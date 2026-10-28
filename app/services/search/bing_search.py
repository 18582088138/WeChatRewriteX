"""Bing HTML 搜索：零配置关联搜索兜底（无 API key 时的主力）。

www.bing.com/search 不需要 key，结果链接是 /ck/a 跳转：
真实地址在 u 参数（"a1" 前缀 + base64url）。解析还原后返回。
"""
from __future__ import annotations

import base64
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx

from .. import http
from lxml import html as lxml_html

from .base import SearchResult

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


class BingSearcher:
    name = "bing"

    def available(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 8,
               days_window: int | None = None) -> list[SearchResult]:
        params = {"q": query, "count": max_results * 2, "setlang": "zh-hans",
                  "mkt": "zh-CN", "cc": "CN"}
        if days_window:
            params["filters"] = f"ex1:\"ez{(days_window * 2)}\""
        try:
            resp = http.get("https://www.bing.com/search", params=params,
                             headers={"User-Agent": UA,
                                      "Accept-Language": "zh-CN,zh;q=0.9"},
                             timeout=20, follow_redirects=True)
            resp.raise_for_status()
        except httpx.HTTPError:
            return []
        try:
            doc = lxml_html.fromstring(resp.text)
        except Exception:
            return []
        out: list[SearchResult] = []
        for li in doc.xpath("//li[contains(@class,'b_algo')]"):
            a_nodes = li.xpath(".//h2/a")
            if not a_nodes:
                continue
            a = a_nodes[0]
            href = _unwrap(a.get("href", ""))
            title = " ".join(a.text_content().split())
            if not href.startswith("http") or not title:
                continue
            snippet = " ".join(li.xpath("string(.//p)").split())[:300]
            out.append(SearchResult(title=title, url=href, snippet=snippet,
                                    source="bing"))
            if len(out) >= max_results:
                break
        return out


def _unwrap(href: str) -> str:
    """解 Bing /ck/a 跳转：u 参数 = 'a1' + base64url(真实 URL)。"""
    if "/ck/a" not in href:
        return href
    u = parse_qs(urlparse(href).query).get("u", [""])[0]
    if u.startswith("a1"):
        try:
            padded = u[2:] + "=" * (-len(u[2:]) % 4)
            return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
        except Exception:
            return href
    return href
