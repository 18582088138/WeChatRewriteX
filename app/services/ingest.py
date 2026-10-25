"""摄取服务：单链接入库 / 重抓 / 批量（供 API 与 ingest 任务复用）。"""
from __future__ import annotations

from ..storage import dao, db, library
from ..services.crawl import registry as crawl_registry
from ..services.crawl.base import CrawlError
from ..services.media import download as media_download


def ingest_url(article_id: str, url: str, ref_type: str | None = None) -> dict:
    """抓取一个链接：正文 + 前 5 图 + 视频/音频入库。返回摘要。

    去重（反馈 四.3）：同项目已有同源链接素材直接返回既有 id，不重复抓取入库。"""
    from ..storage import dao as _dao
    dup = next((m for m in _dao.list_materials(scope="article", article_id=article_id)
                if m.get("source_url") == url and m["kind"] == "text"), None)
    if dup:
        return {"material_id": dup["id"], "title": dup.get("title"),
                "media": 0, "skipped": True}
    raw = crawl_registry.fetch(url)  # CrawlError 由调用方处理
    folder = library.save_ref_snapshot(article_id, "", raw.html or "", raw.markdown,
                                       {"url": url, "title": raw.title,
                                        "published_at": raw.published_at})
    mid = library.ingest_text(raw.markdown, title=raw.title or url, scope="article",
                              article_id=article_id, source_url=url,
                              ref_type=ref_type or "reference",
                              meta={"site": raw.site, "published_at": raw.published_at},
                              folder=folder)
    saved = media_download.fetch_images(raw.images[:5], scope="article",
                                        article_id=article_id, source_material_id=mid,
                                        page_url=url)
    if getattr(raw, "videos", None):
        saved += media_download.fetch_videos(raw.videos, scope="article",
                                             article_id=article_id,
                                             source_material_id=mid, page_url=url)
    if getattr(raw, "audios", None):
        saved += media_download.fetch_audios(raw.audios, scope="article",
                                             article_id=article_id,
                                             source_material_id=mid, page_url=url)
    return {"material_id": mid, "title": raw.title, "media": len(saved)}


def recrawl(material_id: str) -> dict:
    """单链接重抓：更新正文与标题，并补充抓取媒体（不删除旧媒体）。"""
    m = dao.get_material(material_id)
    if not m or not m.get("source_url"):
        raise CrawlError("该素材没有来源链接，无法重抓")
    url = m["source_url"]
    raw = crawl_registry.fetch(url)
    dao.set_material_text(material_id, raw.markdown)
    db.execute("UPDATE materials SET title=?, fetch_status='ok' WHERE id=?",
               (raw.title or m.get("title") or url, material_id))
    saved = media_download.fetch_images(raw.images[:5], scope="article",
                                        article_id=m["article_id"],
                                        source_material_id=material_id, page_url=url)
    if getattr(raw, "videos", None):
        saved += media_download.fetch_videos(raw.videos, scope="article",
                                             article_id=m["article_id"],
                                             source_material_id=material_id, page_url=url)
    return {"material_id": material_id, "title": raw.title, "media_added": len(saved)}
