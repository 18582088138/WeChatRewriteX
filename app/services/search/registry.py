"""搜索注册表。

- 网络搜索：Tavily（有 key 优先）→ DuckDuckGo（零配置兜底）→ Null
- 论文搜索：arXiv（始终可用），AI 要闻的原始论文来源
"""
from __future__ import annotations

from .arxiv_search import ArxivSearcher
from .base import Searcher
from .duckduckgo import DuckDuckGoSearcher
from .tavily_search import NullSearcher, TavilySearcher

_WEB: list[Searcher] = [TavilySearcher(), DuckDuckGoSearcher()]
_PAPER = ArxivSearcher()


def get_searcher() -> Searcher:
    """第一个可用的网络搜索器；Tavily 有 key 时优先（质量与时窗过滤更好）。"""
    tavily = _WEB[0]
    if tavily.available():
        return tavily
    return _WEB[1]


def get_paper_searcher() -> Searcher:
    return _PAPER


def null_searcher() -> Searcher:
    return NullSearcher()
