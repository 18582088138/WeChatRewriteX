"""素材库媒体补充：原文配图不足时，按主题关键词检索可商用的图/视频。

渠道（用 .env 里已有的 key，缺 key 自动跳过）：
- Pexels：图片 /v1/search，视频 /videos/search
- Pixabay：图片 /api/，视频 /api/videos/
所有结果带来源链接与平台署名（发布包 README 会列出素材来源）。
"""
from __future__ import annotations

from .. import http

from ...core import config
from ...storage import dao, library
from .download import download_file

_PEXELS_IMG = "https://api.pexels.com/v1/search"
_PEXELS_VID = "https://api.pexels.com/videos/search"
_PIXABAY_IMG = "https://pixabay.com/api/"
_PIXABAY_VID = "https://pixabay.com/api/videos/"


def _pexels_images(query: str, limit: int) -> list[dict]:
    key = config.get_env("PEXELS_API_KEY")
    if not key:
        return []
    try:
        resp = http.get(_PEXELS_IMG, params={"query": query, "per_page": limit},
                         headers={"Authorization": key}, timeout=20)
        resp.raise_for_status()
        return [{"url": p["src"]["large"], "title": p.get("alt") or query,
                 "credit": f"Pexels · {p.get('photographer', '')}"}
                for p in resp.json().get("photos", [])]
    except Exception:
        return []


def _pexels_videos(query: str, limit: int) -> list[dict]:
    key = config.get_env("PEXELS_API_KEY")
    if not key:
        return []
    try:
        resp = http.get(_PEXELS_VID, params={"query": query, "per_page": limit},
                         headers={"Authorization": key}, timeout=20)
        resp.raise_for_status()
        out = []
        for v in resp.json().get("videos", []):
            files = sorted(v.get("video_files", []),
                           key=lambda f: f.get("width", 9999))
            f = files[0] if files else None
            if f and f.get("link"):
                out.append({"url": f["link"], "title": query,
                            "credit": f"Pexels · {v.get('user', {}).get('name', '')}",
                            "duration": v.get("duration")})
        return out
    except Exception:
        return []


def _pixabay_images(query: str, limit: int) -> list[dict]:
    key = config.get_env("PIXABAY_API_KEY")
    if not key:
        return []
    try:
        resp = http.get(_PIXABAY_IMG,
                         params={"key": key, "q": query, "per_page": limit,
                                 "image_type": "photo", "safesearch": "true"},
                         timeout=20)
        resp.raise_for_status()
        return [{"url": h["largeImageURL"], "title": h.get("tags") or query,
                 "credit": f"Pixabay · {h.get('user', '')}"}
                for h in resp.json().get("hits", [])]
    except Exception:
        return []


def _pixabay_videos(query: str, limit: int) -> list[dict]:
    key = config.get_env("PIXABAY_API_KEY")
    if not key:
        return []
    try:
        resp = http.get(_PIXABAY_VID,
                         params={"key": key, "q": query, "per_page": limit,
                                 "safesearch": "true"}, timeout=20)
        resp.raise_for_status()
        out = []
        for h in resp.json().get("hits", []):
            vids = h.get("videos", {})
            pick = vids.get("medium") or vids.get("small") or {}
            if pick.get("url"):
                out.append({"url": pick["url"], "title": h.get("tags") or query,
                            "credit": f"Pixabay · {h.get('user', '')}",
                            "duration": h.get("duration")})
        return out
    except Exception:
        return []


def enrich_media(article_id: str, keywords: list[str], need_images: int = 3,
                 need_videos: int = 1) -> dict:
    """为文章素材组补充可商用配图/视频。返回补充数量统计。"""
    if not keywords:
        return {"images": 0, "videos": 0}
    query = " ".join(keywords[:2])
    stats = {"images": 0, "videos": 0}

    have_images = len(dao.list_materials(scope="article", article_id=article_id,
                                         kind="image"))
    if have_images < need_images:
        want = min(6, need_images - have_images + 2)
        for item in (_pexels_images(query, want) or _pixabay_images(query, want)):
            try:
                data = download_file(item["url"])
            except Exception:
                continue
            library.ingest_bytes(
                data, filename=item["url"].rsplit("/", 1)[-1].split("?")[0] or "stock.jpg",
                scope="article", article_id=article_id, source_url=item["url"],
                kind="image", title=item["title"],
                note=f"素材库补充配图（{item['credit']}）")
            stats["images"] += 1
            if have_images + stats["images"] >= need_images:
                break

    have_videos = len(dao.list_materials(scope="article", article_id=article_id,
                                         kind="video"))
    if have_videos < need_videos:
        for item in (_pexels_videos(query, 2) or _pixabay_videos(query, 2)):
            try:
                data = download_file(item["url"], timeout=60)
            except Exception:
                continue
            if len(data) > 80 * 1024 * 1024:      # 超过 80MB 放弃
                continue
            mid, _ = library.ingest_bytes(
                data, filename=item["url"].rsplit("/", 1)[-1].split("?")[0] or "stock.mp4",
                scope="article", article_id=article_id, source_url=item["url"],
                kind="video", title=item["title"],
                note=f"素材库补充视频（{item['credit']}）")
            if item.get("duration"):
                from ...storage import db as _db
                _db.execute("UPDATE materials SET duration=? WHERE id=?",
                            (float(item["duration"]), mid))
            stats["videos"] += 1
            break
    return stats
