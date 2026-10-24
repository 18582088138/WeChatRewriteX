"""搜索插件基类。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    published_at: str | None = None
    source: str = ""


class Searcher(Protocol):
    name: str

    def available(self) -> bool: ...
    def search(self, query: str, max_results: int = 8,
               days_window: int | None = None) -> list[SearchResult]: ...
