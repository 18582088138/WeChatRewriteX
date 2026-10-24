"""素材库文件系统（v2：文章标题命名 + 中文分项目录）。

结构（data/ 为唯一数据根，与代码分离且整体 gitignore）：

data/library/
├── common/                      # 公共素材库
│   ├── 图片/ 视频/ 文档/ inbox/
└── articles/<文章标题_短id>/     # 每篇文章一个可读文件夹
    ├── 原文/                    # page.html content.md meta.json
    ├── 参考/<material_id>/      # 每篇参考一个子目录
    ├── 图片/  视频/  文档/
    ├── inbox/                   # 手动拷入落点（扫描即入库）
    ├── exports/<platform>/      # 发布包（含 cards/）
    └── notes.md                 # 收集报告

素材行 materials.path 记录相对 library/ 的路径；文件夹名在首次建目录时定稿
（标题已知用标题，否则用 id 兜底），并持久化到 articles.lib_dir，保证稳定。
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from ..core.config import data_dir
from . import dao, db

_KIND_DIR = {"image": "图片", "video": "视频", "doc": "文档", "text": "文档", "link": "文档"}
_IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_VID_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}


def library_root() -> Path:
    return data_dir() / "library"


def common_dir() -> Path:
    return library_root() / "common"


def _safe_name(title: str, fallback: str, limit: int = 24) -> str:
    t = re.sub(r'[\\/:*?"<>|\r\n\t]+', "", (title or "")).strip().strip(".")
    t = re.sub(r"\s+", " ", t)[:limit].strip()
    return t or fallback


def article_dir(article_id: str) -> Path:
    """文章素材目录：读 articles.lib_dir；未命名按标题定名写回；标题后到时自动迁移。"""
    row = db.query_one("SELECT id, title, lib_dir FROM articles WHERE id=?", (article_id,))
    if not row:
        return library_root() / "articles" / article_id
    title = (row.get("title") or "").strip()
    lib_dir = row.get("lib_dir")
    fallback_named = not lib_dir or lib_dir.startswith(("art_", "article_"))

    if lib_dir and (not fallback_named or not title):
        return library_root() / "articles" / lib_dir
    # 标题已知且当前是兜底名 → 迁移到标题命名
    name = f"{_safe_name(title, article_id)}_{article_id[-6:]}" if title else article_id
    if lib_dir and lib_dir != name:
        old, new = library_root() / "articles" / lib_dir, library_root() / "articles" / name
        if old.exists() and not new.exists():
            old.rename(new)
            for sep in ("/", "\\"):
                db.execute("UPDATE materials SET path=REPLACE(path, ?, ?) WHERE article_id=?",
                           (f"articles{sep}{lib_dir}{sep}", f"articles{sep}{name}{sep}",
                            article_id))
        elif new.exists():
            name = lib_dir or name   # 目标已存在则不折腾，保持原名
    db.execute("UPDATE articles SET lib_dir=? WHERE id=?", (name, article_id))
    return library_root() / "articles" / name


def exports_dir(article_id: str) -> Path:
    return article_dir(article_id) / "exports"


def ensure_dirs(article_id: str | None = None) -> None:
    bases = [common_dir()] + ([article_dir(article_id)] if article_id else [])
    for base in bases:
        for sub in ("图片", "视频", "文档", "inbox"):
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
    return base / _KIND_DIR.get(kind, "文档")


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
    # 公众号等渠道的图片 URL 常无扩展名：按内容嗅探真实格式并改名
    if kind == "image" and ext not in _IMG_EXTS:
        try:
            from PIL import Image
            with Image.open(dest) as im:
                fmt = (im.format or "").lower()
            real_ext = {"jpeg": ".jpg"}.get(fmt, f".{fmt}") if fmt else None
            if real_ext:
                new_dest = dest.with_suffix(real_ext)
                dest.rename(new_dest)
                dest = new_dest
        except Exception:
            pass

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
        db.execute("UPDATE materials SET meta_json=? WHERE id=?",
                   (json.dumps(meta, ensure_ascii=False), mid))
    return mid


def material_abs_path(rel_path: str | None) -> Path | None:
    if not rel_path:
        return None
    return library_root() / rel_path


def save_article_snapshot(article_id: str, html: str, markdown: str, meta: dict) -> Path:
    d = article_dir(article_id) / "原文"
    d.mkdir(parents=True, exist_ok=True)
    (d / "page.html").write_text(html, encoding="utf-8")
    (d / "content.md").write_text(markdown, encoding="utf-8")
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return d


def save_ref_snapshot(article_id: str, material_id: str, html: str, markdown: str,
                      meta: dict) -> Path:
    d = article_dir(article_id) / "参考" / material_id
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


# ---------- 文案版本落盘（应用内部数据，非用户素材） ----------

def drafts_dir(article_id: str) -> Path:
    return data_dir() / "drafts" / article_id


def save_draft_files(doc, markdown: str) -> Path:
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
