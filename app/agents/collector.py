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
from ..services.crawl.base import CrawlError, ImageRef, RawArticle
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

    def _progress(self, article_id: str, message: str) -> None:
        """分阶段进度事件：前端等待动画 + 文字日志（反馈 3.4）；开发者模式同时写日志。"""
        events.bus.publish(events.STAGE_PROGRESS, article_id,
                           stage="collect", message=message)
        from .. import logging_setup
        logging_setup.log("info", "[collect] %s (article=%s)", message, article_id)

    def run(self, article_id: str) -> CollectionReport:
        article = dao.get_article(article_id)
        if not article:
            raise ValueError(f"文章不存在: {article_id}")

        self._progress(article_id, "抓取原文与快照…")
        raw = self._fetch_primary(article)
        self._progress(article_id, f"抓取文章【{raw.title or article['url']}】完成")
        library.ensure_dirs(article_id)
        primary_mid = self._store_primary(article_id, raw)
        self._progress(article_id, "提取主题与报道主体（规则抽取）…")
        extract = self._extract_topic(raw)
        self._progress(article_id, "抓取原文图片 / 视频 / 音频…")
        self._collect_images(raw, article_id, primary_mid)
        # V1.12：扩搜（关联搜索补参考）已下线——耗时长且返回与主题无关，待更好替代方案
        refs: list[tuple[str, str, str]] = []
        self._progress(article_id, "补充可商用配图/视频素材…")
        media_stats = self._enrich_media(article_id, extract)

        report = CollectionReport(
            topic=extract.topic, keywords=extract.keywords,
            core_points=extract.core_points, entities=extract.entities,
            published_at=raw.published_at,
            refs=[],
            scarce=False,
        )

        self._progress(article_id, "素材入库与索引…")
        notes = self._render_notes(article, raw, extract, refs, media_stats)
        notes_path = library.write_notes(article_id, notes)
        report.notes_path = str(notes_path)

        rag_index.index_materials(article_id=article_id)   # 无 embedding 渠道时静默跳过
        library.save_agent_run(article_id, "collect",
                               report.model_dump() | {"keywords": extract.keywords})
        events.bus.publish(events.COLLECT_FINISHED, article_id,
                           refs=0, scarce=report.scarce)
        return report

    # ---- 步骤 ----

    def _fetch_primary(self, article: dict) -> RawArticle:
        raw = crawl_registry.fetch(article["url"])
        dao.update_article(article["id"], title=raw.title, source_site=raw.site,
                           published_at=raw.published_at)   # 先落标题（文件夹命名要用）
        folder = library.save_article_snapshot(article["id"], raw.html or "", raw.markdown, {
            "url": raw.url, "title": raw.title, "published_at": raw.published_at,
            "author": raw.author, "site": raw.site, "extra": raw.extra,
        })
        self._primary_folder = folder
        return raw

    def _store_primary(self, article_id: str, raw: RawArticle) -> str:
        return library.ingest_text(
            raw.markdown, title=raw.title or "原文", scope="article",
            article_id=article_id, source_url=raw.url, ref_type=RefType.PRIMARY.value,
            meta={"author": raw.author, "site": raw.site, "published_at": raw.published_at},
            folder=getattr(self, "_primary_folder", None))

    def _collect_images(self, raw: RawArticle, article_id: str, source_mid: str) -> list[str]:
        saved = []
        if raw.images:
            imgs = media_download.fetch_images(
                raw.images, scope="article", article_id=article_id,
                source_material_id=source_mid, page_url=raw.url)
            saved += imgs
            self._progress(article_id, f"图片下载完成（入库 {len(imgs)} 张）")
        vids = getattr(raw, "videos", None) or []
        dl_count = 0
        for v in vids:
            url = v.url if hasattr(v, "url") else str(v)
            if "readtemplate" in url or (hasattr(v, "vid") and v.vid.startswith("wxv_")):
                # wxv_ 视频号：降级为「链接 + 封面」素材；重收时按来源链接去重
                dup = next((m for m in dao.list_materials(
                    scope="article", article_id=article_id, kind="video")
                    if m.get("source_url") == url), None)
                if dup:
                    link_mid = dup["id"]
                else:
                    link_mid = dao.insert_material(
                        scope="article", article_id=article_id, kind="video",
                        source_url=url, source_material_id=source_mid,
                        title=f"内嵌视频 {v.vid or ''}".strip(),
                        note="视频号内嵌视频（浏览器可播，服务端暂不取流）")
                    saved.append(link_mid)
                poster = getattr(v, "poster", "")
                if poster:
                    media_download.fetch_images(
                        [ImageRef(url=poster, alt="视频封面")],
                        scope="article", article_id=article_id,
                        source_material_id=link_mid, page_url=raw.url, limit=1)
            else:
                got = media_download.fetch_videos(
                    [v], scope="article", article_id=article_id,
                    source_material_id=source_mid, page_url=raw.url)
                saved += got
                dl_count += len(got)
        if vids:
            self._progress(article_id, f"视频抓取完成（下载 {dl_count} 个，链接素材 "
                                       f"{len(vids) - dl_count} 个）")
        if getattr(raw, "audios", None):
            saved += media_download.fetch_audios(
                raw.audios, scope="article", article_id=article_id,
                source_material_id=source_mid, page_url=raw.url)
        return saved

    def _extract_topic(self, raw: RawArticle) -> TopicExtract:
        """纯规则抽取主题/报道主体/关键词（不调 LLM，控制成本）。

        规则：标题分句 ×3 + 英文/型号 token + 「」引号词 + 实体词典，
        核心句取「含数字+含关键词」高分句（services/textmine.py）。"""
        from ..services.textmine import extract_topic_rules
        g = extract_topic_rules(raw.title, raw.markdown[:12000])
        return TopicExtract(topic=g.topic, keywords=g.keywords,
                            core_points=g.core_points, entities=g.entities,
                            foundational_queries=g.foundational_queries)

    def _search_and_fetch_refs(self, article_id: str, raw: RawArticle,
                               extract: TopicExtract) -> list[tuple[str, str, str]]:
        """网络搜索 + arXiv 论文两路并集，目标凑齐 min~max 篇。返回 [(mid, ref_type, url)]。"""
        web = get_searcher()
        window = int(config.get("collect.search_window_days", 3))
        ref_min, ref_max = (int(config.get("collect.ref_count.min", 3)),
                            int(config.get("collect.ref_count.max", 5)))
        out: list[tuple[str, str, str]] = []
        seen_urls = {raw.url}

        # 相关性守卫：标题+摘要须命中任一关键词/实体 token（防无关结果入库）
        tokens = {t.lower() for t in
                  (extract.keywords + extract.entities + [extract.topic]) if t and len(t) >= 2}
        tokens |= {w.lower() for t in tokens for w in t.split() if len(w) >= 2}

        def _relevant(results):
            if not tokens:
                return results
            kept = []
            for r in results:
                hay = (r.title + " " + (r.snippet or "")).lower()
                if any(t in hay for t in tokens):
                    kept.append(r)
            return kept

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
            _take(_relevant(web.search(q, max_results=6, days_window=window)),
                  RefType.REFERENCE, ref_max)

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
        # 持久去重：素材库已有同源文章则复用（跨收集运行有效）
        dup = next((m for m in dao.list_materials(article_id=article_id, kind="text")
                    if m.get("source_url") == url), None)
        if dup:
            return dup["id"]
        try:
            raw = crawl_registry.fetch(url)
        except CrawlError:
            dao.insert_material(scope="article", article_id=article_id, kind="link",
                                source_url=url, ref_type=ref_type.value,
                                fetch_status="fetch_error", title=url)
            return None
        self._progress(article_id, f"爬取参考【{raw.title or url}】")
        folder = library.save_ref_snapshot(article_id, "", raw.html or "", raw.markdown,
                                           {"url": url, "title": raw.title,
                                            "published_at": raw.published_at})
        mid = library.ingest_text(raw.markdown, title=raw.title or url, scope="article",
                                  article_id=article_id, source_url=url,
                                  ref_type=ref_type.value,
                                  meta={"site": raw.site, "published_at": raw.published_at},
                                  folder=folder)
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
