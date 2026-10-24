"""Tavily 搜索（需 TAVILY_API_KEY）。"""
from __future__ import annotations

import httpx

from ...core import config
from .base import SearchResult


class TavilySearcher:
    name = "tavily"

    def available(self) -> bool:
        return bool(config.get_env("TAVILY_API_KEY"))

    def search(self, query: str, max_results: int = 8,
               days_window: int | None = None) -> list[SearchResult]:
        payload: dict = {
            "api_key": config.get_env("TAVILY_API_KEY"),
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
        }
        if days_window:
            payload["days"] = max(1, days_window * 2 + 1)  # 前后 N 天 → 总跨度
        try:
            resp = httpx.post("https://api.tavily.com/search", json=payload, timeout=30)
            resp.raise_for_status()
        except httpx.HTTPError:
            return []
        out = []
        for r in resp.json().get("results", []):
            out.append(SearchResult(
                title=r.get("title", ""), url=r.get("url", ""),
                snippet=r.get("content", ""), published_at=r.get("published_date"),
                source="tavily"))
        return out


class NullSearcher:
    name = "null"

    def available(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 8,
               days_window: int | None = None) -> list[SearchResult]:
        return []
