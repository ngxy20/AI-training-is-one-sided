"""Steps 2 & 3: fine-tune orchestration and Agent planning/execution."""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import time

TMP = pathlib.Path(tempfile.mkdtemp(prefix="aixian-steps23-"))
os.environ["AIXIAN_HOME"] = str(TMP / "home")
os.environ["AIXIAN_WEB_DIST"] = str(TMP / "no-dist")
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from aixian.app import app  # noqa: E402

API = "/api/v1"


def wait_job(client: TestClient, job_id: str, timeout: float = 25.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"{API}/jobs/{job_id}").json()
        if data.get("status") in ("succeeded", "failed", "cancelled"):
            return data
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} 超时")


TRAIN_SCRIPT = '''"""Trainer-owned script: writes an adapter artifact using injected paths."""
import json, os, pathlib
out = pathlib.Path(os.environ["AIXIAN_ADAPTER_OUTPUT"])
out.mkdir(parents=True, exist_ok=True)
(out / "adapter_model.safetensors").write_bytes(b"demo")
pathlib.Path(os.environ["AIXIAN_METRICS_PATH"]).write_text(json.dumps({"loss": 0.12}))
print("base:", os.environ.get("AIXIAN_BASE_MODEL", ""))
print("method:", os.environ.get("AIXIAN_FINETUNE_METHOD", ""))
'''


def test_finetune_and_agent():
    with TestClient(app) as c:
        project = c.post(f"{API}/projects", json={"name": "微调与 Agent"}).json()
        pid = project["id"]

        # --- fixtures: base model, dataset, trainer's script ---
        base = c.post(f"{API}/projects/{pid}/models", json={
            "name": "基座 Qwen", "kind": "base",
            "ref_json": {"type": "transformers", "model": str(TMP / "base")},
        }).json()
        dataset = c.post(f"{API}/projects/{pid}/datasets", json={"name": "指令集"}).json()
        version = c.post(f"{API}/datasets/{dataset['id']}/versions", json={
            "records": [{"instruction": "问", "output": "答"}]}).json()
        script = c.post(f"{API}/projects/{pid}/scripts", json={
            "name": "我的微调脚本", "type": "py", "content": TRAIN_SCRIPT}).json()

        # --- step 2: templates ---
        catalog = c.get(f"{API}/projects/{pid}/finetune-templates").json()
        assert len([t for t in catalog["items"] if t["builtin"]]) == 4
        assert "lora" in catalog["methods"] and "alpaca" in catalog["formats"]
        custom = c.post(f"{API}/projects/{pid}/finetune-templates", json={
            "name": "团队 LoRA 模板", "method": "lora", "dataset_format": "alpaca",
            "defaults_json": {"lora_r": 8}}).json()
        assert custom["id"] in [t["id"] for t in c.get(f"{API}/projects/{pid}/finetune-templates").json()["items"]]

        check = c.post(f"{API}/projects/{pid}/dataset-versions/{version['id']}/check-format?fmt=alpaca").json()
        assert check["ok"] is True

        config = c.post(f"{API}/projects/{pid}/finetune-templates/instantiate", json={
            "template_id": "builtin:lora", "script_id": script["id"],
            "base_model_id": base["id"], "params": {"num_epochs": 5}}).json()
        assert config["finetune_json"]["base_model_id"] == base["id"]
        assert config["params_json"]["num_epochs"] == 5
        assert config["params_json"]["lora_r"] == 16

        # --- one-click fine-tune run: adapter is auto-registered ---
        run = c.post(f"{API}/projects/{pid}/finetune-runs", json={
            "name": "LoRA 微调 1", "template_id": "builtin:lora",
            "script_id": script["id"], "base_model_id": base["id"],
            "dataset_version_ids": [version["id"]]}).json()
        assert wait_job(c, run["job_id"])["status"] == "succeeded"
        detail = c.get(f"{API}/runs/{run['run_id']}").json()
        adapters = detail["artifacts_json"]["registered_adapters"]
        assert len(adapters) == 1
        produced = c.get(f"{API}/models/{adapters[0]['id']}").json()
        assert produced["kind"] == "adapter"
        assert produced["base_model_id"] == base["id"]
        assert produced["source_run_id"] == run["run_id"]
        assert produced["source_run"]["id"] == run["run_id"]
        graph = c.get(f"{API}/projects/{pid}/lineage").json()
        assert any(e["label"] == "微调自" for e in graph["edges"])
        assert any(e["label"] == "训练产出" for e in graph["edges"])

        # invalid format is reported, not silently accepted
        raw = c.post(f"{API}/projects/{pid}/datasets", json={"name": "原始"}).json()
        raw_v = c.post(f"{API}/datasets/{raw['id']}/versions", json={
            "records": [{"text": "没有指令字段"}]}).json()
        check_bad = c.post(
            f"{API}/projects/{pid}/dataset-versions/{raw_v['id']}/check-format?fmt=alpaca").json()
        assert check_bad["ok"] is False and "instruction" in check_bad["missing"]

        # --- step 3: Agent tools & rule plan ---
        tools = c.get(f"{API}/projects/{pid}/agent/tools").json()
        assert len(tools["items"]) >= 15 and "finetune.run" in tools["high_risk"]
        plan = c.post(f"{API}/projects/{pid}/agent/plan", json={"goal": "帮我做一次评测并生成报告"}).json()
        assert plan["source"] == "rules" and any(s["tool"] == "eval.run" for s in plan["plan_json"])
        session_id = plan["id"]

        # human-in-the-loop: edit plan down to safe read-only steps, then execute
        safe = [{"tool": "project.stats", "args": {}},
                {"tool": "model.list", "args": {}},
                {"tool": "audit.list", "args": {}}]
        edited = c.put(f"{API}/agent/sessions/{session_id}/plan", json={"steps": safe}).json()
        assert len(edited["plan_json"]) == 3
        execution = c.post(f"{API}/agent/sessions/{session_id}/execute",
                           json={"confirmed": True}).json()
        assert wait_job(c, execution["job_id"])["status"] == "succeeded"
        session = c.get(f"{API}/agent/sessions/{session_id}").json()
        assert session["status"] == "succeeded" and len(session["result_json"]) == 3
        assert all(r["status"] == "succeeded" for r in session["result_json"])

        # high-risk step is gated without confirmation
        risky_plan = c.post(f"{API}/projects/{pid}/agent/plan", json={"goal": "配置一个定时任务"}).json()
        c.put(f"{API}/agent/sessions/{risky_plan['id']}/plan", json={
            "steps": [{"tool": "schedule.create", "args": {"name": "x", "type": "command",
                                                            "cron_expr": "*/5 * * * *"}}]})
        gated = c.post(f"{API}/agent/sessions/{risky_plan['id']}/execute", json={}).json()
        assert wait_job(c, gated["job_id"])["status"] == "succeeded"
        gated_session = c.get(f"{API}/agent/sessions/{risky_plan['id']}").json()
        assert gated_session["status"] == "needs_confirmation"
        assert gated_session["result_json"][0]["status"] == "needs_confirmation"
        assert c.get(f"{API}/projects/{pid}/schedules").json()["total"] == 0

        # LLM-driven plan from a registered model
        brain = c.post(f"{API}/projects/{pid}/models", json={
            "name": "编排大脑", "kind": "endpoint",
            "ref_json": {"type": "static", "outputs": {
                "agent-plan": '[{"tool":"project.stats","args":{},"reason":"先看概览"}]'}},
        }).json()
        llm_plan = c.post(f"{API}/projects/{pid}/agent/plan", json={
            "goal": "查看项目状态", "model_id": brain["id"]}).json()
        assert llm_plan["source"] == "llm"
        assert llm_plan["plan_json"][0]["tool"] == "project.stats"
