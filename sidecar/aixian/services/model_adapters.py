"""Model inference adapters.

Turns an evaluation case (a prompt) into a model output. Offline adapters
(``inline`` / ``echo`` / ``static`` / ``dataset``) are kept for reproducibility;
the inference adapters (``http`` / ``openai`` / ``vllm`` / ``transformers`` /
``subprocess`` / ``plugin``) make EvalRun, ABTest and LLM-as-judge actually call
a model instead of scoring pre-recorded results.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .. import workspace
from ..errors import ApiError
from ..plugin_loader import registry
from ..plugin_sdk import ModelCase

LogFn = Callable[[str], None] | None

ADAPTERS: list[dict[str, Any]] = [
    {"type": "inline", "label": "离线 · 用例内输出", "offline": True,
     "description": "读取 case.output，用于复现历史评测，不调用模型",
     "fields": [{"key": "field", "label": "输出字段", "default": "output"}]},
    {"type": "echo", "label": "离线 · 回显输入", "offline": True,
     "description": "把 case.input 原样作为输出，仅用于调试", "fields": []},
    {"type": "static", "label": "离线 · 静态映射", "offline": True,
     "description": "按 case.id 或序号查预置输出", "fields": []},
    {"type": "dataset", "label": "离线 · 数据集版本", "offline": True,
     "description": "从数据集版本记录里读取输出列",
     "fields": [{"key": "dataset_version_id", "label": "数据集版本 ID", "required": True},
                {"key": "field", "label": "输出字段", "default": "output"}]},
    {"type": "openai", "label": "OpenAI 兼容接口", "offline": False,
     "description": "任何 /v1/chat/completions 服务（OpenAI / vLLM / Ollama / LM Studio / OneAPI）",
     "fields": [
         {"key": "base_url", "label": "Base URL", "default": "http://127.0.0.1:8000/v1", "required": True},
         {"key": "model", "label": "模型名", "default": "default", "required": True},
         {"key": "api_key", "label": "API Key（可选）", "default": ""},
         {"key": "system", "label": "System Prompt（可选）", "default": ""},
         {"key": "temperature", "label": "temperature", "default": 0.2, "type": "number"},
         {"key": "max_tokens", "label": "max_tokens", "default": 512, "type": "number"},
         {"key": "field", "label": "响应字段路径", "default": "choices.0.message.content"},
         {"key": "timeout", "label": "超时(秒)", "default": 60, "type": "number"},
     ]},
    {"type": "vllm", "label": "vLLM /generate", "offline": False,
     "description": "vLLM 原生生成接口（非 OpenAI 兼容模式）",
     "fields": [
         {"key": "url", "label": "生成端点", "default": "http://127.0.0.1:8000/generate", "required": True},
         {"key": "field", "label": "响应字段路径", "default": "text.0"},
         {"key": "max_tokens", "label": "max_tokens", "default": 512, "type": "number"},
         {"key": "temperature", "label": "temperature", "default": 0.2, "type": "number"},
         {"key": "timeout", "label": "超时(秒)", "default": 60, "type": "number"},
     ]},
    {"type": "http", "label": "自定义 HTTP", "offline": False,
     "description": "任意 HTTP JSON 端点，支持 {prompt} 模板与自定义 headers",
     "fields": [
         {"key": "url", "label": "URL", "required": True},
         {"key": "payload_template", "label": "请求体模板(JSON，可用 {prompt})", "default": '{"prompt": "{prompt}"}'},
         {"key": "headers", "label": "请求头(JSON)", "default": {}},
         {"key": "field", "label": "响应字段路径", "default": "output"},
         {"key": "timeout", "label": "超时(秒)", "default": 30, "type": "number"},
     ]},
    {"type": "transformers", "label": "本地 Transformers", "offline": True,
     "description": "本机加载 HuggingFace 模型（需安装 transformers + torch），单例复用",
     "fields": [
         {"key": "model", "label": "模型路径 / Hub ID", "required": True},
         {"key": "task", "label": "任务", "default": "text-generation"},
         {"key": "device", "label": "device (-1=CPU, 0=GPU0)", "default": -1, "type": "number"},
         {"key": "max_new_tokens", "label": "max_new_tokens", "default": 256, "type": "number"},
         {"key": "strip_prompt", "label": "去掉回显的 prompt", "default": True, "type": "checkbox"},
     ]},
    {"type": "subprocess", "label": "本地命令行模型", "offline": True,
     "description": "把 prompt 通过 stdin 传给本地命令（llama.cpp / 自定义推理脚本），stdout 作为输出",
     "fields": [
         {"key": "command", "label": "命令（字符串或参数数组）", "required": True},
         {"key": "cwd", "label": "工作目录（工作区内相对路径）", "default": ""},
         {"key": "timeout", "label": "超时(秒)", "default": 120, "type": "number"},
     ]},
    {"type": "plugin", "label": "插件模型适配器", "offline": False,
     "description": "由 model_adapter 扩展点提供推理能力",
     "fields": [{"key": "plugin_id", "label": "插件 ID（留空取第一个）", "default": ""}]},
]

ADAPTER_TYPES = tuple(item["type"] for item in ADAPTERS)

_PIPELINE_CACHE: dict[tuple[Any, ...], Any] = {}
_PIPELINE_LOCK = threading.Lock()


def describe() -> list[dict[str, Any]]:
    return [dict(item) for item in ADAPTERS]


def _prompt(case: dict[str, Any], ref: dict[str, Any]) -> str:
    template = ref.get("prompt_template")
    if template:
        try:
            return str(template).format(**case)
        except (KeyError, IndexError, ValueError):
            return str(template)
    return str(case.get("input", case.get("prompt", "")))


def _extract(data: Any, field: str) -> str:
    current = data
    for part in str(field or "output").split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, (list, tuple)):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return ""
        else:
            return ""
        if current is None:
            return ""
    if isinstance(current, str):
        return current
    if isinstance(current, (dict, list)):
        return json.dumps(current, ensure_ascii=False)
    return str(current)


def _json_body(template: Any, prompt: str) -> dict[str, Any]:
    if isinstance(template, dict):
        raw = json.dumps(template, ensure_ascii=False)
    else:
        raw = str(template or '{"prompt": "{prompt}"}')
    text = raw.replace("{prompt}", json.dumps(prompt, ensure_ascii=False)[1:-1])
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ApiError("ADAPTER_CONFIG", "请求体模板必须是 JSON 对象", 422)
    return parsed


def _post(url: str, body: dict[str, Any], headers: dict[str, Any], timeout: float) -> Any:
    import httpx

    response = httpx.post(url, json=body, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _openai(case: dict[str, Any], ref: dict[str, Any]) -> str:
    base = str(ref.get("base_url") or "http://127.0.0.1:8000/v1").rstrip("/")
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    messages: list[dict[str, str]] = []
    if ref.get("system"):
        messages.append({"role": "system", "content": str(ref["system"])})
    messages.append({"role": "user", "content": _prompt(case, ref)})
    body = {
        "model": ref.get("model", "default"), "messages": messages, "stream": False,
        "temperature": float(ref.get("temperature", 0.2)),
        "max_tokens": int(ref.get("max_tokens", 512)),
    }
    body.update(ref.get("extra_body") or {})
    headers: dict[str, str] = {"Content-Type": "application/json", **(ref.get("headers") or {})}
    if ref.get("api_key"):
        headers["Authorization"] = f"Bearer {ref['api_key']}"
    return _extract(_post(url, body, headers, float(ref.get("timeout", 60))),
                    str(ref.get("field", "choices.0.message.content")))


def _vllm(case: dict[str, Any], ref: dict[str, Any]) -> str:
    prompt = _prompt(case, ref)
    body = {
        "prompt": prompt,
        "max_tokens": int(ref.get("max_tokens", 512)),
        "temperature": float(ref.get("temperature", 0.2)),
    }
    body.update(ref.get("extra_body") or {})
    data = _post(str(ref["url"]), body, {"Content-Type": "application/json", **(ref.get("headers") or {})},
                 float(ref.get("timeout", 60)))
    return _extract(data, str(ref.get("field", "text.0")))


def _http(case: dict[str, Any], ref: dict[str, Any]) -> str:
    body = _json_body(ref.get("payload_template"), _prompt(case, ref))
    data = _post(str(ref["url"]), body, {"Content-Type": "application/json", **(ref.get("headers") or {})},
                 float(ref.get("timeout", 30)))
    return _extract(data, str(ref.get("field", "output")))


def _transformers(case: dict[str, Any], ref: dict[str, Any]) -> str:
    try:
        from transformers import pipeline
    except ImportError as exc:
        raise ApiError("MISSING_DEPENDENCY", "本地推理需要安装 transformers 与 torch", 500, str(exc)) from exc
    key = (ref.get("model"), ref.get("task", "text-generation"), ref.get("device", -1))
    with _PIPELINE_LOCK:
        if key not in _PIPELINE_CACHE:
            _PIPELINE_CACHE[key] = pipeline(str(key[1]), model=str(key[0]), device=int(key[2]))
        pipe = _PIPELINE_CACHE[key]
    prompt = _prompt(case, ref)
    with _PIPELINE_LOCK:
        result = pipe(prompt, max_new_tokens=int(ref.get("max_new_tokens", 256)),
                      do_sample=float(ref.get("temperature", 0)) > 0,
                      temperature=float(ref.get("temperature", 0)) or None,
                      num_return_sequences=1)
    text = ""
    if isinstance(result, list) and result:
        text = str(result[0].get("generated_text", result[0]))
    else:
        text = str(result)
    if ref.get("strip_prompt", True) and text.startswith(prompt):
        text = text[len(prompt):]
    return text.strip()


def _subprocess(case: dict[str, Any], ref: dict[str, Any], project_id: str | None) -> str:
    if not project_id:
        raise ApiError("ADAPTER_CONFIG", "subprocess 适配器需要项目上下文", 422)
    command = ref.get("command")
    if not command:
        raise ApiError("ADAPTER_CONFIG", "subprocess 适配器需要 command", 422)
    root = workspace.ensure_workspace(project_id)
    sub = str(ref.get("cwd") or "").strip()
    cwd = workspace.resolve(project_id, sub) if sub else root
    if not cwd.is_dir():
        cwd = root
    use_shell = isinstance(command, str)
    completed = subprocess.run(command, shell=use_shell, cwd=str(cwd),
                               input=_prompt(case, ref), capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=float(ref.get("timeout", 120)))
    if completed.returncode != 0:
        raise ApiError("ADAPTER_EXEC", f"推理命令退出码 {completed.returncode}", 500,
                       (completed.stderr or "")[-500:])
    return (completed.stdout or "").strip()


def _plugin(case: dict[str, Any], ref: dict[str, Any], session) -> str:
    plugin_id = str(ref.get("plugin_id") or "")
    enabled = ref.get("_enabled_plugins")
    if enabled is None:
        enabled = registry.enabled_ids(session) if session is not None else None
    for plugin, _, impl in registry.implementations("model_adapter", enabled):
        if plugin_id and plugin.id != plugin_id:
            continue
        registry.require_permission(plugin, "model:invoke")
        return str(impl.generate(ModelCase(
            id=str(case.get("id", "")), input=_prompt(case, ref),
            expected=case.get("expected"), category=str(case.get("category", "general")),
            metadata=case.get("metadata") or {},
        ), ref.get("config") or ref))
    raise ApiError("PLUGIN_NOT_FOUND", f"没有可用的模型适配器插件: {plugin_id or '(任意)'}", 404)


def _dataset_outputs(ref: dict[str, Any], session) -> dict[str, str]:
    from sqlalchemy import select

    from ..models import Record

    version_id = ref.get("dataset_version_id")
    if not version_id or session is None:
        return {}
    field = str(ref.get("field", "output"))
    rows = session.execute(select(Record).where(Record.dataset_version_id == version_id)).scalars().all()
    return {str(i): str((row.payload_json or {}).get(field, (row.payload_json or {}).get("response", "")))
            for i, row in enumerate(rows)}


def generate(case: dict[str, Any], ref: dict[str, Any], *, session=None,
             project_id: str | None = None, index: int = 0, log: LogFn = None) -> str:
    """Generate one output. Raises on configuration/runtime errors (caller decides)."""
    kind = str(ref.get("type") or "echo")
    started = time.perf_counter()
    if kind == "echo":
        output = str(case.get("input", ""))
    elif kind == "static":
        outputs = ref.get("outputs") or {}
        output = str(outputs.get(str(case.get("id")), outputs.get(str(index), "")))
    elif kind == "dataset":
        outputs = ref.get("_resolved_outputs") or _dataset_outputs(ref, session)
        output = outputs.get(str(index % max(1, len(outputs))), "") if outputs else ""
    elif kind == "inline":
        output = str(case.get(str(ref.get("field", "output")), ""))
    elif kind == "http":
        output = _http(case, ref)
    elif kind == "openai":
        output = _openai(case, ref)
    elif kind == "vllm":
        output = _vllm(case, ref)
    elif kind == "transformers":
        output = _transformers(case, ref)
    elif kind == "subprocess":
        output = _subprocess(case, ref, project_id)
    elif kind == "plugin":
        output = _plugin(case, ref, session)
    else:
        raise ApiError("UNSUPPORTED_MODEL_REF", f"未知模型适配器: {kind}，可用: {ADAPTER_TYPES}", 422)
    if log:
        log(f"[model:{kind}] 用例 {index + 1} 用时 {round((time.perf_counter() - started) * 1000)}ms")
    return output


def prepare(ref: dict[str, Any], session=None) -> dict[str, Any]:
    """Resolve DB-backed adapters once so batch workers can run without a shared Session."""
    prepared = dict(ref or {})
    if prepared.get("type") == "dataset":
        prepared["_resolved_outputs"] = _dataset_outputs(prepared, session)
    if prepared.get("type") == "plugin" and session is not None:
        prepared["_enabled_plugins"] = registry.enabled_ids(session)
    return prepared


def generate_batch(cases: list[dict[str, Any]], ref: dict[str, Any], *, session=None,
                   project_id: str | None = None, log: LogFn = None) -> list[str]:
    """Ordered batch generation with bounded concurrency; per-case failures are isolated."""
    prepared = prepare(ref, session)
    concurrency = int(prepared.get("concurrency") or 1)
    if prepared.get("type") in ("transformers", "dataset", "static", "echo", "inline"):
        concurrency = 1

    def one(args: tuple[int, dict[str, Any]]) -> str:
        index, case = args
        try:
            return generate(case, prepared, project_id=project_id, index=index, log=log)
        except Exception as exc:  # noqa: BLE001
            message = f"[模型调用失败: {type(exc).__name__}: {exc}]"
            if log:
                log(f"[model] 用例 {index + 1} 失败: {exc}")
            if prepared.get("fail_fast"):
                raise
            return message

    tasks = list(enumerate(cases))
    if concurrency <= 1:
        return [one(task) for task in tasks]
    with ThreadPoolExecutor(max_workers=min(concurrency, 16)) as pool:
        return list(pool.map(one, tasks))


JUDGE_TEMPLATE = (
    "你是评测裁判。请只输出一个 0 到 1 之间的数字，表示模型回答相对于参考答案的正确程度。\n"
    "问题：{input}\n参考答案：{expected}\n模型回答：{output}\n分数："
)


def judge_score(case: dict[str, Any], output: str, scorer: dict[str, Any], *,
                session=None, project_id: str | None = None, log: LogFn = None) -> float:
    """Real LLM-as-judge: ask a judge model to grade the generated output."""
    judge_ref = scorer.get("judge_model_ref")
    if not judge_ref:
        raise ApiError("JUDGE_CONFIG", "llm_judge 评分器需要 judge_model_ref", 422)
    template = str(scorer.get("prompt_template") or JUDGE_TEMPLATE)
    try:
        prompt = template.format(**{**case, "output": output})
    except (KeyError, IndexError, ValueError):
        prompt = template
    text = generate({"id": case.get("id", ""), "input": prompt}, dict(judge_ref),
                    session=session, project_id=project_id, log=log)
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return 0.0
    value = float(match.group())
    if value > 1:
        value = value / 100 if value <= 100 else value / 10
    return round(min(1.0, max(0.0, value)), 4)
