"""素材库路由：列表 / 上传 / 网址摄取 / inbox 扫描 / 删除。"""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..core import events
from ..storage import dao, db, library
from ..services.crawl import registry as crawl_registry
from ..services.crawl.base import CrawlError
from ..services.media import download as media_download

router = APIRouter(prefix="/api", tags=["materials"])


class AddUrl(BaseModel):
    url: str
    ref_type: str | None = None    # reference | foundational


def _with_abs(m: dict) -> dict:
    p = library.material_abs_path(m.get("path"))
    m["url"] = f"/files/library/{m['path']}" if m.get("path") else None
    m["exists"] = bool(p and p.exists()) if m.get("path") else None
    return m


@router.get("/articles/{aid}/materials")
def article_materials(aid: str, scope: str = "article", kind: str | None = None) -> dict:
    if scope not in ("article", "common"):
        raise HTTPException(400, "scope 为 article 或 common")
    article_id = aid if scope == "article" else None
    mats = dao.list_materials(scope=scope, article_id=article_id, kind=kind)
    return {"materials": [_with_abs(m) for m in mats]}


@router.get("/materials/common")
def common_materials(kind: str | None = None) -> dict:
    return {"materials": [_with_abs(m) for m in dao.list_materials(scope="common", kind=kind)]}


@router.post("/articles/{aid}/materials/upload")
async def upload_article_material(aid: str, file: UploadFile = File(...)) -> dict:
    if not dao.get_article(aid):
        raise HTTPException(404, "文章不存在")
    data = await file.read()
    mid, created = library.ingest_bytes(data, file.filename or "upload.bin",
                                        "article", aid, note="GUI 上传")
    events.bus.publish(events.MATERIAL_INGESTED, aid, material_id=mid)
    return {"material_id": mid, "created": created}


@router.post("/materials/upload")
async def upload_common_material(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    mid, created = library.ingest_bytes(data, file.filename or "upload.bin",
                                        "common", note="GUI 上传(公共库)")
    events.bus.publish(events.MATERIAL_INGESTED, None, material_id=mid)
    return {"material_id": mid, "created": created}


@router.post("/articles/{aid}/materials/url")
def add_url_material(aid: str, body: AddUrl) -> dict:
    if not dao.get_article(aid):
        raise HTTPException(404, "文章不存在")
    try:
        raw = crawl_registry.fetch(body.url)
    except CrawlError as e:
        raise HTTPException(502, f"抓取失败: {e}")
    mid = library.ingest_text(raw.markdown, title=raw.title or body.url, scope="article",
                              article_id=aid, source_url=body.url,
                              ref_type=body.ref_type or "reference",
                              meta={"site": raw.site, "published_at": raw.published_at})
    media_download.fetch_images(raw.images[:5], scope="article", article_id=aid,
                                source_material_id=mid, page_url=body.url)
    events.bus.publish(events.MATERIAL_INGESTED, aid, material_id=mid)
    return {"material_id": mid, "title": raw.title}


@router.post("/articles/{aid}/materials/scan-inbox")
def scan_article_inbox(aid: str) -> dict:
    return {"ingested": library.scan_inbox(aid)}


@router.post("/materials/scan-inbox")
def scan_common_inbox() -> dict:
    return {"ingested": library.scan_inbox(None)}


@router.delete("/materials/{mid}")
def delete_material(mid: str) -> dict:
    m = dao.get_material(mid)
    if not m:
        raise HTTPException(404, "素材不存在")
    p = library.material_abs_path(m.get("path"))
    db.execute("DELETE FROM materials WHERE id=?", (mid,))
    db.execute("DELETE FROM material_texts WHERE material_id=?", (mid,))
    db.execute("DELETE FROM embeddings WHERE material_id=?", (mid,))
    if p and p.exists():
        try:
            p.unlink()
        except OSError:
            pass
    return {"ok": True}
