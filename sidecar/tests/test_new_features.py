"""End-to-end tests for model adapters, generated A/B, cron, RBAC and themes."""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("AIXIAN_HOME", str(pathlib.Path(tempfile.mkdtemp(prefix="aixian-new-"))))

from fastapi.testclient import TestClient  # noqa: E402

from aixian.app import app  # noqa: E402
from aixian.services import scheduler as scheduler_service  # noqa: E402

API = "/api/v1"


class MockModel(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        prompt = str(body.get("prompt", ""))
        if self.path == "/judge":
            answer = "0.8"
        else:
            answer = "答1" if "问1" in prompt else "答2" if "问2" in prompt else "不知道"
        payload = json.dumps({"output": answer}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def wait_job(client: TestClient, job_id: str, timeout: float = 25.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"{API}/jobs/{job_id}").json()
        if data.get("status") in ("succeeded", "failed", "cancelled"):
            return data
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} 超时")


def test_new_features():
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockModel)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        with TestClient(app) as c:
            project = c.post(f"{API}/projects", json={"name": "新功能验证"}).json()
            pid = project["id"]

            # ---------- 1. Themes ----------
            themes = c.get(f"{API}/themes").json()
            assert len(themes["presets"]) >= 5 and themes["active_id"] == "dark"
            assert "synKeyword" in themes["token_keys"]
            applied = c.put(f"{API}/themes/tokens", json={"tokens": {"accent": "#ff0000"}}).json()
            assert applied["tokens"]["accent"] == "#ff0000"
            saved = c.post(f"{API}/themes", json={
                "name": "我的主题", "tokens": {"accent": "#00ff00", "bg": "#101010"}}).json()
            assert saved["id"].startswith("custom-") and saved["tokens"]["bg"] == "#101010"
            assert c.get(f"{API}/themes").json()["active_id"] == saved["id"]
            exported = c.get(f"{API}/themes/{saved['id']}/export").json()
            assert exported["format"] == "aixian-theme/1"
            imported = c.post(f"{API}/themes/import", json={"theme": exported}).json()
            assert imported["name"] == "我的主题"
            assert c.put(f"{API}/themes/active", json={"id": "dark", "tokens": {}}).status_code == 200
            assert c.delete(f"{API}/themes/{saved['id']}").status_code == 200
            assert c.delete(f"{API}/themes/{imported['id']}").status_code == 200
            assert c.post(f"{API}/themes", json={"name": "坏主题", "tokens": {"accent": "not-a-color"}}).status_code == 422

            # ---------- 2. Model adapters catalog + real HTTP inference ----------
            catalog = c.get(f"{API}/projects/{pid}/model-adapters").json()
            kinds = {item["type"] for item in catalog["items"]}
            assert {"openai", "vllm", "http", "transformers", "subprocess", "plugin"} <= kinds
            assert "llm_judge" in catalog["scorers"]
            probe = c.post(f"{API}/projects/{pid}/model-adapters/test",
                           json={"prompt": "问1", "model_ref_json": {"type": "echo"}}).json()
            assert probe["output"] == "问1"

            suite = c.post(f"{API}/projects/{pid}/eval-suites", json={
                "name": "真实推理套件", "type": "accuracy",
                "cases_json": [
                    {"id": "c1", "input": "问1", "expected": "答1", "category": "general"},
                    {"id": "c2", "input": "问2", "expected": "答2", "category": "general"},
                ]}).json()
            job = c.post(f"{API}/eval-suites/{suite['id']}/runs", json={
                "model_ref_json": {"type": "http", "url": base_url,
                                   "payload_template": '{"prompt": "{prompt}"}',
                                   "field": "output", "concurrency": 2},
                "scorer_json": {"type": "exact_match"},
            }).json()
            assert wait_job(c, job["job_id"])["status"] == "succeeded"
            eval_run = c.get(f"{API}/eval-runs/{job['eval_run_id']}").json()
            assert eval_run["metrics_json"]["accuracy"] == 1.0
            assert eval_run["metrics_json"]["model_ref_type"] == "http"
            assert [r["output"] for r in eval_run["results_json"]] == ["答1", "答2"]

            # real LLM-as-judge (judge endpoint returns 0.8)
            judged = c.post(f"{API}/eval-suites/{suite['id']}/runs", json={
                "model_ref_json": {"type": "http", "url": base_url, "field": "output"},
                "scorer_json": {"type": "llm_judge", "threshold": 0.7,
                                "judge_model_ref": {"type": "http", "url": base_url + "/judge",
                                                    "field": "output"}},
            }).json()
            assert wait_job(c, judged["job_id"])["status"] == "succeeded"
            judged_run = c.get(f"{API}/eval-runs/{judged['eval_run_id']}").json()
            assert judged_run["metrics_json"]["accuracy"] == 0.8
            assert all(r["score"]["passed"] for r in judged_run["results_json"])

            # invalid adapter is rejected before submitting a Job
            assert c.post(f"{API}/eval-suites/{suite['id']}/runs", json={
                "model_ref_json": {"type": "does-not-exist"}}).status_code == 422

            # plugin-provided model adapter (high-risk permission needs confirmation)
            c.post(f"{API}/plugins/scan?pid={pid}")
            plugins = c.get(f"{API}/plugins", params={"pid": pid}).json()["items"]
            echo_id = "com.aixian.echo-adapter"
            assert echo_id in {p["id"] for p in plugins}
            assert c.post(f"{API}/plugins/{echo_id}/enable",
                          json={"pid": pid, "enabled": True}).status_code == 428
            assert c.post(f"{API}/plugins/{echo_id}/enable",
                          json={"pid": pid, "enabled": True, "confirm": True}).status_code == 200
            plugin_probe = c.post(f"{API}/projects/{pid}/model-adapters/test", json={
                "prompt": "你好",
                "model_ref_json": {"type": "plugin", "plugin_id": echo_id,
                                   "config": {"rules": {"你好": "你好呀"}, "prefix": "[规则] "}},
            }).json()
            assert plugin_probe["output"] == "[规则] 你好呀"

            # ---------- 3. Generated A/B ----------
            ab = c.post(f"{API}/projects/{pid}/ab-tests", json={
                "name": "自动生成 A/B", "generate": True,
                "model_a_ref": {"type": "static", "outputs": {"p1": "答1", "p2": "答1"}},
                "model_b_ref": {"type": "static", "outputs": {"p1": "错", "p2": "错"}},
                "scorer_json": {"type": "exact_match"},
                "prompt_set_json": [
                    {"id": "p1", "input": "问1", "expected": "答1"},
                    {"id": "p2", "input": "问2", "expected": "答1"},
                ]}).json()
            assert ab["generated"] is True and ab["job_id"]
            assert wait_job(c, ab["job_id"])["status"] == "succeeded"
            ab_detail = c.get(f"{API}/ab-tests/{ab['ab_test_id']}").json()
            assert ab_detail["result_json"]["wins_a"] == 2
            assert ab_detail["model_a"]["type"] == "static"
            assert ab_detail["prompt_set_json"][0]["output_a"] == "答1"
            assert ab_detail["report_id"]
            # legacy pre-recorded mode still works
            legacy = c.post(f"{API}/projects/{pid}/ab-tests", json={
                "name": "离线 A/B", "model_a_ref": "model-v1", "model_b_ref": "baseline",
                "prompt_set_json": [{"id": "p1", "score_a": 1, "score_b": 0, "winner": "a"}]}).json()
            assert legacy["result_json"]["total"] == 1

            # ---------- 4. Cron schedules ----------
            assert scheduler_service.matches("*/5 * * * *", datetime(2026, 11, 7, 10, 15))
            assert not scheduler_service.matches("*/5 * * * *", datetime(2026, 11, 7, 10, 16))
            assert scheduler_service.next_after("0 3 * * *", datetime(2026, 11, 7, 10, 0)).hour == 3
            types = c.get(f"{API}/projects/{pid}/schedule-types").json()["items"]
            assert {"script.run", "pipeline.run", "eval.run", "command"} == {t["type"] for t in types}
            scheduled = c.post(f"{API}/projects/{pid}/schedules", json={
                "name": "每 5 分钟问候", "type": "command", "cron_expr": "*/5 * * * *",
                "payload_json": {"command": "echo scheduled"}}).json()
            assert scheduled["next_run_at"] and scheduled["enabled"] == 1
            manual = c.post(f"{API}/schedules/{scheduled['id']}/run-now").json()
            assert wait_job(c, manual["job_id"])["status"] == "succeeded"
            assert c.patch(f"{API}/schedules/{scheduled['id']}",
                           json={"enabled": False}).json()["next_run_at"] is None
            assert c.post(f"{API}/projects/{pid}/schedules", json={
                "name": "坏 cron", "type": "command", "cron_expr": "bogus",
                "payload_json": {"command": "echo x"}}).status_code == 422

            # ---------- 5. Users / roles / sharing ----------
            assert c.get(f"{API}/roles").status_code == 200
            me = c.get(f"{API}/me").json()
            assert me["user"]["username"] == "local"
            alice = c.post(f"{API}/users", json={
                "username": "alice", "display_name": "标注员 Alice", "global_role": "viewer"}).json()
            c.post(f"{API}/projects/{pid}/members", json={
                "user_id": alice["id"], "role": "annotator"})
            members = c.get(f"{API}/projects/{pid}/members").json()["items"]
            assert members and members[0]["username"] == "alice"
            try:
                c.post(f"{API}/me", json={"user_id": alice["id"]})
                denied = c.post(f"{API}/projects/{pid}/datasets", json={"name": "不该成功"})
                assert denied.status_code == 403 and denied.json()["code"] == "FORBIDDEN"
                # read-only endpoints remain available to restricted roles
                assert c.get(f"{API}/projects/{pid}/datasets").status_code == 200
            finally:
                local_id = next(u["id"] for u in c.get(f"{API}/users").json()["items"]
                                if u["username"] == "local")
                c.post(f"{API}/me", json={"user_id": local_id})
            assert c.post(f"{API}/projects/{pid}/datasets", json={"name": "恢复后可写"}).status_code == 200
            assert c.delete(f"{API}/projects/{pid}/members/{alice['id']}").status_code == 200
            audit = c.get(f"{API}/audit-events", params={"pid": pid, "size": 100}).json()["items"]
            assert any(e["action"] == "member.upsert" for e in audit)
    finally:
        server.shutdown()
        server.server_close()


def test_legacy_column_migration():
    """Existing project DBs must gain columns added to ABTest by this iteration."""
    import sqlite3

    from sqlalchemy import create_engine, inspect, text

    from aixian.database import _add_missing_columns

    path = pathlib.Path(tempfile.mkdtemp(prefix="aixian-migrate-")) / "meta.db"
    connection = sqlite3.connect(path)
    connection.execute("""CREATE TABLE ab_tests (
        id VARCHAR(32) PRIMARY KEY, project_id VARCHAR(32), name VARCHAR(200),
        model_a_ref TEXT, model_b_ref TEXT, prompt_set_json JSON, result_json JSON,
        report_id VARCHAR(32), status VARCHAR(32),
        created_at DATETIME, updated_at DATETIME)""")
    connection.commit()
    connection.close()
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    added = _add_missing_columns(engine)
    columns = {c["name"] for c in inspect(engine).get_columns("ab_tests")}
    assert {"scorer_json", "job_id", "generated"} <= columns
    assert added >= 3
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO ab_tests (id, name, project_id, status) "
                          "VALUES ('legacy', '旧记录', 'p', 'completed')"))
        row = conn.execute(text("SELECT scorer_json, generated FROM ab_tests WHERE id='legacy'")).one()
        assert row[1] == 0
    engine.dispose()
