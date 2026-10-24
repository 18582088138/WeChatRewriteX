"""资料收集 Agent：抓取 → 主题提炼 → 关联搜索 → 素材入库 → 收集报告。

每一步产物落盘；LLM/搜索不可用时降级（仅原文，scarce=true），不阻断流程。
"""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from ..core import config, events
from ..core.models import CollectionReport, RefType
from ..storage import dao, library
from ..services.crawl import registry as crawl_registry
from ..services.crawl.base import CrawlError, RawArticle
from ..services.media import download as media_download
from ..services.media import stock as stock_media
from ..services.search.registry import get_paper_searcher, get_searcher
from ..services.rag import index as rag_index
from .base import AgentBase


class TopicExtract(BaseModel):
    topic: str = ""
    keywords: list[str] = Field(default_factory=list)
    core_points: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    foundational_queries: list[str] = Field(default_factory=list)


class CollectorAgent(AgentBase):
    name = "collector"

    def run(self, article_id: str) -> CollectionReport:
        article = dao.get_article(article_id)
        if not article:
            raise ValueError(f"文章不存在: {article_id}")

        raw = self._fetch_primary(article)          # 先拿标题，再建目录（文件夹用标题命名）
        library.ensure_dirs(article_id)
        primary_mid = self._store_primary(article_id, raw)
        self._collect_images(raw, article_id, primary_mid)

        extract = self._extract_topic(raw)
        refs = self._search_and_fetch_refs(article_id, raw, extract)
        media_stats = self._enrich_media(article_id, extract)

        report = CollectionReport(
            topic=extract.topic, keywords=extract.keywords,
            core_points=extract.core_points, entities=extract.entities,
            published_at=raw.published_at,
            refs=[{"material_id": m, "ref_type": rt, "url": u} for m, rt, u in refs],
            scarce=len(refs) < int(config.get("collect.ref_count.min", 3)),
        )
        if len(refs) < int(config.get("collect.ref_count.scarce_min", 1)):
            report.scarce = True

        notes = self._render_notes(article, raw, extract, refs, media_stats)
        notes_path = library.write_notes(article_id, notes)
        report.notes_path = str(notes_path)

        rag_index.index_materials(article_id=article_id)   # 无 embedding 渠道时静默跳过
        library.save_agent_run(article_id, "collect",
                               report.model_dump() | {"keywords": extract.keywords})
        events.bus.publish(events.COLLECT_FINISHED, article_id,
                           refs=len(refs), scarce=report.scarce)
        return report

    # ---- 步骤 ----

    def _fetch_primary(self, article: dict) -> RawArticle:
        raw = crawl_registry.fetch(article["url"])
        library.save_article_snapshot(article["id"], raw.html or "", raw.markdown, {
            "url": raw.url, "title": raw.title, "published_at": raw.published_at,
            "author": raw.author, "site": raw.site, "extra": raw.extra,
        })
        dao.update_article(article["id"], title=raw.title, source_site=raw.site,
                           published_at=raw.published_at)
        return raw

    def _store_primary(self, article_id: str, raw: RawArticle) -> str:
        return library.ingest_text(
            raw.markdown, title=raw.title or "原文", scope="article",
            article_id=article_id, source_url=raw.url, ref_type=RefType.PRIMARY.value,
            meta={"author": raw.author, "site": raw.site, "published_at": raw.published_at})

    def _collect_images(self, raw: RawArticle, article_id: str, source_mid: str) -> list[str]:
        if not raw.images:
            return []
        return media_download.fetch_images(
            raw.images, scope="article", article_id=article_id,
            source_material_id=source_mid, page_url=raw.url)

    def _extract_topic(self, raw: RawArticle) -> TopicExtract:
        if not self.llm_available():
            return TopicExtract(topic=raw.title, keywords=[raw.title] if raw.title else [],
                                core_points=[], entities=[])
        prompt = self.prompt("topic_extract", title=raw.title,
                             published_at=raw.published_at,
                             content=raw.markdown[:6000])
        try:
            result = self.complete("summarize", [{"role": "user", "content": prompt}],
                                   schema=TopicExtract, stage="collector.topic_extract")
            return result.parsed
        except Exception:
            return TopicExtract(topic=raw.title, keywords=[raw.title] if raw.title else [])

    def _search_and_fetch_refs(self, article_id: str, raw: RawArticle,
                               extract: TopicExtract) -> list[tuple[str, str, str]]:
        """网络搜索 + arXiv 论文两路并集，目标凑齐 min~max 篇。返回 [(mid, ref_type, url)]。"""
        web = get_searcher()
        window = int(config.get("collect.search_window_days", 3))
        ref_min, ref_max = (int(config.get("collect.ref_count.min", 3)),
                            int(config.get("collect.ref_count.max", 5)))
        out: list[tuple[str, str, str]] = []
        seen_urls = {raw.url}

        def _take(results, ref_type: RefType, cap: int) -> None:
            for r in results:
                if len(out) >= cap:
                    break
                if r.url in seen_urls:
                    continue
                seen_urls.add(r.url)
                mid = self._fetch_ref(article_id, r.url, ref_type)
                if mid:
                    out.append((mid, ref_type.value, r.url))

        # 1) 网络参考（窗口内）
        queries: list[str] = []
        if extract.keywords:
            queries.append(" ".join(extract.keywords[:3]))
        if extract.topic:
            queries.append(extract.topic)
        for e in extract.entities[:2]:
            queries.append(e)
        for q in queries:
            if len(out) >= ref_max:
                break
            _take(web.search(q, max_results=6, days_window=window), RefType.REFERENCE, ref_max)

        # 2) 原始论文/基础资料（允许跳出窗口；AI 要闻基本总能关联到论文）
        if config.get("collect.allow_foundational", True) and len(out) < ref_max:
            paper_q = (extract.foundational_queries or [])[:1]
            if not paper_q and extract.keywords:
                paper_q = [" ".join(extract.keywords[:2])]
            for q in paper_q:
                if len(out) >= ref_max:
                    break
                _take(get_paper_searcher().search(q, max_results=2),
                      RefType.FOUNDATIONAL, ref_max)
        return out

    def _enrich_media(self, article_id: str, extract: TopicExtract) -> dict:
        """原文媒体不足时，用可商用图/视频库按主题补齐（配图/视频策略的兜底）。"""
        try:
            kw = extract.keywords or ([extract.topic] if extract.topic else [])
            return stock_media.enrich_media(article_id, kw)
        except Exception:
            return {"images": 0, "videos": 0}

    def _fetch_ref(self, article_id: str, url: str, ref_type: RefType) -> str | None:
        try:
            raw = crawl_registry.fetch(url)
        except CrawlError:
            dao.insert_material(scope="article", article_id=article_id, kind="link",
                                source_url=url, ref_type=ref_type.value,
                                fetch_status="fetch_error", title=url)
            return None
        mid = library.ingest_text(raw.markdown, title=raw.title or url, scope="article",
                                  article_id=article_id, source_url=url,
                                  ref_type=ref_type.value,
                                  meta={"site": raw.site, "published_at": raw.published_at})
        library.save_ref_snapshot(article_id, mid, raw.html or "", raw.markdown,
                                  {"url": url, "title": raw.title,
                                   "published_at": raw.published_at})
        # 参考篇图片少量抓取下（每篇至多 5 张）
        media_download.fetch_images(raw.images[:5], scope="article", article_id=article_id,
                                    source_material_id=mid, page_url=url)
        return mid

    @staticmethod
    def _render_notes(article: dict, raw: RawArticle, extract: TopicExtract,
                      refs: list[tuple[str, str, str]], media_stats: dict | None = None) -> str:
        lines = [
            f"# 收集报告：{raw.title or article['url']}", "",
            f"- 原文: {raw.url}",
            f"- 来源: {raw.site} / {raw.author}",
            f"- 发布: {raw.published_at or '未知'}",
            f"- 主题: {extract.topic}", "",
            "## 关键词", *[f"- {k}" for k in extract.keywords], "",
            "## 核心要点", *[f"- {p}" for p in extract.core_points], "",
            "## 实体", ", ".join(extract.entities) or "（无）", "",
            "## 参考素材",
        ]
        for mid, rt, url in refs:
            lines.append(f"- [{rt}] {mid} — {url}")
        if media_stats:
            lines += ["", "## 媒体补充",
                      f"- 补充配图 {media_stats.get('images', 0)} 张 / 视频 "
                      f"{media_stats.get('videos', 0)} 个（可商用素材库）"]
        return "\n".join(lines) + "\n"
