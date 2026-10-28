"""FastAPI 应用组装：DB 初始化 → 配置覆盖注册 → hooks → 队列 → 路由 → 静态托管。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import APP_FULL_NAME, APP_VERSION
from .api import articles, drafts, materials, ops
from .core import config
from .core.config import RUNTIME_ROOT, data_dir
from .pipeline import hooks, queue
from .storage import dao, db

WEB_DIST = RUNTIME_ROOT / "web" / "dist"


def create_app(start_worker: bool = True, llm=None) -> FastAPI:
    db.init_db()
    data_dir().mkdir(parents=True, exist_ok=True)
    config.set_db_overlay(dao.db_settings)
    hooks.register_hooks()
    from . import logging_setup
    logging_setup.configure()       # 常驻持久化：级别/路径走 log.* 配置

    app = FastAPI(title=APP_FULL_NAME, version=APP_VERSION)

    from .services.draft_service import VersionConflict
    @app.exception_handler(VersionConflict)
    async def version_conflict(request: Request, exc: VersionConflict):
        return JSONResponse({"detail": str(exc), "code": "version_conflict"}, status_code=409)

    # 本地工具默认可跨域（开发期 Vite 端口不同）
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])

    @app.middleware("http")
    async def token_guard(request: Request, call_next):
        token = config.get_env("APP_ACCESS_TOKEN")
        if token and not request.url.path.startswith("/api/health"):
            given = request.query_params.get("token") or \
                request.headers.get("Authorization", "").removeprefix("Bearer ")
            if given != token:
                return JSONResponse({"detail": "未授权"}, status_code=401)
        return await call_next(request)

    app.include_router(articles.router)
    app.include_router(articles.jobs_router)
    app.include_router(drafts.router)
    app.include_router(materials.router)
    app.include_router(ops.router)

    # 素材与导出文件（图片预览 / 下载）
    (data_dir() / "library").mkdir(parents=True, exist_ok=True)
    app.mount("/files", StaticFiles(directory=data_dir()), name="files")

    # SPA 静态托管 + 前端路由回退
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if WEB_DIST.exists():
            target = WEB_DIST / full_path
            if full_path and target.exists() and target.is_file():
                return FileResponse(target)
            return FileResponse(WEB_DIST / "index.html")
        return JSONResponse({"name": APP_FULL_NAME,
                             "hint": "前端未构建：cd web && npm install && npm run build",
                             "api": "/docs"})

    if start_worker:
        queue.start(llm)
    return app


app = create_app()
