"""Immutable material views for a single export/render operation."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
from pathlib import Path
import shutil

from ..storage import dao, library
from ..core.files import sha256_file

_view: ContextVar[dict | None] = ContextVar("asset_view", default=None)


def get_material(mid: str) -> dict | None:
    view = _view.get()
    return view.get(mid) if view is not None else dao.get_material(mid)


def manifest(doc) -> dict:
    ids = {mid for block in doc.blocks for mid in
           ([block.asset_id] if block.asset_id else []) + block.citations}
    ids.update(p.asset_id for p in doc.meta.xhs_pages if p.asset_id)
    return {mid: dao.get_material(mid) for mid in ids if dao.get_material(mid)}


@contextmanager
def frozen(doc, directory: Path, expected: dict | None = None):
    view = expected if expected is not None else manifest(doc)
    copied = {}
    directory.mkdir(parents=True, exist_ok=True)
    # Rename/ingest operations use the same lock; no DB transaction spans copies.
    with library._file_lock:
        for mid, material in view.items():
            item = dict(material)
            if material.get("path"):
                # Renames may update the location, but never the recorded content.
                current = dao.get_material(mid) or material
                src = library.material_abs_path(current.get("path"))
                if not src or not src.is_file():
                    raise ValueError(f"素材文件不存在: {mid}")
                target = directory / f"{mid}{src.suffix.lower()}"
                shutil.copy2(src, target)
                digest = sha256_file(target)
                if material.get("sha256") and digest != material["sha256"]:
                    raise ValueError(f"素材内容与快照不符: {mid}")
                item["path"] = str(target.relative_to(library.library_root()))
                item["sha256"] = digest
            copied[mid] = item
    token = _view.set(copied)
    try:
        yield copied
    finally:
        _view.reset(token)
