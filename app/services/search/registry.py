"""搜索注册表。

- 网络搜索：Tavily（有 key 优先）→ Bing（零配置主力兜底）→ DuckDuckGo → Null
- 论文搜索：arXiv（始终可用），AI 要闻的原始论文来源
"""
from __future__ import annotations

from .arxiv_search import ArxivSearcher
from .base import Searcher
from .bing_search import BingSearcher
from .duckduckgo import DuckDuckGoSearcher
from .tavily_search import NullSearcher, TavilySearcher

_WEB: list[Searcher] = [TavilySearcher(), BingSearcher(), DuckDuckGoSearcher()]
_PAPER = ArxivSearcher()


def get_searcher() -> Searcher:
    """Tavily 有 key 时优先（质量与时窗过滤更好），否则零配置 Bing。"""
    if _WEB[0].available():
        return _WEB[0]
    return _WEB[1]


def get_paper_searcher() -> Searcher:
    return _PAPER


def null_searcher() -> Searcher:
    return NullSearcher()
