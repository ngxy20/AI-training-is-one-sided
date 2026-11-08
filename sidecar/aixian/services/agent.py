"""Agent orchestration over the existing API.

The Agent is a planning/execution shell, not a new system: tools are existing
endpoints, the brain is a model the trainer registered, execution reuses the
Job table, WS logs and audit trail. No framework, no bundled model.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..errors import ApiError
from . import model_adapters, registry as model_registry

TOOLS: list[dict[str, Any]] = [
    {"name": "project.stats", "label": "查看项目概览", "method": "GET",
     "path": "/projects/{pid}/stats", "risk": "low", "fields": []},
    {"name": "dataset.create", "label": "新建数据集", "method": "POST",
     "path": "/projects/{pid}/datasets", "risk": "low", "fields": ["name"]},
    {"name": "dataset.import", "label": "导入数据集版本", "method": "POST",
     "path": "/datasets/{id}/versions", "risk": "low", "fields": ["id", "path", "fmt"]},
    {"name": "dataset.versions", "label": "列出数据集版本", "method": "GET",
     "path": "/projects/{pid}/dataset-versions", "risk": "low", "fields": []},
    {"name": "dataset.export", "label": "导出训练格式", "method": "POST",
     "path": "/dataset-versions/{id}/export", "risk": "low", "fields": ["id", "format"]},
    {"name": "pipeline.create", "label": "新建清洗 Pipeline", "method": "POST",
     "path": "/projects/{pid}/pipelines", "risk": "low", "fields": ["name", "nodes_json"]},
    {"name": "pipeline.run", "label": "复跑清洗 Pipeline", "method": "POST",
     "path": "/pipelines/{id}/run", "risk": "medium", "fields": ["id", "source_version_id"]},
    {"name": "script.create", "label": "新建脚本", "method": "POST",
     "path": "/projects/{pid}/scripts", "risk": "low", "fields": ["name", "type"]},
    {"name": "model.list", "label": "列出已注册模型", "method": "GET",
     "path": "/projects/{pid}/models", "risk": "low", "fields": []},
    {"name": "model.register", "label": "注册模型路径", "method": "POST",
     "path": "/projects/{pid}/models", "risk": "medium", "fields": ["name", "ref_json"]},
    {"name": "model.test", "label": "测试模型调用", "method": "POST",
     "path": "/models/{id}/test", "risk": "low", "fields": ["id", "prompt"]},
    {"name": "finetune.templates", "label": "查看微调模板", "method": "GET",
     "path": "/projects/{pid}/finetune-templates", "risk": "low", "fields": []},
    {"name": "finetune.run", "label": "提交微调任务", "method": "POST",
     "path": "/projects/{pid}/finetune-runs", "risk": "high",
     "fields": ["template_id", "base_model_id", "script_id", "dataset_version_ids"]},
    {"name": "suite.create", "label": "新建评测套件", "method": "POST",
     "path": "/projects/{pid}/eval-suites", "risk": "low", "fields": ["name", "type", "cases_json"]},
    {"name": "eval.run", "label": "运行评测", "method": "POST",
     "path": "/eval-suites/{id}/runs", "risk": "medium", "fields": ["id", "model_id"]},
    {"name": "ab.generate", "label": "自动生成 A/B 对比", "method": "POST",
     "path": "/projects/{pid}/ab-tests", "risk": "high",
     "fields": ["model_a_id", "model_b_id", "prompt_set_json"]},
    {"name": "report.create", "label": "生成报告", "method": "POST",
     "path": "/projects/{pid}/reports", "risk": "low", "fields": ["name", "linked_entities_json"]},
    {"name": "schedule.create", "label": "新建定时任务", "method": "POST",
     "path": "/projects/{pid}/schedules", "risk": "high", "fields": ["name", "type", "cron_expr"]},
    {"name": "audit.list", "label": "查看审计事件", "method": "GET",
     "path": "/audit-events", "risk": "low", "fields": []},
]

TOOL_NAMES = {t["name"]: t for t in TOOLS}
HIGH_RISK = {t["name"] for t in TOOLS if t["risk"] == "high"}

_RULE_PLANS: list[tuple[tuple[str, ...], list[str]]] = [
    (("导入", "收集", "接入", "拉取"), ["dataset.create", "dataset.import", "dataset.versions"]),
    (("清洗", "去重", "过滤"), ["pipeline.create", "pipeline.run"]),
    (("微调", "训练", "lora", "qlora"), ["model.list", "finetune.templates", "finetune.run"]),
    (("评测", "测试", "准确率", "边界"), ["model.list", "suite.create", "eval.run"]),
    (("对比", "a/b", "ab"), ["model.list", "ab.generate"]),
    (("报告", "汇总", "导出"), ["report.create"]),
    (("注册", "模型路径", "添加模型"), ["model.register", "model.test"]),
    (("定时", "每天", "自动运行"), ["schedule.create"]),
    (("审计", "记录", "追踪"), ["audit.list"]),
]

LLM_PLAN_PROMPT = """你是 AI 训练工作台的编排助手。可用工具（名称: 说明: 参数）如下：
{tools}

用户目标：{goal}

请只输出一个 JSON 数组，每个元素形如 {{"tool":"工具名","args":{{参数}},"reason":"一句话理由"}}。
没有足够信息时参数留空对象，不要编造路径或 ID。最多 6 步，高风险动作（finetune.run / ab.generate / schedule.create）放最后。
只输出 JSON，不要解释。"""


def rule_plan(goal: str) -> list[dict[str, Any]]:
    text = goal.lower()
    steps: list[str] = []
    for keywords, names in _RULE_PLANS:
        if any(word in text for word in keywords):
            steps.extend(name for name in names if name not in steps)
    if not steps:
        steps = ["project.stats", "model.list", "audit.list"]
    return [{"tool": name, "args": {}, "reason": "按目标关键词匹配的内置流程"}
            for name in steps[:6]]


def llm_plan(goal: str, model_id: str, session, project_id: str) -> list[dict[str, Any]]:
    ref, _ = model_registry.resolve(session, project_id, model_id)
    prepared = model_adapters.prepare(ref, session)
    tool_lines = "\n".join(
        f"- {t['name']}: {t['label']}; 参数 {', '.join(t['fields']) or '无'}" for t in TOOLS)
    prompt = LLM_PLAN_PROMPT.format(tools=tool_lines, goal=goal)
    text = model_adapters.generate({"id": "agent-plan", "input": prompt},
                                   prepared, project_id=project_id, index=0)
    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        raise ApiError("AGENT_PLAN_PARSE", "模型未返回 JSON 计划，已回退内置流程", 422, text[:300])
    parsed = json.loads(match.group())
    if not isinstance(parsed, list):
        raise ApiError("AGENT_PLAN_PARSE", "计划格式不是数组", 422)
    valid = []
    for step in parsed[:6]:
        if not isinstance(step, dict) or step.get("tool") not in TOOL_NAMES:
            continue
        valid.append({"tool": step["tool"], "args": step.get("args") or {},
                      "reason": str(step.get("reason") or "")})
    if not valid:
        raise ApiError("AGENT_PLAN_PARSE", "模型没有给出任何有效工具", 422)
    return valid


def build_plan(goal: str, model_id: str | None, session, project_id: str) -> dict[str, Any]:
    if not goal.strip():
        raise ApiError("VALIDATION_ERROR", "请描述目标", 422)
    if model_id:
        try:
            steps = llm_plan(goal, model_id, session, project_id)
            return {"steps": steps, "source": "llm", "warnings": []}
        except Exception as exc:  # noqa: BLE001 - fall back to a deterministic plan
            steps = rule_plan(goal)
            return {"steps": steps, "source": "rules",
                    "warnings": [f"模型规划失败，已回退内置流程：{type(exc).__name__}: {exc}"]}
    return {"steps": rule_plan(goal), "source": "rules", "warnings": []}


def describe() -> list[dict[str, Any]]:
    return [dict(t) for t in TOOLS]


def _request_for(step: dict[str, Any], pid: str) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    tool = TOOL_NAMES.get(step.get("tool"))
    if tool is None:
        raise ApiError("AGENT_TOOL", f"未知工具 {step.get('tool')}", 422)
    args = dict(step.get("args") or {})
    path = str(tool["path"]).replace("{pid}", pid)
    params: dict[str, Any] = {}
    if "{id}" in path:
        ident = args.pop("id", None)
        if not ident:
            raise ApiError("AGENT_ARGS", f"工具 {tool['name']} 缺少 id", 422)
        path = path.replace("{id}", str(ident))
    if tool["name"] == "audit.list":
        params["pid"] = pid
    body = {key: value for key, value in args.items() if value not in (None, "", [], {})}
    if tool["name"] == "ab.generate":
        body["generate"] = True
    if tool["name"] == "dataset.import":
        body.setdefault("workspace_relative", False)
    return tool["method"], "/api/v1" + path, body, params


async def execute(steps: list[dict[str, Any]], project_id: str, ctx, *,
                  confirmed: bool = False, continue_on_error: bool = False) -> list[dict[str, Any]]:
    import httpx

    from ..app import app as application

    results: list[dict[str, Any]] = []
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://aixian.local",
                                 timeout=60) as client:
        for index, step in enumerate(steps):
            name = step.get("tool", "")
            if name in HIGH_RISK and not confirmed:
                results.append({"step": index + 1, "tool": name, "status": "needs_confirmation",
                                "reason": "高风险动作需人工确认"})
                ctx.log(f"[agent] 步骤 {index + 1} {name} 等待人工确认")
                continue
            try:
                method, path, body, params = _request_for(step, project_id)
                ctx.log(f"[agent] 步骤 {index + 1}/{len(steps)} {method} {path}")
                response = await client.request(method, path, json=body or None, params=params or None)
                try:
                    payload = response.json()
                except ValueError:
                    payload = response.text[:500]
                ok = 200 <= response.status_code < 300
                entry = {"step": index + 1, "tool": name, "status": "succeeded" if ok else "failed",
                         "http_status": response.status_code, "result": payload,
                         "reason": step.get("reason", "")}
                results.append(entry)
                ctx.log(f"[agent] 步骤 {index + 1} {'完成' if ok else '失败'} ({response.status_code})")
                if not ok and not continue_on_error:
                    break
            except Exception as exc:  # noqa: BLE001
                results.append({"step": index + 1, "tool": name, "status": "failed",
                                "error": f"{type(exc).__name__}: {exc}"})
                ctx.log(f"[agent] 步骤 {index + 1} 异常: {exc}")
                if not continue_on_error:
                    break
            ctx.progress((index + 1) / max(1, len(steps)))
    return results
