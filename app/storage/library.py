"""素材库文件系统 v3（resource 根目录 + 项目文件夹 + reference 同级 + 类型子目录）。

布局（resource/ 为唯一数据根，gitignore，运行时自动创建）：

resource/
├── app.db  style_reference/
├── common/                                # 公共素材库
│   ├── reference/<文章标题>/               # 公共文章素材（与项目内同级结构）
│   ├── 图片/  视频/  音频/  其他/
│   └── inbox/                             # 手动拷入落点，扫描即入库
└── <项目名 = 输入文章标题-YYYYMMDD-HHmm>/    # 文章项目文件夹（创作定题后改名的标题）
    ├── reference/
    │   ├── <输入文章标题>/  page.html content.md meta.json
    │   └── <参考文章标题>/  （与输入文章同级，不做来源隔离）
    ├── 图片/  视频/  音频/  其他/
    ├── inbox/
    ├── exports/<platform>/                # 发布包（xhs_cards/ 也在此）
    ├── drafts/                            # 文案版本 vNNN.md/.json + runs/
    └── notes.md                           # 收集报告

素材行 materials.path 记录相对 resource/ 的路径；文件夹名持久化在 articles.lib_dir。
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import shutil
from pathlib import Path

from ..core.config import data_dir
from . import dao, db

_KIND_DIR = {"image": "图片", "video": "视频", "audio": "音频",
             "doc": "其他", "text": "reference", "link": "其他"}
_IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_VID_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
_AUD_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}

_DT_SUFFIX = re.compile(r"-(\d{8}-\d{4})$")


def library_root() -> Path:
    """resource/ 根（library_root 之名保留以免大面积改动调用点）。"""
    return data_dir()


def common_dir() -> Path:
    return library_root() / "common"


def _safe_name(title: str, fallback: str, limit: int = 40) -> str:
    t = re.sub(r'[\\/:*?"<>|\r\n\t]+', "", (title or "")).strip().strip(".")
    t = re.sub(r"\s+", " ", t)[:limit].strip()
    return t or fallback


def _dt_of(article_row: dict | None = None) -> str:
    if article_row and article_row.get("created_at"):
        try:
            dt = datetime.datetime.strptime(article_row["created_at"][:16], "%Y-%m-%d %H:%M")
            return dt.strftime("%Y%m%d-%H%M")
        except ValueError:
            pass
    return datetime.datetime.now().strftime("%Y%m%d-%H%M")


def article_dir(article_id: str) -> Path:
    """项目文件夹：<输入文章标题-日期时间>；标题后到时迁移；创作定题后由 rename_to_created_title 改名。"""
    row = db.query_one("SELECT id, title, lib_dir, created_at FROM articles WHERE id=?",
                       (article_id,))
    if not row:
        return library_root() / article_id
    title = (row.get("title") or "").strip()
    lib_dir = row.get("lib_dir")
    # 已定名（符合 标题-日期时间 规范）就直接用
    if lib_dir and _DT_SUFFIX.search(lib_dir):
        return library_root() / lib_dir
    # 旧命名（标题_短id 或 art_ 兜底）或无命名 → 迁移/定名
    name = f"{_safe_name(title, article_id)}-{_dt_of(row)}"
    if lib_dir and lib_dir != name:
        _migrate_dir_name(article_id, lib_dir, name)
    db.execute("UPDATE articles SET lib_dir=? WHERE id=?", (name, article_id))
    return library_root() / name


def _migrate_dir_name(article_id: str, old: str, new: str) -> None:
    """物理改名 + 素材 path 前缀重写。目标已存在则保持原名。"""
    old_p, new_p = library_root() / old, library_root() / new
    if not old_p.exists():
        return
    if new_p.exists():
        return
    old_p.rename(new_p)
    for sep in ("/", "\\"):
        db.execute("UPDATE materials SET path=REPLACE(path, ?, ?) WHERE article_id=?",
                   (f"{old}{sep}", f"{new}{sep}", article_id))


def rename_to_created_title(article_id: str, new_title: str) -> Path:
    """创作 Agent 定题后：把文件夹从「输入标题-日期」改名为「拟定标题-日期」（日期保留）。"""
    row = db.query_one("SELECT lib_dir, created_at FROM articles WHERE id=?", (article_id,))
    if not row or not row.get("lib_dir"):
        return article_dir(article_id)
    old = row["lib_dir"]
    m = _DT_SUFFIX.search(old)
    dt = m.group(1) if m else _dt_of(row)
    slug = _safe_name(new_title, "")
    if not slug:
        return library_root() / old
    name = f"{slug}-{dt}"
    if name != old:
        _migrate_dir_name(article_id, old, name)
        db.execute("UPDATE articles SET lib_dir=? WHERE id=?", (name, article_id))
    return library_root() / name


def exports_dir(article_id: str) -> Path:
    return article_dir(article_id) / "exports"


def ensure_dirs(article_id: str | None = None) -> None:
    bases = [common_dir()] + ([article_dir(article_id)] if article_id else [])
    for base in bases:
        for sub in ("图片", "视频", "音频", "其他", "reference", "inbox"):
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
    if ext in _AUD_EXTS:
        return "audio"
    if ext in {".txt", ".md", ".markdown"}:
        return "text"
    return "doc"


def _dest_dir(scope: str, article_id: str | None, kind: str) -> Path:
    base = common_dir() if scope == "common" else article_dir(article_id or "")
    return base / _KIND_DIR.get(kind, "其他")


def _unique_dir(parent: Path, name: str) -> Path:
    """reference/<标题> 重名时追加 -2/-3。"""
    cand = parent / name
    n = 2
    while cand.exists():
        cand = parent / f"{name}-{n}"
        n += 1
    return cand


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
                meta: dict | None = None, folder: Path | None = None) -> str:
    """存文章素材：reference/<标题>/content.md（正文进 FTS 索引）。

    folder 给定时直接写入该目录（与 page.html/meta.json 快照同夹），否则按标题自建。"""
    digest = _sha256(content.encode("utf-8"))
    dup = dao.find_material_by_sha(digest)
    if dup:
        return dup["id"]
    if folder is None:
        ensure_dirs(article_id if scope == "article" else None)
        base = common_dir() if scope == "common" else article_dir(article_id or "")
        folder = _unique_dir(base / "reference", _safe_name(title, digest[:8]))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "content.md").write_text(content, encoding="utf-8")
    if meta and not (folder / "meta.json").exists():
        (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    rel = str(folder.relative_to(library_root()))
    mid = dao.insert_material(
        scope=scope, article_id=article_id, kind="text", path=rel + "/content.md",
        sha256=digest, source_url=source_url, ref_type=ref_type,
        title=title or digest[:8],
    )
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
    base = article_dir(article_id) / "reference"
    folder = _unique_dir(base, _safe_name(meta.get("title") or "", "原文"))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "page.html").write_text(html, encoding="utf-8")
    (folder / "content.md").write_text(markdown, encoding="utf-8")
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    return folder


def save_ref_snapshot(article_id: str, material_id: str, html: str, markdown: str,
                      meta: dict) -> Path:
    base = article_dir(article_id) / "reference"
    folder = _unique_dir(base, _safe_name(meta.get("title") or "", material_id))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "page.html").write_text(html, encoding="utf-8")
    (folder / "content.md").write_text(markdown, encoding="utf-8")
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    return folder


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


# ---------- 文案版本落盘（项目文件夹内 drafts/） ----------

def drafts_dir(article_id: str) -> Path:
    return article_dir(article_id) / "drafts"


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
