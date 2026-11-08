"""Hardening for invited trial builds: CORS allowlist + terminal off by default."""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

TMP = pathlib.Path(tempfile.mkdtemp(prefix="aixian-security-"))
os.environ["AIXIAN_HOME"] = str(TMP / "home")
os.environ["AIXIAN_WEB_DIST"] = str(TMP / "no-dist")
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from aixian import config  # noqa: E402
from aixian.app import app  # noqa: E402

API = "/api/v1"


def test_cors_and_terminal_defaults():
    with TestClient(app) as c:
        # Unknown/foreign origins are not granted cross-origin access.
        foreign = c.options(f"{API}/health", headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        })
        assert "access-control-allow-origin" not in foreign.headers

        allowed = c.options(f"{API}/health", headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        })
        assert allowed.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"

        # Terminal is off unless explicitly enabled.
        project = c.post(f"{API}/projects", json={"name": "安全验证"}).json()
        denied = c.post(f"{API}/terminal/exec", json={"pid": project["id"], "command": "echo hi"})
        assert denied.status_code == 403 and denied.json()["code"] == "TERMINAL_DISABLED"

        config.save_settings({"enable_local_terminal": True})
        try:
            ok = c.post(f"{API}/terminal/exec", json={"pid": project["id"], "command": "echo aixian"})
            assert ok.status_code == 200 and "aixian" in ok.json()["output"]
        finally:
            config.save_settings({"enable_local_terminal": False})
