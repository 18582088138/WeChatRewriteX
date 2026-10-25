"""素材库路由：列表 / 上传 / 网址摄取 / inbox 扫描 / 删除。"""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..core import events
from ..core.ids import new_id as new_id_fn
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
    m["url"] = f"/files/{m['path']}" if m.get("path") else None
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


@router.get("/materials/{mid}/file")
def material_file(mid: str) -> FileResponse:
    """按素材 id 直接取文件（编辑器图片块用）。"""
    m = dao.get_material(mid)
    if not m:
        raise HTTPException(404, "素材不存在")
    p = library.material_abs_path(m.get("path"))
    if not p or not p.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(p)


@router.get("/materials/{mid}/text")
def material_text(mid: str) -> dict:
    return {"material_id": mid, "content": dao.get_material_text(mid)}


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
    from ..services import ingest as ingest_svc
    try:
        r = ingest_svc.ingest_url(aid, body.url, body.ref_type)
    except CrawlError as e:
        raise HTTPException(502, f"抓取失败: {e}")
    events.bus.publish(events.MATERIAL_INGESTED, aid, material_id=r["material_id"])
    return r


class BatchUrl(BaseModel):
    urls: list[str]
    ref_type: str | None = None


class CopyToArticle(BaseModel):
    article_id: str


class PatchMaterial(BaseModel):
    title: str | None = None
    note: str | None = None


@router.post("/articles/{aid}/materials/batch-url")
def batch_url_material(aid: str, body: BatchUrl) -> dict:
    """批量链接批量抓取：入队 ingest 任务，逐链接记录成败。"""
    if not dao.get_article(aid):
        raise HTTPException(404, "文章不存在")
    urls = [u.strip() for u in body.urls if u.strip().startswith("http")]
    if not urls:
        raise HTTPException(400, "没有有效链接")
    from ..pipeline import queue
    job_id = queue.enqueue("ingest", aid, {"urls": urls, "ref_type": body.ref_type})
    return {"job_id": job_id, "count": len(urls)}


@router.post("/materials/{mid}/recrawl")
def recrawl_material(mid: str) -> dict:
    """单链接独立重抓：更新正文标题并补充媒体。"""
    from ..services import ingest as ingest_svc
    try:
        r = ingest_svc.recrawl(mid)
    except CrawlError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"重抓失败: {e}")
    events.bus.publish(events.MATERIAL_INGESTED, None, material_id=mid)
    return r


@router.post("/materials/{mid}/copy-to-article")
def copy_to_article(mid: str, body: CopyToArticle) -> dict:
    """公共库素材拖拽复制到本文素材库（同文件，新行；不重复占盘）。"""
    m = dao.get_material(mid)
    if not m:
        raise HTTPException(404, "素材不存在")
    if not dao.get_article(body.article_id):
        raise HTTPException(404, "文章不存在")
    if m["scope"] == "article" and m.get("article_id") == body.article_id:
        return {"material_id": mid, "copied": False, "reason": "已在本文素材库"}
    new_id = new_id_fn("material")
    db.execute(
        """INSERT INTO materials
        (id,scope,article_id,kind,path,sha256,phash,source_url,source_material_id,
         watermark,width,height,duration,ref_type,fetch_status,note,title,meta_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (new_id, "article", body.article_id, m["kind"], m.get("path"), m.get("sha256"),
         m.get("phash"), m.get("source_url"), m.get("source_material_id"), m.get("watermark"),
         m.get("width"), m.get("height"), m.get("duration"), m.get("ref_type"),
         m.get("fetch_status"), (m.get("note") or "") + "（复制自公共库）", m.get("title"),
         m.get("meta_json") or "{}"),
    )
    if m["kind"] == "text":
        db.execute("INSERT OR REPLACE INTO material_texts(material_id,content) VALUES(?,?)",
                   (new_id, dao.get_material_text(mid)))
    events.bus.publish(events.MATERIAL_INGESTED, body.article_id, material_id=new_id)
    return {"material_id": new_id, "copied": True}


@router.post("/materials/{mid}/copy-to-common")
def copy_to_common(mid: str) -> dict:
    """本文素材库反向复制到公共素材库（sha256 校验，公共库已有同文件则跳过）。"""
    m = dao.get_material(mid)
    if not m:
        raise HTTPException(404, "素材不存在")
    if m["scope"] == "common":
        return {"material_id": mid, "copied": False, "reason": "已在公共素材库"}
    if m.get("sha256"):
        dup = dao.find_material_by_sha(m["sha256"])
        if dup and dup["scope"] == "common":
            return {"material_id": dup["id"], "copied": False, "reason": "公共库已存在同文件，已跳过"}
    new_id = new_id_fn("material")
    db.execute(
        """INSERT INTO materials
        (id,scope,article_id,kind,path,sha256,phash,source_url,source_material_id,
         watermark,width,height,duration,ref_type,fetch_status,note,title,meta_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (new_id, "common", None, m["kind"], m.get("path"), m.get("sha256"),
         m.get("phash"), m.get("source_url"), m.get("source_material_id"), m.get("watermark"),
         m.get("width"), m.get("height"), m.get("duration"), m.get("ref_type"),
         m.get("fetch_status"), (m.get("note") or "") + "（复制自项目素材）", m.get("title"),
         m.get("meta_json") or "{}"),
    )
    if m["kind"] == "text":
        db.execute("INSERT OR REPLACE INTO material_texts(material_id,content) VALUES(?,?)",
                   (new_id, dao.get_material_text(mid)))
    events.bus.publish(events.MATERIAL_INGESTED, None, material_id=new_id)
    return {"material_id": new_id, "copied": True}


@router.patch("/materials/{mid}")
def patch_material(mid: str, body: PatchMaterial) -> dict:
    """改素材标题/备注。"""
    m = dao.get_material(mid)
    if not m:
        raise HTTPException(404, "素材不存在")
    if body.title is not None:
        db.execute("UPDATE materials SET title=? WHERE id=?", (body.title.strip(), mid))
    if body.note is not None:
        db.execute("UPDATE materials SET note=? WHERE id=?", (body.note, mid))
    return {"ok": True}


@router.post("/materials/{mid}/reveal")
def reveal_material(mid: str) -> dict:
    """在系统文件管理器中打开素材所在文件夹；路径失效时给出友好提示（反馈 3.5）。"""
    m = dao.get_material(mid)
    if not m:
        raise HTTPException(404, "素材不存在")
    p = library.material_abs_path(m.get("path"))
    if (not p or not p.exists()) and m.get("source_url"):
        # 无本地文件的链接型素材：改为浏览器打开来源
        return {"ok": True, "external": m["source_url"]}
    if not p or not p.exists():
        raise HTTPException(404, f"本地文件不存在或已被移动：{m.get('path') or '（无文件记录）'}。"
                                 f"可在项目文件夹内检查，或重新抓取该素材")
    import subprocess
    import sys as _sys
    try:
        if _sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(p)])
        elif _sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p.parent)])
    except OSError as e:
        raise HTTPException(500, f"打开文件夹失败: {e}")
    return {"ok": True, "folder": str(p.parent)}


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
