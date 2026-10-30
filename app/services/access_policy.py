"""Fail-closed authorization of the existing API surface and file routes."""
import re
from fastapi import HTTPException
from . import team
from ..storage import db, dao, library

PUBLIC = {"/api/health", "/api/auth/status", "/api/auth/login", "/api/auth/bootstrap"}
ADMIN = {"/api/settings", "/api/settings/reload-env", "/api/logs/tail", "/docs", "/redoc", "/openapi.json",
         "/api/articles/imports/scan", "/api/materials/upload", "/api/materials/scan-inbox"}


def file_authorized(member, target):
    normalized = target.relative_to(library.library_root().resolve()).as_posix()
    for material in db.query("SELECT * FROM materials WHERE REPLACE(path,char(92),'/')=?", (normalized,)):
        if team.material_allowed(member, material):
            return True
    from .file_access import export_directories, package_files
    for article in db.query("SELECT id,lib_dir FROM articles WHERE lib_dir IS NOT NULL"):
        if team.allowed(member, article["id"]):
            if any(target in package_files(p) for p in export_directories(article["id"])):
                return True
            if target.name.startswith("page-") and target.suffix == ".png" and target.parent.name == "xhs_cards" and target.is_relative_to(library.article_dir(article["id"]).resolve()):
                return True
    return False


async def authorize(request, member):
    path, method = request.url.path, request.method
    if method == "OPTIONS":
        return None
    protected = path.startswith(("/api/", "/files/")) or path in ADMIN
    if not protected:
        return None
    if method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        from ..core import config
        origins = {str(request.base_url).rstrip("/")}
        origins.update((config.get_env("WENSHU_CORS_ORIGINS") or "http://localhost:5173,http://127.0.0.1:5173").split(","))
        if origin and origin not in origins:
            raise HTTPException(403, "请求来源无效")
    if path in PUBLIC:
        return None
    if not member:
        raise HTTPException(401, "请登录成员账号")
    if method not in ("GET", "HEAD", "OPTIONS"):
        import hmac
        if not hmac.compare_digest(request.headers.get("X-Wenshu-CSRF", ""), member["csrf"]):
            raise HTTPException(403, "会话校验失败，请重新登录")
    if member["must_change"] and path not in ("/api/auth/me", "/api/auth/password", "/api/auth/logout"):
        raise HTTPException(403, "请先更改初始或重置密码")
    if path in ADMIN or path.startswith("/api/auth/members"):
        team.admin()
        return ("admin", "manage")
    if path.startswith("/api/auth/") or path in ("/api/session", "/api/sse", "/api/capabilities", "/api/team/work", "/api/team/settings"):
        return None
    if path == "/api/ready":
        if member["role"] == "member":
            raise HTTPException(403, "仅维护人员可查看服务状态")
        return None
    if path == "/api/articles" or path == "/api/jobs":
        aid = request.query_params.get("article_id") if path == "/api/jobs" else None
        if aid:
            team.require(aid)
        return (aid, "read")
    if path == "/api/materials/common":
        return None
    if path.startswith("/files/"):
        from .file_access import recorded_file
        target = recorded_file(path[len("/files/"):])
        if not file_authorized(member, target):
            raise HTTPException(404, "文件不存在或无访问权限")
        return None
    if path.endswith("/reveal"):
        raise HTTPException(403, "团队服务不操作服务器桌面")
    match = re.fullmatch(r"/api/articles/([^/]+)(?:/(.*))?", path)
    aid, suffix = None, ""
    if match:
        aid, suffix = match.group(1), match.group(2) or ""
    else:
        match = re.fullmatch(r"/api/drafts/([^/]+)/(.*)", path)
        if match:
            row = dao.get_draft_by_id(match.group(1))
            if not row:
                # Workspace IDs have a stable article-vN spelling.
                aid = match.group(1).rsplit("-v", 1)[0]
                row = dao.latest_draft(aid)
            aid, suffix = row["article_id"] if row else None, match.group(2)
        else:
            match = re.fullmatch(r"/api/(materials|review-items)/([^/]+)(?:/(.*))?", path)
            if match:
                kind, oid, suffix = match.group(1), match.group(2), match.group(3) or ""
                if kind == "materials":
                    material = dao.get_material(oid)
                    if not team.material_allowed(member, material):
                        raise HTTPException(404, "素材不存在或无访问权限")
                    if suffix == "copy-to-article":
                        body = await request.json()
                        aid = body.get("article_id")
                    elif material["scope"] == "common":
                        if method not in ("GET", "HEAD"):
                            team.admin()
                        return ("admin", "manage") if method not in ("GET", "HEAD") else None
                    else:
                        aid = material["article_id"]
                    if suffix == "copy-to-common":
                        team.admin()
                        return ("admin", "manage")
                else:
                    row = db.query_one("SELECT r.article_id FROM reviews r JOIN review_items i ON i.review_id=r.id WHERE i.id=?", (oid,))
                    aid = row["article_id"] if row else None
    if not aid:
        raise HTTPException(404, "未知或无权访问的接口")
    capability = "read" if method in ("GET", "HEAD") else "write"
    if method not in ("GET", "HEAD") and suffix in ("finalize", "publish", "publish/retry", "cards"):
        capability = "release"
    if suffix.startswith("access"):
        capability = "read" if method in ("GET", "HEAD") else "manage"
    team.require(aid, capability)
    if not dao.get_article(aid):
        raise HTTPException(404, "项目不存在")
    if method not in ("GET", "HEAD") and "application/json" in request.headers.get("content-type", ""):
        body = await request.json()
        def references(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in ("asset_id", "material_id") and isinstance(child, str):
                        yield child
                    elif key in ("citations", "material_ids", "selected_material_ids") and isinstance(child, list):
                        yield from child
                    else:
                        yield from references(child)
            elif isinstance(value, list):
                for child in value:
                    yield from references(child)
        for mid in references(body):
            material = dao.get_material(mid) if isinstance(mid, str) else None
            if not material or not team.material_allowed(member, material) or (material["scope"] == "article" and material["article_id"] != aid):
                raise HTTPException(404, "素材不属于当前项目或获准公共范围")
    return (aid, capability)
