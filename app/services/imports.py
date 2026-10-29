"""外部项目文件夹导入（V1.14）：识别 resource/ 下新增的文章项目文件夹并重建 DB 记录。

- 判定：resource/ 一级子目录中含 reference/ 或 drafts/ 子目录的即项目文件夹；
- 幂等：按 articles.lib_dir 去重，重复扫描不产生重复记录；
- 重建：articles 行（标题去 -YYYYMMDD-HHmm 后缀；url 取 primary meta.json，否则 local://）
  + materials 行（**直接引用现有文件路径，不复制文件**）+ drafts 行（读最新 vNNN.json，
  重映射 article_id/id）；
- 状态：有草稿 → DRAFTED（可继续审稿/编辑/定稿/导出），否则 → COLLECTED（可开始创作）。
- 扫描方式：启动时全量一次 + 后台线程按 `library.import_scan_interval_sec` 定时扫描
  （默认 30s；`library.watch_imports=false` 关闭），也可 POST /api/imports/scan 手动触发。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from ..core import config, events
from ..core.files import sha256_file
from ..core.models import ArticleStatus, DraftDoc
from ..storage import dao, db, library

_SYS_DIRS = {"_cache", "common", "backups", "style_reference", "library", "runs"}
_IMG_DIR_KIND = {"图片": "image", "视频": "video", "音频": "audio", "其他": "doc"}
_IMPORT_THREAD: threading.Thread | None = None
_WATCH_LOCK = threading.RLock()
_WATCH_STOP = threading.Event()
_WATCH_USERS = 0
_SCAN_LOCK = threading.Lock()


def _is_project_dir(d: Path) -> bool:
    if not d.is_dir() or d.name in _SYS_DIRS or d.name.startswith("."):
        return False
    return (d / "reference").is_dir() or (d / "drafts").is_dir()


def scan_once() -> dict:
    """扫一遍 resource/，导入尚未入库的项目文件夹。返回 {imported, skipped}。"""
    # Background first scan and manual refresh must not import a folder twice.
    with _SCAN_LOCK:
        return _scan_once()


def _scan_once() -> dict:
    root = config.data_dir()
    imported, skipped = [], []
    if not root.is_dir():
        return {"imported": imported, "skipped": skipped}
    for d in sorted(root.iterdir()):
        if not _is_project_dir(d):
            continue
        if db.query_one("SELECT id FROM articles WHERE lib_dir=?", (d.name,)):
            skipped.append(d.name)
            continue
        try:
            aid = _import_one(d)
            imported.append({"folder": d.name, "article_id": aid})
        except Exception as e:
            skipped.append(f"{d.name}（导入失败: {e}）")
            from .. import logging_setup
            logging_setup.log("error", "External project import failed folder=%s", d.name, exc_info=True)
    return {"imported": imported, "skipped": skipped}


def _notes_meta(d: Path) -> dict:
    """从 notes.md（收集报告）提取 原文链接/来源/发布日期——比 reference 目录结构更可靠。"""
    import re
    f = d / "notes.md"
    if not f.is_file():
        return {}
    try:
        text = f.read_text(encoding="utf-8")
    except Exception:
        return {}
    out: dict = {}
    m = re.search(r"^-\s*原文:\s*(\S+)", text, re.M)
    if m:
        out["url"] = m.group(1)
    m = re.search(r"^-\s*来源:\s*(.+)$", text, re.M)
    if m:
        out["site"] = m.group(1).split("/")[0].strip()
    m = re.search(r"^-\s*发布:\s*(\S+)", text, re.M)
    if m:
        out["published_at"] = m.group(1)
    return out


def _import_one(d: Path) -> str:
    title = library._DT_SUFFIX.sub("", d.name) or d.name
    # 优先 notes.md 的原文链接（最权威），reference 的 primary meta 作兜底
    meta = {**_primary_meta(d), **_notes_meta(d)}
    url = meta.get("url") or f"local://{d.name}"
    art = dao.create_article(url, title=title)
    aid = art["id"]
    db.execute("UPDATE articles SET lib_dir=? WHERE id=?", (d.name, aid))
    if meta.get("published_at"):
        db.execute("UPDATE articles SET published_at=? WHERE id=?",
                   (meta["published_at"], aid))
    if meta.get("site"):
        db.execute("UPDATE articles SET source_site=? WHERE id=?", (meta["site"], aid))

    n_text = _import_reference_materials(d, aid, meta)
    n_draft = _import_draft(d, aid)
    dao.set_article_status(aid, ArticleStatus.DRAFTED if n_draft else ArticleStatus.COLLECTED)
    events.bus.publish(events.ARTICLE_ADDED, aid)
    events.bus.publish(events.STATUS_CHANGED, aid, status="imported")
    from .. import logging_setup
    logging_setup.log("info", "[import] 识别外部项目文件夹 %s → %s（素材 %d，草稿 %d）",
                      d.name, aid, n_text, n_draft)
    return aid


def _primary_meta(d: Path) -> dict:
    """取 primary meta.json：优先**含 page.html 的子文件夹**（只有原文快照会写
    page.html，扩搜参考只写 content.md+meta.json），没有则退回第一个。
    不依赖创建时间（拷贝文件夹会重置时间戳）。"""
    ref = d / "reference"
    if not ref.is_dir():
        return {}
    subs = [s for s in sorted(ref.iterdir()) if s.is_dir()]
    subs.sort(key=lambda s: not (s / "page.html").is_file())   # 有 page.html 的排最前
    for sub in subs:
        mf = sub / "meta.json"
        if mf.is_file():
            try:
                return json.loads(mf.read_text(encoding="utf-8"))
            except Exception:
                continue
    return {}


def _import_reference_materials(d: Path, aid: str, primary_meta: dict) -> int:
    """reference/ 下的文章与媒体直接登记到素材表（引用原路径，不复制）。"""
    ref = d / "reference"
    if not ref.is_dir():
        return 0
    count = 0
    primary_url = primary_meta.get("url")
    for f in sorted(ref.rglob("*")):
        if not f.is_file() or f.name in ("meta.json", "page.html"):
            continue
        rel = str(f.relative_to(config.data_dir()))
        kind = "text" if f.name == "content.md" else library.guess_kind(f.name)
        sha = sha256_file(f)
        title = f.parent.name if f.name == "content.md" else f.stem
        mid = dao.insert_material(
            scope="article", article_id=aid, kind=kind, path=rel, sha256=sha,
            source_url=primary_url if f.name == "content.md" else None,
            ref_type="primary" if f.name == "content.md" else "reference",
            title=title, note="外部项目导入")
        if f.name == "content.md":
            dao.set_material_text(mid, f.read_text(encoding="utf-8", errors="replace"))
        count += 1
    return count


def _import_draft(d: Path, aid: str) -> int:
    """读 drafts/ 下最新 vNNN.json，重映射为本文草稿（块级 checkpoint 直接可用）。"""
    dd = d / "drafts"
    if not dd.is_dir():
        return 0
    versions = sorted(dd.glob("v*.json"))
    if not versions:
        return 0
    latest = versions[-1]
    try:
        doc = DraftDoc.model_validate_json(latest.read_text(encoding="utf-8"))
    except Exception:
        return 0
    doc.article_id = aid
    doc.id = f"{aid}-v{doc.version}"
    dao.save_draft(doc, origin="imported")
    return 1


# ---------- 定时扫描 ----------

def start_watcher() -> bool:
    """V1.16: first full scan runs in background, never on the ready path."""
    global _IMPORT_THREAD, _WATCH_USERS
    if not config.get("library.watch_imports", True):
        return False
    with _WATCH_LOCK:
        _WATCH_USERS += 1
        if _IMPORT_THREAD and _IMPORT_THREAD.is_alive():
            return True
        _WATCH_STOP.clear()
        interval = max(1, int(config.get("library.import_scan_interval_sec", 30)))

        def _loop():
            while not _WATCH_STOP.is_set():
                try:
                    scan_once()
                except Exception:
                    from .. import logging_setup
                    logging_setup.log("error", "External project scan failed", exc_info=True)
                if _WATCH_STOP.wait(interval):
                    break

        _IMPORT_THREAD = threading.Thread(target=_loop, name="import-watcher", daemon=True)
        _IMPORT_THREAD.start()
        return True


def stop_watcher() -> None:
    global _IMPORT_THREAD, _WATCH_USERS
    with _WATCH_LOCK:
        _WATCH_USERS = max(0, _WATCH_USERS - 1)
        if _WATCH_USERS or _IMPORT_THREAD is None:
            return
        _WATCH_STOP.set()
        _IMPORT_THREAD.join()
        _IMPORT_THREAD = None
