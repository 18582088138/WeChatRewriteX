"""Serve only recorded material files and completed export manifests."""
import json
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse
from ..storage import db, library


def export_directories(article_id: str) -> list[Path]:
    """Fixed packages first; legacy runs remain readable until explicitly removed."""
    root = library.exports_dir(article_id).resolve()
    directories = []
    for platform in ("wechat_mp", "xhs", "weibo", "x"):
        fixed = root / platform
        if fixed.resolve().is_relative_to(root) and (fixed / "manifest.json").is_file():
            directories.append(fixed)
            continue
        for job in db.query("SELECT result_json FROM publish_jobs WHERE article_id=? AND platform=? AND status='done' ORDER BY created_at DESC, rowid DESC", (article_id, platform)):
            legacy = Path(json.loads(job["result_json"]).get("export_dir") or ".").resolve()
            if legacy.is_relative_to(root) and (legacy / "manifest.json").is_file():
                directories.append(legacy)
                break
    return directories


def package_files(directory: Path) -> list[Path]:
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        names = list(manifest["files"]) + ["manifest.json"]
        root = directory.resolve()
        return [p for name in names if not any(part.startswith(("_", ".")) for part in Path(name).parts)
                if (p := (directory / name).resolve()).is_relative_to(root) and p.is_file()]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def response(path: Path):
    active = path.suffix.lower() in (".html", ".htm", ".svg", ".xml", ".js")
    headers = {"X-Content-Type-Options": "nosniff"}
    if active:
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'"
    return FileResponse(path, filename=path.name if active else None, headers=headers)


def recorded_file(relative: str) -> Path:
    try:
        target = library.material_abs_path(relative)
    except ValueError:
        raise HTTPException(404, "文件不存在")
    if not target or not target.is_file():
        raise HTTPException(404, "文件不存在")
    root = library.library_root().resolve()
    normalized = target.relative_to(root).as_posix()
    material = db.query_one("SELECT path FROM materials WHERE REPLACE(path, char(92), '/')=?", (normalized,))
    if material:
        return target
    for article in db.query("SELECT id, lib_dir FROM articles WHERE lib_dir IS NOT NULL"):
        if target.is_relative_to((root / article["lib_dir"]).resolve()):
            for directory in export_directories(article["id"]):
                if target in package_files(directory):
                    return target
    for job in db.query("SELECT result_json FROM publish_jobs WHERE status='done'"):
        result = json.loads(job["result_json"] or "{}")
        directory = Path(result.get("export_dir") or ".").resolve()
        if directory.is_relative_to(root) and target.is_relative_to(directory):
            if target.relative_to(directory).as_posix() in result.get("files", []):
                return target
    # Standalone generated cards have a restricted, article-owned directory.
    if target.name.startswith("page-") and target.suffix == ".png" and target.parent.name == "xhs_cards":
        article = db.query_one("SELECT id FROM articles WHERE lib_dir=?", (target.parent.parent.parent.name,))
        if article:
            return target
    raise HTTPException(404, "文件未公开")
