"""公众号内嵌视频（wxv/mpvideo）直链提取（复用 DailyNewsAssistant 验证过的思路）。

关键事实：
- 真正的 mp4 直链藏在文章 HTML 的 inline JS 里：
  `http://mpvideo.qpic.cn/<clipid>.f<fmt>.mp4?dis_k=…&auth_info=…&auth_key=…`（带签名）。
- JS 里的 `&` 被写成 `\\x26amp;`（或 `\\x26` / `&amp;`），必须先**反转义**再匹配，
  否则 URL 在第一个反斜杠处截断、丢失 auth_info/auth_key，下载得到 403。
- 同一条视频有多种码率：f10004/f10002 是 H.264，f101xx 是 HEVC——优先 H.264
  （浏览器与剪辑软件支持更好）。
"""
from __future__ import annotations

import re

from .base import VideoRef

_WX_VIDEO_RE = re.compile(
    r"https?://mpvideo\.qpic\.cn/(?P<id>[0-9a-z]+)\.(?P<format>f\d+)\.mp4[^\s\"'<>\\]*",
    re.IGNORECASE,
)

_FORMAT_ORDER = ("f10004", "f10002", "f10104", "f10102")


def extract_wechat_direct_videos(raw_html: str) -> list[VideoRef]:
    """从公众号文章 HTML 提取签名 mp4 直链（按清晰度择优、按出现顺序）。"""
    if "mpvideo.qpic.cn" not in raw_html:
        return []
    plain = (raw_html
             .replace("\\x26amp;", "&")
             .replace("\\x26", "&")
             .replace("&amp;", "&"))
    best: dict[str, tuple[int, str]] = {}
    for match in _WX_VIDEO_RE.finditer(plain):
        clip = match.group("id").lower()
        fmt = match.group("format").lower()
        rank = _FORMAT_ORDER.index(fmt) if fmt in _FORMAT_ORDER else len(_FORMAT_ORDER)
        current = best.get(clip)
        if current is None or rank < current[0]:
            best[clip] = (rank, match.group(0))
    return [VideoRef(url=url, vid=clip) for clip, (_, url) in best.items()]


def looks_like_video(data: bytes) -> bool:
    """按文件头校验是视频（防盗链错误页拦截）：ftyp/EBML/FLV/RIFF/MOV/TS。"""
    if len(data) < 12:
        return False
    if data[4:8] == b"ftyp":
        return True
    for sig in (b"\x1a\x45\xdf\xa3", b"FLV", b"RIFF", b"\x00\x00\x01"):
        if data.startswith(sig):
            return True
    return False
