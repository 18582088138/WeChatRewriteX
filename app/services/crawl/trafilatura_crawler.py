"""通用文章爬虫：trafilatura 提取正文与元数据，lxml 补抓正文内图片。"""
from __future__ import annotations

import re

import httpx
from lxml import html as lxml_html

from .base import CrawlError, ImageRef, RawArticle
from .. import http

_SKIP_IMG = re.compile(r"logo|icon|avatar|sprite|blank|pixel|loading", re.I)


class TrafilaturaCrawler:
    name = "trafilatura"

    def can_handle(self, url: str) -> bool:
        return url.startswith(("http://", "https://"))

    def fetch(self, url: str) -> RawArticle:
        # Parsing is non-core startup work; load only for actual article fetches.
        import trafilatura
        from .wechat_mp import UA
        try:
            response = http.get(url, untrusted=True, headers={"User-Agent": UA}, timeout=30,
                                follow_redirects=True)
            response.raise_for_status()
            html_text = response.text
        except httpx.HTTPError as exc:
            raise CrawlError(f"页面请求失败，请检查网络和系统代理: {exc}") from exc
        if not html_text:
            raise CrawlError("页面抓取失败（可能需要 JS 渲染或存在反爬）")
        from ..media.filter import clean_markdown, image_url_ok
        markdown = trafilatura.extract(
            html_text, output_format="markdown", include_images=True,
            include_links=False, favor_recall=True) or ""
        if not markdown.strip():
            raise CrawlError("正文提取为空")
        markdown = clean_markdown(markdown)
        meta = trafilatura.extract_metadata(html_text)

        images: list[ImageRef] = []
        videos: list = []
        try:
            from .base import VideoRef
            doc = lxml_html.fromstring(html_text)
            for im in doc.xpath("//img[@src]"):
                src = im.get("src") or ""
                if src.startswith("//"):
                    src = "https:" + src
                if not src.startswith("http") or not image_url_ok(src):
                    continue
                images.append(ImageRef(url=src, alt=im.get("alt") or ""))
            # 文内嵌视频（iframe 播放器 / video 标签）
            for iframe in doc.xpath("//iframe"):
                src = iframe.get("data-src") or iframe.get("src") or ""
                if any(h in src for h in ("v.qq.com", "player.bilibili.com",
                                          "youtube.com", "youtube-nocookie.com")):
                    videos.append(VideoRef(
                        url=src if src.startswith("http") else "https:" + src.lstrip("/")))
            for v in doc.xpath("//video"):
                src = v.get("data-src") or v.get("src") or ""
                if src.startswith("http"):
                    videos.append(VideoRef(url=src, poster=v.get("poster") or ""))
                for s in v.xpath(".//source"):
                    ssrc = s.get("src") or ""
                    if ssrc.startswith("http"):
                        videos.append(VideoRef(url=ssrc))
        except Exception:
            pass

        return RawArticle(
            url=url,
            title=(meta.title if meta and meta.title else "") or "",
            html=html_text, markdown=markdown,
            published_at=(meta.date if meta else None),
            author=(meta.author if meta and meta.author else "") or "",
            site=(meta.sitename if meta and meta.sitename else "") or "",
            images=images,
            videos=list({v.url: v for v in videos}.values()),
        )
