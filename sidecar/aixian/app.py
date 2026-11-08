"""FastAPI application: unified errors, CORS, WebSocket, API v1, static desktop shell."""
from __future__ import annotations

import asyncio
import traceback
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, config
from .database import init_registry, migrate_all_projects
from .errors import ApiError
from .events import hub
from .api import (
    agent, annotations, datasets, datasources, evaluation, finetune, identity,
    models, pipelines, projects, reports, schedules, scripts, system, themes, training,
)
from .services import scheduler

ROUTERS = (
    projects.router, datasources.router, datasets.router, pipelines.router,
    scripts.router, annotations.router, training.router, evaluation.router,
    reports.router, system.router, schedules.router, identity.router, themes.router,
    models.router, finetune.router, agent.router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.bootstrap()
    init_registry()
    migrate_all_projects()
    hub.bind_loop(asyncio.get_running_loop())
    scheduler.scheduler.start()
    try:
        yield
    finally:
        await scheduler.scheduler.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI Training Studio · 本地服务",
        description="AI 训练工作台 Sidecar API v0.1（项目级隔离 / 本地优先）",
        version=__version__,
        lifespan=lifespan,
    )
    # Only the app's own origins may call the local API. A wildcard here would
    # let any web page in the browser drive /terminal/exec and the other 110
    # endpoints on 127.0.0.1. Production (Sidecar-served SPA) is same-origin.
    local_origins = [
        "http://127.0.0.1:5173", "http://localhost:5173",  # Vite dev server
        f"http://127.0.0.1:{config.PORT}", f"http://localhost:{config.PORT}",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=local_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.body())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={
            "code": "VALIDATION_ERROR", "message": "请求参数校验失败",
            "detail": [{"loc": list(e.get("loc", [])), "msg": e.get("msg", "")} for e in exc.errors()],
        })

    @app.exception_handler(HTTPException)
    async def _http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={
            "code": "HTTP_ERROR", "message": str(exc.detail), "detail": None,
        })

    @app.exception_handler(Exception)
    async def _unexpected(_request: Request, exc: Exception) -> JSONResponse:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={
            "code": "INTERNAL_ERROR", "message": str(exc),
            "detail": traceback.format_exc(limit=6).splitlines()[-6:],
        })

    for router in ROUTERS:
        app.include_router(router, prefix=config.API_PREFIX)

    @app.websocket("/ws")
    async def websocket_events(ws: WebSocket) -> None:
        async def on_message(socket: WebSocket, raw: dict[str, Any]) -> None:
            if raw.get("type") == "ping":
                await socket.send_json({"type": "pong", "ts": raw.get("ts")})
            elif raw.get("type") == "subscribe":
                await socket.send_json({"type": "subscribed", "topics": raw.get("topics", [])})
            elif raw.get("type") == "history":
                await socket.send_json({"type": "history", "events": list(hub.recent)})

        await hub.handle_client(ws, on_message)

    @app.get("/api/v1/version", tags=["meta"])
    def version() -> dict[str, Any]:
        return {"version": __version__, "sdk_version": "0.1", "api": "v1"}

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    dist = config.WEB_DIST
    if not dist.exists():
        return
    app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="assets") if (dist / "assets").exists() else None

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = (dist / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(str(candidate))
        index = dist / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse({"code": "NO_FRONTEND", "message": "前端构建产物不存在，请先执行 npm run build", "detail": None}, 404)


app = create_app()
