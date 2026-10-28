"""Serve only recorded material files and completed export manifests."""
import json
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse
from ..storage import db, library


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
