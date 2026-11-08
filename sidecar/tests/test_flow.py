"""End-to-end MVP acceptance test (P0 数据闭环 + P1 训练 + P2 评测报告 + 插件 + 审计).

Run: cd sidecar && pytest -q tests/test_flow.py
"""
from __future__ import annotations

import os
import pathlib
import sqlite3
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = pathlib.Path(tempfile.mkdtemp(prefix="aixian-test-"))
os.environ["AIXIAN_HOME"] = str(TMP / "home")
os.environ["AIXIAN_WEB_DIST"] = str(TMP / "no-dist")

from fastapi.testclient import TestClient  # noqa: E402

from aixian.app import app  # noqa: E402

API = "/api/v1"


def wait_job(client: TestClient, job_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"{API}/jobs/{job_id}").json()
        if data.get("status") in ("succeeded", "failed", "cancelled"):
            return data
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} 超时")


def test_full_lifecycle():
    with TestClient(app) as c:
        health = c.get(f"{API}/health").json()
        assert health["status"] == "ok" and health["version"] == "0.1.0"

        # 1. 多项目隔离
        a = c.post(f"{API}/projects", json={"name": "项目 A"}).json()
        b = c.post(f"{API}/projects", json={"name": "项目 B"}).json()
        assert a["id"] != b["id"] and a["workspace_path"] != b["workspace_path"]
        assert pathlib.Path(a["workspace_path"], "meta.db").exists()
        assert pathlib.Path(b["workspace_path"], "meta.db").exists()
        pid = a["id"]
        assert c.post(f"{API}/projects/{pid}/open").status_code == 200

        # 2. 外部 SQLite 数据源：测试 / Schema / SQL / 导入数据集
        db_path = TMP / "legacy.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE posts (id INTEGER, text TEXT, label TEXT)")
            conn.executemany("INSERT INTO posts VALUES (?,?,?)",
                             [(1, "你好世界", "问候"), (2, "hello world", "问候"), (3, "重复内容", "其他")])
            conn.commit()
        source = c.post(f"{API}/projects/{pid}/datasources", json={
            "name": "生产库", "type": "sqlite", "config": {"path": str(db_path)}
        }).json()
        assert c.post(f"{API}/datasources/{source['id']}/test").json()["ok"] is True
        schema = c.get(f"{API}/datasources/{source['id']}/schema").json()
        assert schema["tables"][0]["name"] == "posts"
        result = c.post(f"{API}/datasources/{source['id']}/query", json={"sql": "SELECT * FROM posts"}).json()
        assert result["row_count"] == 3
        assert c.post(f"{API}/datasources/{source['id']}/query",
                      json={"sql": "DELETE FROM posts"}).status_code == 403
        imported = c.post(f"{API}/datasources/{source['id']}/import", json={
            "sql": "SELECT * FROM posts", "dataset_name": "原始语料"
        }).json()
        assert imported["record_count"] == 3

        # 3. 不可变数据集版本 / 预览 / 训练格式导出
        dataset = c.post(f"{API}/projects/{pid}/datasets", json={"name": "手工数据集"}).json()
        v1 = c.post(f"{API}/datasets/{dataset['id']}/versions", json={
            "records": [{"text": "样本一", "label": "A"}, {"text": "样本二", "label": "B"},
                        {"text": "样本一", "label": "A"}],
            "changelog": "首批导入",
        }).json()
        assert v1["version"] == 1 and v1["record_count"] == 3 and v1["content_hash"]
        v2 = c.post(f"{API}/datasets/{dataset['id']}/versions", json={"records": [{"text": "新样本"}]}).json()
        assert v2["version"] == 2 and v2["parent_version_id"] == v1["id"]
        assert pathlib.Path(a["workspace_path"], v1["manifest_path"]).exists()
        records = c.get(f"{API}/dataset-versions/{v1['id']}/records", params={"size": 2}).json()
        assert records["total"] == 3 and len(records["items"]) == 2
        exported = c.post(f"{API}/dataset-versions/{v1['id']}/export",
                          json={"format": "alpaca", "mapping": {"instruction": "text", "output": "label"}}).json()
        assert exported["record_count"] == 3 and "instruction" in exported["preview"][0]

        # 4. 清洗 Pipeline 复跑 -> 新版本
        pipeline = c.post(f"{API}/projects/{pid}/pipelines", json={
            "name": "去重+长度", "nodes_json": [
                {"op": "dedup", "params": {"field": "text"}},
                {"op": "length_range", "params": {"field": "text", "min": 1, "max": 100}},
            ]
        }).json()
        job = c.post(f"{API}/pipelines/{pipeline['id']}/run",
                     json={"source_version_id": v1["id"]}).json()
        assert wait_job(c, job["job_id"])["status"] == "succeeded"
        runs = c.get(f"{API}/pipelines/{pipeline['id']}/runs").json()
        assert runs[0]["stats_json"]["output"] == 2
        clean_version_id = runs[0]["output_version_id"]

        # 5. 收集脚本（版本化）产物落盘
        script = c.post(f"{API}/projects/{pid}/scripts", json={"name": "采集脚本", "type": "py"}).json()
        assert "AIXIAN_OUTPUT" in script["content"]
        c.put(f"{API}/scripts/{script['id']}", json={"content": script["content"]})
        job = c.post(f"{API}/scripts/{script['id']}/run", json={"params": {"n": 4}}).json()
        assert wait_job(c, job["job_id"])["status"] == "succeeded"
        assert job["job_id"]

        # 6. 标注 -> 审核 -> 导出 -> Kappa
        ann_schema = c.post(f"{API}/projects/{pid}/annotation-schemas", json={
            "name": "情感分类", "template_type": "classification",
            "schema_json": {"fields": [{"key": "label", "type": "select", "options": ["正向", "负向"]}]}
        }).json()
        task = c.post(f"{API}/projects/{pid}/annotation-tasks", json={
            "name": "标注任务 1", "dataset_version_id": clean_version_id, "schema_id": ann_schema["id"]
        }).json()
        first = c.get(f"{API}/annotation-tasks/{task['id']}/records").json()["items"][0]
        ann = c.post(f"{API}/annotation-tasks/{task['id']}/annotations", json={
            "record_id": first["id"], "label_json": {"label": "正向"}
        }).json()
        assert c.post(f"{API}/annotation-tasks/{task['id']}/review", json={
            "record_ids": [first["id"]], "decision": "approve", "reviewer": "lead"
        }).json()["reviewed"] == 1
        detail = c.get(f"{API}/annotation-tasks/{task['id']}").json()
        assert detail["stats_json"]["approved"] == 1 and "cohen_kappa" in detail["stats_json"]
        export = c.post(f"{API}/annotation-tasks/{task['id']}/export", json={"only_approved": True}).json()
        assert export["record_count"] == 1

        # 7. 训练配置 / 本地 Runner / 实验关联 / 模型登记
        config = c.post(f"{API}/projects/{pid}/configs", json={
            "name": "默认参数", "script_id": script["id"], "params": {"lr": 0.001, "epochs": 1},
            "runner_type": "local",
        }).json()
        assert "params_yaml" in config
        run = c.post(f"{API}/projects/{pid}/runs", json={
            "name": "实验 1", "config_id": config["id"], "dataset_version_ids": [clean_version_id]
        }).json()
        training_state = wait_job(c, run["job_id"])
        assert training_state["status"] == "succeeded", (training_state.get("error"),
                                                          c.get(f"{API}/jobs/{run['job_id']}/logs").json()["lines"][-20:])
        run_detail = c.get(f"{API}/runs/{run['run_id']}").json()
        assert run_detail["code_version"] and run_detail["dataset_version_ids_json"] == [clean_version_id]
        registered = c.post(f"{API}/runs/{run['run_id']}/register-model",
                            json={"name": "model-v1"}).json()
        assert registered["registered_model_name"] == "model-v1"

        # 8. 评测套件 / EvalRun / 报告强关联
        suite = c.post(f"{API}/projects/{pid}/eval-suites", json={
            "name": "准确性套件", "type": "accuracy",
            "cases_json": [
                {"id": "c1", "input": "问1", "expected": "答1", "output": "答1", "category": "general"},
                {"id": "c2", "input": "问2", "expected": "答2", "output": "错", "category": "boundary"},
            ]
        }).json()
        eval_job = c.post(f"{API}/eval-suites/{suite['id']}/runs", json={
            "model_ref_json": {"type": "inline", "field": "output"},
            "dataset_version_ids": [clean_version_id],
            "scorer_json": {"type": "exact_match"},
        }).json()
        assert wait_job(c, eval_job["job_id"])["status"] == "succeeded"
        eval_run = c.get(f"{API}/eval-runs/{eval_job['eval_run_id']}").json()
        assert eval_run["metrics_json"]["accuracy"] == 0.5 and eval_run["report_id"]

        # 9. A/B 测试 + 四格式报告导出
        ab = c.post(f"{API}/projects/{pid}/ab-tests", json={
            "name": "模型 A/B", "model_a_ref": "model-v1", "model_b_ref": "baseline",
            "prompt_set_json": [
                {"id": "p1", "output_a": "好", "output_b": "差", "score_a": 1, "score_b": 0, "winner": "a"},
                {"id": "p2", "output_a": "差", "output_b": "好", "score_a": 0, "score_b": 1, "winner": "b"},
            ]
        }).json()
        assert ab["result_json"]["total"] == 2 and ab["report_id"]
        report = c.post(f"{API}/projects/{pid}/reports", json={
            "name": "实验总报告", "type": "experiment",
            "linked_entities_json": [
                {"type": "run", "id": run["run_id"]},
                {"type": "dataset_version", "id": clean_version_id},
                {"type": "eval_run", "id": eval_job["eval_run_id"]},
            ],
            "summary_json": {"metrics": {"accuracy": 0.5, "pass_rate": 0.5}},
        }).json()
        assert len(report["linked_entities_json"]) == 3
        assert c.post(f"{API}/projects/{pid}/reports",
                      json={"name": "孤立报告", "linked_entities_json": []}).status_code == 422
        for fmt, marker in (("html", b"<html"), ("json", b"context"), ("md", b"# "), ("pdf", b"%PDF")):
            response = c.get(f"{API}/reports/{report['id']}/export", params={"format": fmt})
            assert response.status_code == 200, (fmt, response.text[:200])
            assert marker in response.content, fmt

        # 10. 插件扫描 / 高风险权限二次确认 / 启用
        scanned = c.post(f"{API}/plugins/scan", params={"pid": pid}).json()
        assert scanned["scanned"] >= 3
        plugins = c.get(f"{API}/plugins", params={"pid": pid}).json()["items"]
        risky = next(p for p in plugins if "network:outbound" in p["permissions"])
        assert c.post(f"{API}/plugins/{risky['id']}/enable",
                      json={"pid": pid, "enabled": True}).status_code == 428
        assert c.post(f"{API}/plugins/{risky['id']}/enable",
                      json={"pid": pid, "enabled": True, "confirm": True}).status_code == 200
        dedup_plugin = next(p for p in plugins
                            if any(e["point"] == "cleaning_operator" for e in p["extension_points"]))
        assert c.post(f"{API}/plugins/{dedup_plugin['id']}/enable",
                      json={"pid": pid, "enabled": True}).status_code == 200
        operators = c.get(f"{API}/projects/{pid}/cleaning-operators").json()["items"]
        plugin_op = next(op for op in operators if op["source"] == "plugin")
        plugin_pipeline = c.post(f"{API}/projects/{pid}/pipelines", json={
            "name": "插件算子链路", "nodes_json": [{"op": plugin_op["op"], "params": {"field": "text"}}]
        }).json()
        job = c.post(f"{API}/pipelines/{plugin_pipeline['id']}/run",
                     json={"source_version_id": v1["id"]}).json()
        assert wait_job(c, job["job_id"])["status"] == "succeeded"
        assert c.get(f"{API}/pipelines/{plugin_pipeline['id']}/runs").json()[0]["stats_json"]["output"] == 2

        # 11. 资源树 / 血缘 / 全局搜索 / 审计 / 日志
        tree = c.get(f"{API}/projects/{pid}/tree").json()
        assert tree["groups"] and any(g["items"] for g in tree["groups"])
        graph = c.get(f"{API}/projects/{pid}/lineage").json()
        assert graph["nodes"] and graph["edges"]
        assert c.get(f"{API}/projects/{pid}/search", params={"q": "实验"}).json()["items"]
        events = c.get(f"{API}/audit-events", params={"pid": pid, "size": 100}).json()
        assert events["total"] > 10
        actions = {e["action"] for e in events["items"]}
        assert "project.create" in actions and "plugin.enable" in actions
        logs = c.get(f"{API}/jobs/{run['job_id']}/logs").json()
        assert logs["lines"]

        # 12. 项目隔离：B 项目看不到 A 的数据集
        assert c.get(f"{API}/projects/{b['id']}/datasets").json()["total"] == 0
