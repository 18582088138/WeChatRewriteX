"""arXiv 论文搜索（无需 key），为 AI 要闻补原始论文/基础资料。"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import quote

import httpx

from .. import http

from .base import SearchResult

_ATOM = "{http://www.w3.org/2005/Atom}"


class ArxivSearcher:
    name = "arxiv"

    def available(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 5,
               days_window: int | None = None) -> list[SearchResult]:
        # all: 全字段检索；按提交日期倒序保证「要闻相关」的新鲜度
        q = quote(f'all:"{query}"')
        url = (f"https://export.arxiv.org/api/query?search_query={q}"
               f"&start=0&max_results={max_results}&sortBy=submittedDate&sortOrder=descending")
        try:
            resp = http.get(url, timeout=30)
            resp.raise_for_status()
        except httpx.HTTPError:
            return []
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError:
            return []
        out: list[SearchResult] = []
        for entry in root.findall(f"{_ATOM}entry"):
            title = (entry.findtext(f"{_ATOM}title") or "").strip().replace("\n", " ")
            link = entry.findtext(f"{_ATOM}id") or ""
            published = (entry.findtext(f"{_ATOM}published") or "")[:10]
            snippet = ((entry.findtext(f"{_ATOM}summary") or "").strip())[:300]
            if title and link:
                out.append(SearchResult(title=title, url=link, snippet=snippet,
                                        published_at=published, source="arxiv"))
        return out
