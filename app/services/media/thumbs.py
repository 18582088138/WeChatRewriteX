"""视频首帧缩略图（V1.17 统一：素材库/创作列表/卡片共用）。

海报子图优先；否则 ffmpeg 抽首帧并缓存到 data/_cache/thumbs/<mid>.jpg。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ...core import config
from ...storage import dao, library


def _ffmpeg_exe() -> str | None:
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        return get_ffmpeg_exe()
    except Exception:
        import shutil
        return shutil.which("ffmpeg")


def video_thumb(mid: str, material: dict) -> Path | None:
    """视频首帧：海报子图优先，否则抽帧缓存。链接型无本地文件时返回 None。"""
    # 海报子图（微信等自带封面）
    for x in dao.list_materials(scope="article", article_id=material.get("article_id"),
                                kind="image"):
        if x.get("source_material_id") == mid and x.get("path"):
            p = library.material_abs_path(x["path"])
            if p and p.exists():
                return p
    src = library.material_abs_path(material.get("path"))
    if not src or not src.exists():
        return None
    out_dir = config.data_dir() / "_cache" / "thumbs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{mid}.jpg"
    if out.exists():
        return out
    exe = _ffmpeg_exe()
    if not exe:
        return None
    for ss in ("0.5", "0"):
        args = [exe, "-y"] + (["-ss", ss] if ss != "0" else []) + \
               ["-i", str(src), "-frames:v", "1", "-q:v", "3", str(out)]
        r = subprocess.run(args, capture_output=True, timeout=60)
        if r.returncode == 0 and out.exists():
            return out
    return None
