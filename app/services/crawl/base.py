"""爬虫插件基类。新增来源只需实现 can_handle/fetch 并注册进 registry。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ImageRef:
    url: str
    alt: str = ""


@dataclass
class VideoRef:
    url: str                 # 可 yt-dlp 的页面/直链，或 readtemplate 播放器页（降级为链接素材）
    poster: str = ""         # 封面图地址（可下载为图片素材）
    vid: str = ""            # 平台视频 id（如 wxv_）


@dataclass
class RawArticle:
    url: str
    title: str = ""
    html: str = ""
    markdown: str = ""          # 规范化正文（含 ![](url) 图片占位）
    published_at: str | None = None
    author: str = ""
    site: str = ""
    images: list[ImageRef] = field(default_factory=list)
    videos: list[VideoRef] = field(default_factory=list)
    audios: list[str] = field(default_factory=list)   # 音频直链
    extra: dict = field(default_factory=dict)   # 论文 pdf_url 等


class Crawler(Protocol):
    name: str

    def can_handle(self, url: str) -> bool: ...
    def fetch(self, url: str) -> RawArticle: ...


class CrawlError(Exception):
    pass
