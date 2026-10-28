"""视频下载：yt-dlp 包装（v.qq/bilibili/微博/直链通吃），失败返回 None 不阻断。"""
from __future__ import annotations

import tempfile
from pathlib import Path

from ..http import proxy_for

MAX_MB = 200


def download_video(url: str, max_mb: int = MAX_MB, timeout: int = 240) -> tuple[bytes, str] | None:
    """下载视频，返回 (bytes, 文件名)；不可下载/超限时返回 None。"""
    try:
        import yt_dlp
    except ImportError:
        return None
    with tempfile.TemporaryDirectory() as td:
        out = str(Path(td) / "v.%(ext)s")
        opts = {
            "format": f"best[filesize<{max_mb}M]/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "outtmpl": out,
            "socket_timeout": 60,
        }
        proxy = proxy_for(url)
        if proxy:
            opts["proxy"] = proxy
        try:
            import yt_dlp.utils  # noqa
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception:
            return None
        files = [f for f in Path(td).iterdir() if f.is_file()]
        if not files:
            return None
        f = max(files, key=lambda x: x.stat().st_size)
        data = f.read_bytes()
        if len(data) > max_mb * 1024 * 1024:
            return None
        return data, f.name
