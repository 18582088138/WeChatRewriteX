"""搜索注册表：取第一个已配置的搜索器；都没有则 Null（收集降级为仅原文）。"""
from __future__ import annotations

from .base import Searcher
from .tavily_search import NullSearcher, TavilySearcher

_SEARCHERS: list[Searcher] = [TavilySearcher(), NullSearcher()]


def get_searcher() -> Searcher:
    for s in _SEARCHERS:
        if s.name != "null" and s.available():
            return s
    return NullSearcher()
