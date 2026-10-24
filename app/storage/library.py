"""素材库文件系统：data/library/{common|articles/<id>}/...

摄取统一入口（ingest_*）：无论 Agent 抓取、GUI 上传还是拷贝进 inbox，
都走 sha256 去重 → 落盘 → 索引入库 的同一条管线（见 docs/design/03）。
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
from pathlib import Path

from ..core.config import data_dir
from ..core.ids import new_id
from ..core.models import DraftDoc
from . import dao

_KIND_DIR = {"image": "images", "video": "videos", "doc": "docs", "text": "docs", "link": "docs"}
_IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_VID_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}


def library_root() -> Path:
    return data_dir() / "library"


def common_dir() -> Path:
    return library_root() / "common"


def article_dir(article_id: str) -> Path:
    return library_root() / "articles" / article_id


def ensure_dirs(article_id: str | None = None) -> None:
    for base in ([common_dir()] + ([article_dir(article_id)] if article_id else [])):
        for sub in ("images", "videos", "docs", "inbox"):
            (base / sub).mkdir(parents=True, exist_ok=True)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _phash(path: Path) -> str | None:
    try:
        import imagehash
        from PIL import Image
        with Image.open(path) as im:
            return str(imagehash.phash(im))
    except Exception:
        return None


def _image_size(path: Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.width, im.height
    except Exception:
        return None, None


def guess_kind(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in _IMG_EXTS:
        return "image"
    if ext in _VID_EXTS:
        return "video"
    if ext in {".txt", ".md", ".markdown"}:
        return "text"
    return "doc"


def _dest_dir(scope: str, article_id: str | None, kind: str) -> Path:
    base = common_dir() if scope == "common" else article_dir(article_id or "")
    return base / _KIND_DIR.get(kind, "docs")


def ingest_bytes(data: bytes, filename: str, scope: str, article_id: str | None = None,
                 source_url: str | None = None, source_material_id: str | None = None,
                 kind: str | None = None, ref_type: str | None = None,
                 note: str = "", title: str = "") -> tuple[str, bool]:
    """存二进制素材。返回 (material_id, 是否新建)；sha256 命中时返回已有 id 不复制。"""
    digest = _sha256(data)
    dup = dao.find_material_by_sha(digest)
    if dup:
        return dup["id"], False

    kind = kind or guess_kind(filename)
    ensure_dirs(article_id if scope == "article" else None)
    ext = Path(filename).suffix.lower() or (".bin" if kind != "text" else ".txt")
    dest = _dest_dir(scope, article_id, kind) / f"{digest[:16]}{ext}"
    dest.write_bytes(data)

    width = height = None
    ph = None
    if kind == "image":
        ph = _phash(dest)
        width, height = _image_size(dest)
    rel = str(dest.relative_to(library_root()))
    mid = dao.insert_material(
        scope=scope, article_id=article_id, kind=kind, path=rel, sha256=digest, phash=ph,
        source_url=source_url, source_material_id=source_material_id, width=width,
        height=height, ref_type=ref_type, note=note, title=title or Path(filename).stem,
    )
    if kind == "text":
        try:
            dao.set_material_text(mid, data.decode("utf-8", errors="replace"))
        except Exception:
            pass
    return mid, True


def ingest_text(content: str, title: str, scope: str, article_id: str | None = None,
                source_url: str | None = None, ref_type: str | None = None,
                meta: dict | None = None) -> str:
    """存文本素材（正文进 FTS 索引，供检索与审稿取证）。"""
    mid, _ = ingest_bytes(content.encode("utf-8"), f"{title[:40] or 'text'}.md", scope,
                          article_id, source_url=source_url, kind="text", ref_type=ref_type,
                          title=title)
    dao.set_material_text(mid, content)
    if meta:
        from . import db as _db
        _db.execute("UPDATE materials SET meta_json=? WHERE id=?",
                    (json.dumps(meta, ensure_ascii=False), mid))
    return mid


def material_abs_path(rel_path: str | None) -> Path | None:
    if not rel_path:
        return None
    return library_root() / rel_path


def save_article_snapshot(article_id: str, html: str, markdown: str, meta: dict) -> Path:
    d = article_dir(article_id) / "source"
    d.mkdir(parents=True, exist_ok=True)
    (d / "page.html").write_text(html, encoding="utf-8")
    (d / "content.md").write_text(markdown, encoding="utf-8")
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return d


def save_ref_snapshot(article_id: str, material_id: str, html: str, markdown: str,
                      meta: dict) -> Path:
    d = article_dir(article_id) / "refs" / material_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "page.html").write_text(html, encoding="utf-8")
    (d / "content.md").write_text(markdown, encoding="utf-8")
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return d


def write_notes(article_id: str, notes_md: str) -> Path:
    p = article_dir(article_id) / "notes.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(notes_md, encoding="utf-8")
    return p


def scan_inbox(article_id: str | None = None) -> list[str]:
    """扫描 inbox/ 把用户手动拷入的文件摄取入库。article_id=None 时扫公共库。"""
    scope = "article" if article_id else "common"
    base = article_dir(article_id) if article_id else common_dir()
    inbox = base / "inbox"
    ingested: list[str] = []
    if not inbox.exists():
        return ingested
    for f in sorted(inbox.iterdir()):
        if not f.is_file():
            continue
        mid, created = ingest_bytes(f.read_bytes(), f.name, scope, article_id,
                                    note="inbox 手动添加")
        if created:
            ingested.append(mid)
        shutil.move(str(f), str(f.with_suffix(f.suffix + ".done")))
    return ingested


# ---------- 文案落盘 ----------

def drafts_dir(article_id: str) -> Path:
    return data_dir() / "drafts" / article_id


def save_draft_files(doc: DraftDoc, markdown: str) -> Path:
    d = drafts_dir(doc.article_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"v{doc.version:03d}.md").write_text(markdown, encoding="utf-8")
    (d / f"v{doc.version:03d}.json").write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    return d


def save_agent_run(article_id: str, stage: str, payload: dict) -> Path:
    import time
    d = drafts_dir(article_id) / "runs"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{stage}-{int(time.time())}.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return p
