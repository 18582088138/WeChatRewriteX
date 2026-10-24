"""arXiv 爬虫：abs 页 → 官方 API 元数据 + 摘要，pdf 链接入 extra。"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import httpx

from .base import CrawlError, RawArticle

_ATOM = "{http://www.w3.org/2005/Atom}"


class ArxivCrawler:
    name = "arxiv"

    def can_handle(self, url: str) -> bool:
        return "arxiv.org" in url

    def fetch(self, url: str) -> RawArticle:
        m = re.search(r"arxiv\.org/(?:abs|pdf)/([\d.]+)(?:v\d+)?", url)
        if not m:
            raise CrawlError(f"无法从 URL 解析 arXiv id: {url}")
        arxiv_id = m.group(1)
        api = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
        try:
            resp = httpx.get(api, timeout=30)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise CrawlError(f"arXiv API 请求失败: {e}") from e
        root = ET.fromstring(resp.text)
        entry = root.find(f"{_ATOM}entry")
        if entry is None:
            raise CrawlError(f"arXiv 未找到条目: {arxiv_id}")
        title = (entry.findtext(f"{_ATOM}title") or "").strip().replace("\n", " ")
        summary = (entry.findtext(f"{_ATOM}summary") or "").strip()
        published = (entry.findtext(f"{_ATOM}published") or "")[:10]
        authors = ", ".join(a.findtext(f"{_ATOM}name") or ""
                            for a in entry.findall(f"{_ATOM}author"))
        markdown = f"# {title}\n\n作者: {authors}\n\n## 摘要\n\n{summary}\n"
        return RawArticle(
            url=f"https://arxiv.org/abs/{arxiv_id}", title=title, html="",
            markdown=markdown, published_at=published, author=authors,
            site="arXiv", images=[],
            extra={"pdf_url": f"https://arxiv.org/pdf/{arxiv_id}", "arxiv_id": arxiv_id},
        )
