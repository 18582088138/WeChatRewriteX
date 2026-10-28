"""素材库路由：列表 / 上传 / 网址摄取 / inbox 扫描 / 删除。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..core import events, config
from starlette.concurrency import run_in_threadpool
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
    from ..services.file_access import response
    return response(p)


def _extract_first_frame(src, out) -> None:
    """ffmpeg 抽视频首帧（0.5s 优先避开黑场，失败退回 0s）。"""
    import subprocess
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        exe = get_ffmpeg_exe()
    except Exception:
        import shutil as _sh
        exe = _sh.which("ffmpeg")
    if not exe:
        raise HTTPException(503, "未找到 ffmpeg，无法抽取视频首帧")
    for ss in ("0.5", "0"):
        args = [exe, "-y"] + (["-ss", ss] if ss != "0" else []) +                ["-i", str(src), "-frames:v", "1", "-q:v", "3", str(out)]
        r = subprocess.run(args, capture_output=True, timeout=60)
        if r.returncode == 0 and out.exists():
            return
    raise HTTPException(502, f"视频首帧抽取失败: {src.name}")


@router.get("/materials/{mid}/thumb")
def material_thumb(mid: str):
    """缩略图：图片返回自身；视频先取海报子图，否则抽首帧并缓存。"""
    m = dao.get_material(mid)
    if not m:
        raise HTTPException(404, "素材不存在")
    if m["kind"] == "image":
        p = library.material_abs_path(m.get("path"))
        if p and p.exists():
            return FileResponse(p)
        raise HTTPException(404, "图片文件不存在")
    if m["kind"] != "video":
        raise HTTPException(400, "仅图片/视频素材有缩略图")
    for x in dao.list_materials(scope="article", article_id=m.get("article_id"), kind="image"):
        if x.get("source_material_id") == mid and x.get("path"):
            p = library.material_abs_path(x["path"])
            if p and p.exists():
                return FileResponse(p)
    from ..core import config as _config
    thumbs = _config.data_dir() / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    out = thumbs / f"{mid}.jpg"
    if not out.exists():
        src = library.material_abs_path(m.get("path"))
        if not src or not src.exists():
            raise HTTPException(404, "链接型视频素材无本地文件，无法抽帧")
        _extract_first_frame(src, out)
    return FileResponse(out)


@router.get("/materials/{mid}/text")
def material_text(mid: str) -> dict:
    return {"material_id": mid, "content": dao.get_material_text(mid)}


async def _read_upload(file: UploadFile) -> bytes:
    limit = int(config.get("storage.material_size_limit_mb", 500)) * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, "上传文件超过大小限制")
    return data


@router.post("/articles/{aid}/materials/upload")
async def upload_article_material(aid: str, file: UploadFile = File(...)) -> dict:
    if not dao.get_article(aid):
        raise HTTPException(404, "文章不存在")
    data = await _read_upload(file)
    mid, created = await run_in_threadpool(library.ingest_bytes, data, file.filename or "upload.bin",
                                        "article", aid, note="GUI 上传")
    events.bus.publish(events.MATERIAL_INGESTED, aid, material_id=mid)
    return {"material_id": mid, "created": created}


_TEXT_EXT = {".txt", ".md", ".markdown"}
_HTML_EXT = {".html", ".htm"}


def _ingest_upload(aid: str, filename: str, data: bytes) -> tuple[str, bool]:
    """单个上传文件入库：按扩展名自动分流到 文章/图片/视频/音频/其他 素材目录。

    文章类做正文抽取（html 走 trafilatura，pdf 走 pypdf），保证能进证据与检索。
    """
    ext = Path(filename).suffix.lower()
    title = Path(filename).stem
    if ext in _HTML_EXT:
        raw = data.decode("utf-8", errors="replace")
        text = None
        try:
            import trafilatura
            text = trafilatura.extract(raw, include_comments=False, include_images=False)
        except Exception:
            text = None
        mid = library.ingest_text(text or raw, title=title, scope="article",
                                  article_id=aid, ref_type="upload")
        return mid, True
    if ext == ".pdf":
        try:
            import io
            from pypdf import PdfReader
            text = "\n".join((pg.extract_text() or "")
                             for pg in PdfReader(io.BytesIO(data)).pages)
            if text.strip():
                mid = library.ingest_text(text, title=title, scope="article",
                                          article_id=aid, ref_type="upload")
                return mid, True
        except Exception:
            pass        # 抽取失败按二进制文档入库
    return library.ingest_bytes(data, filename, "article", aid, note="本地上传")


@router.post("/articles/{aid}/materials/upload-batch")
async def upload_article_materials_batch(aid: str,
                                         files: list[UploadFile] = File(...)) -> dict:
    """批量上传（本地文件/文件夹）：逐文件自动识别类型、分流入库，逐条记录成败。"""
    if not dao.get_article(aid):
        raise HTTPException(404, "文章不存在")
    if len(files) > 50:
        raise HTTPException(413, "一次最多上传 50 个文件")
    ok, failed = [], []
    for f in files:
        name = f.filename or "upload.bin"
        try:
            data = await _read_upload(f)
            mid, _created = await run_in_threadpool(_ingest_upload, aid, name, data)
            ok.append({"filename": name, "material_id": mid})
            events.bus.publish(events.MATERIAL_INGESTED, aid, material_id=mid)
        except Exception as e:
            failed.append({"filename": name, "error": str(e)[:200]})
    # 本地收集模式（local:// 立档）：上传即收集完成，NEW 直达 COLLECTED
    art = dao.get_article(aid)
    if art and art["status"] == "NEW" and (art["url"] or "").startswith("local://") and ok:
        from ..core.models import ArticleStatus
        dao.set_article_status(aid, ArticleStatus.COLLECTED)
    return {"ok": ok, "failed": failed, "total": len(files)}


@router.post("/materials/upload")
async def upload_common_material(file: UploadFile = File(...)) -> dict:
    data = await _read_upload(file)
    mid, created = await run_in_threadpool(library.ingest_bytes, data, file.filename or "upload.bin",
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
    # 去重：本文库已有同 sha256 或同源链接的素材则跳过（反馈 四.3）
    if m.get("sha256"):
        dup = next((x for x in dao.find_materials_by_sha(m["sha256"])
                    if x["scope"] == "article" and x.get("article_id") == body.article_id), None)
        if dup:
            return {"material_id": dup["id"], "copied": False,
                    "reason": "本文库已存在同文件，已跳过"}
    if m.get("source_url"):
        same_src = next((x for x in dao.list_materials(scope="article", article_id=body.article_id)
                         if x.get("source_url") == m["source_url"]), None)
        if same_src:
            return {"material_id": same_src["id"], "copied": False,
                    "reason": "本文库已存在同来源链接，已跳过"}
    new_id = library._clone_for_scope(m, "article", body.article_id, m.get("note") or "")
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
        dup = next((x for x in dao.find_materials_by_sha(m["sha256"])
                    if x["scope"] == "common"), None)
        if dup:
            return {"material_id": dup["id"], "copied": False,
                    "reason": "公共库已存在同文件，已跳过"}
    new_id = library._clone_for_scope(m, "common", None, m.get("note") or "")
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
    dao.archive_material(mid)
    events.bus.publish(events.MATERIAL_INGESTED, m.get("article_id"), material_id=mid)
    return {"ok": True, "archived": True}
