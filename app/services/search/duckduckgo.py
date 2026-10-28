"""DuckDuckGo HTML 搜索：零配置的关联搜索兜底（无 API key 时用）。

走 html.duckduckgo.com 的轻量端点，解析结果链接（uddg 跳转参数还原真实地址）。
免费端点有限频，失败静默返回空，由上层决定降级。
"""
from __future__ import annotations

from urllib.parse import parse_qs, quote_plus, urlparse

import httpx

from .. import http
from lxml import html as lxml_html

from .base import SearchResult

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


class DuckDuckGoSearcher:
    name = "duckduckgo"

    def available(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 8,
               days_window: int | None = None) -> list[SearchResult]:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            resp = http.get(url, headers={"User-Agent": UA}, timeout=20,
                             follow_redirects=True)
            resp.raise_for_status()
        except httpx.HTTPError:
            return []
        try:
            doc = lxml_html.fromstring(resp.text)
        except Exception:
            return []
        out: list[SearchResult] = []
        for a in doc.xpath("//a[contains(@class,'result__a')]"):
            href = a.get("href", "")
            real = _unwrap(href)
            if not real or not real.startswith("http"):
                continue
            title = " ".join(a.text_content().split())
            out.append(SearchResult(title=title, url=real, source="duckduckgo"))
            if len(out) >= max_results:
                break
        return out


def _unwrap(href: str) -> str:
    """DuckDuckGo 结果链接形如 //duckduckgo.com/l/?uddg=<urlencoded>。"""
    if "uddg=" in href:
        qs = parse_qs(urlparse(href).query)
        return (qs.get("uddg") or [""])[0]
    if href.startswith("//"):
        return "https:" + href
    return href
