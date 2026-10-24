"""爬虫注册表：按序分派。fixture 爬虫供测试/离线冒烟使用。"""
from __future__ import annotations

from pathlib import Path

from .arxiv_crawler import ArxivCrawler
from .base import CrawlError, Crawler, ImageRef, RawArticle
from .trafilatura_crawler import TrafilaturaCrawler
from .wechat_mp import WechatMpCrawler


class FixtureCrawler:
    """读取本地 HTML/Markdown 文件作为文章来源（测试与离线演示用）。

    url 形式: fixture://<文件名>，文件位于 tests/fixtures/ 或绝对路径。
    """
    name = "fixture"

    def can_handle(self, url: str) -> bool:
        return url.startswith("fixture://")

    def fetch(self, url: str) -> RawArticle:
        rel = url[len("fixture://"):]
        path = Path(rel)
        if not path.is_absolute():
            from ...core.config import PROJECT_ROOT
            path = PROJECT_ROOT / "tests" / "fixtures" / rel
        if not path.exists():
            raise CrawlError(f"fixture 不存在: {path}")
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() in {".md", ".txt"}:
            md, html = text, ""
        else:
            html = text
            import trafilatura
            md = trafilatura.extract(text, output_format="markdown", favor_recall=True) or text
        return RawArticle(url=url, title=path.stem, html=html, markdown=md,
                          published_at="2026-10-20", site="fixture", images=[])


_CRAWLERS: list[Crawler] = [WechatMpCrawler(), ArxivCrawler(), FixtureCrawler(), TrafilaturaCrawler()]


def fetch(url: str) -> RawArticle:
    for c in _CRAWLERS:
        if c.can_handle(url):
            return c.fetch(url)
    raise CrawlError(f"没有爬虫能处理: {url}")


def register(crawler: Crawler, first: bool = False) -> None:
    _CRAWLERS.insert(0 if first else len(_CRAWLERS), crawler)
