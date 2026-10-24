"""通用文章爬虫：trafilatura 提取正文与元数据，lxml 补抓正文内图片。"""
from __future__ import annotations

import re

import trafilatura
from lxml import html as lxml_html

from .base import CrawlError, ImageRef, RawArticle

_SKIP_IMG = re.compile(r"logo|icon|avatar|sprite|blank|pixel|loading", re.I)


class TrafilaturaCrawler:
    name = "trafilatura"

    def can_handle(self, url: str) -> bool:
        return url.startswith(("http://", "https://"))

    def fetch(self, url: str) -> RawArticle:
        html_text = trafilatura.fetch_url(url)
        if not html_text:
            raise CrawlError("页面抓取失败（可能需要 JS 渲染或存在反爬）")
        markdown = trafilatura.extract(
            html_text, output_format="markdown", include_images=True,
            include_links=False, favor_recall=True) or ""
        if not markdown.strip():
            raise CrawlError("正文提取为空")
        meta = trafilatura.extract_metadata(html_text)

        images: list[ImageRef] = []
        try:
            doc = lxml_html.fromstring(html_text)
            for im in doc.xpath("//img[@src]"):
                src = im.get("src") or ""
                if src.startswith("//"):
                    src = "https:" + src
                if not src.startswith("http") or _SKIP_IMG.search(src):
                    continue
                images.append(ImageRef(url=src, alt=im.get("alt") or ""))
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
        )
