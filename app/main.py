"""FastAPI 应用组装：DB 初始化 → 配置覆盖注册 → hooks → 队列 → 路由 → 静态托管。"""
from __future__ import annotations

from pathlib import Path
from contextlib import asynccontextmanager
import uuid
import hashlib
import hmac
import time
import ipaddress
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import APP_FULL_NAME, APP_VERSION
from .api import articles, drafts, materials, ops
from .core import config
from .core.config import RUNTIME_ROOT, data_dir
from .pipeline import hooks, queue
from .storage import dao, db

WEB_DIST = RUNTIME_ROOT / "web" / "dist"


def create_app(start_worker: bool = True, llm=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        app.state.runtime = None
        try:
            app.state.runtime = queue.start(llm) if start_worker else None
            if not start_worker:
                db.init_db()
                config.set_db_overlay(dao.db_settings)
            # 外部项目文件夹导入：启动时全量扫一次 + 后台定时扫描（V1.14）
            from .services import imports as import_svc
            import_svc.start_watcher()
            hooks.register_hooks()
            from . import logging_setup
            logging_setup.configure()
            from .context import AppContext
            from .core import events
            import copy
            app.state.context = AppContext(data_dir(), copy.deepcopy(config.all_settings()),
                                            dao, events.bus, app.state.runtime)
            app.state.ready = True
            yield
        finally:
            app.state.ready = False
            if app.state.runtime is not None:
                queue.stop()
            from .services.http import close_clients
            close_clients()

    app = FastAPI(title=APP_FULL_NAME, version=APP_VERSION, lifespan=lifespan)
    app.state.ready = False
    app.state.worker_enabled = start_worker

    from .services.draft_service import VersionConflict
    @app.exception_handler(VersionConflict)
    async def version_conflict(request: Request, exc: VersionConflict):
        return JSONResponse({"detail": str(exc), "code": "version_conflict"}, status_code=409)

    @app.exception_handler(ValueError)
    async def invalid_input(request: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    # 本地工具默认可跨域（开发期 Vite 端口不同）
    app.add_middleware(CORSMiddleware, allow_origins=[origin.strip() for origin in os.environ.get("WENSHU_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip() != "*"], allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"], allow_credentials=True)

    @app.middleware("http")
    async def token_guard(request: Request, call_next):
        from .core.execution import context
        request_id = uuid.uuid4().hex
        ctx = context.set({"request_id": request_id})
        token = config.get_env("APP_ACCESS_TOKEN")
        path = request.url.path
        protected = path.startswith(("/api/", "/files/")) or path in ("/docs", "/redoc", "/openapi.json")
        bearer = request.headers.get("Authorization", "").removeprefix("Bearer ")
        cookie = request.cookies.get("wenshu_session", "")
        authenticated = False
        if token:
            authenticated = bool(bearer and hmac.compare_digest(bearer, token))
            if not authenticated and "." in cookie:
                expires, signature = cookie.split(".", 1)
                expected = hmac.new(token.encode(), expires.encode(), hashlib.sha256).hexdigest()
                authenticated = expires.isdigit() and int(expires) > time.time() and hmac.compare_digest(signature, expected)
        try:
            if protected and path != "/api/health" and request.method != "OPTIONS":
                if token and not authenticated:
                    return JSONResponse({"detail": "未授权"}, status_code=401)
                if not token:
                    host = request.client.host if request.client else ""
                    try:
                        local = ipaddress.ip_address(host).is_loopback
                    except ValueError:
                        local = host == "testclient"
                    if not local:
                        return JSONResponse({"detail": "远程访问必须配置 APP_ACCESS_TOKEN"}, status_code=403)
            result = await call_next(request)
            result.headers["X-Request-ID"] = request_id
            current_token = config.get_env("APP_ACCESS_TOKEN")
            # An authorized reload may rotate the token: re-sign this session
            # without returning the new secret to JavaScript.
            if current_token and ((bearer and authenticated) or
                    (path == "/api/settings/reload-env" and result.status_code == 200)):
                expires = str(int(time.time()) + 8 * 3600)
                signature = hmac.new(current_token.encode(), expires.encode(), hashlib.sha256).hexdigest()
                result.set_cookie("wenshu_session", expires + "." + signature, httponly=True,
                                  secure=request.url.scheme == "https", samesite="strict", max_age=8 * 3600)
            elif not current_token and path == "/api/settings/reload-env" and result.status_code == 200:
                result.delete_cookie("wenshu_session")
            return result
        finally:
            context.reset(ctx)

    @app.get("/api/session")
    def session():
        return {"ok": True}

    app.include_router(articles.router)
    app.include_router(articles.jobs_router)
    app.include_router(drafts.router)
    app.include_router(materials.router)
    app.include_router(ops.router)

    # 素材与导出文件（图片预览 / 下载）
    @app.get("/files/{relative:path}", include_in_schema=False)
    def file(relative: str):
        from .services.file_access import recorded_file, response
        return response(recorded_file(relative))

    # SPA 静态托管 + 前端路由回退
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if WEB_DIST.exists():
            target = (WEB_DIST / full_path).resolve()
            if not target.is_relative_to(WEB_DIST.resolve()):
                return JSONResponse({"detail": "文件不存在"}, status_code=404)
            if full_path and target.exists() and target.is_file():
                return FileResponse(target)
            return FileResponse(WEB_DIST / "index.html")
        return JSONResponse({"name": APP_FULL_NAME,
                             "hint": "前端未构建：cd web && npm install && npm run build",
                             "api": "/docs"})

    return app


app = create_app()
