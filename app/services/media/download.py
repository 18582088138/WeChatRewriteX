"""媒体下载：防盗链 Referer 规则 + 并发控制 + 摄取入库。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import httpx

from ...core import config
from ...storage import library
from ..crawl.base import ImageRef

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 防盗链 Referer 规则: host 关键字 → Referer
_REFERER_RULES = {
    "mmbiz.qpic.cn": "https://mp.weixin.qq.com/",
    "qpic.cn": "https://mp.weixin.qq.com/",
    "sinaimg.cn": "https://weibo.com/",
    "xhscdn.com": "https://www.xiaohongshu.com/",
    "bilibili.com": "https://www.bilibili.com/",
    "hdslb.com": "https://www.bilibili.com/",
}


def referer_for(url: str, fallback: str | None = None) -> str:
    host = urlparse(url).netloc
    for key, ref in _REFERER_RULES.items():
        if key in host:
            return ref
    return fallback or f"{urlparse(url).scheme}://{host}/"


def download_file(url: str, referer: str | None = None, timeout: float = 30) -> bytes:
    headers = {"User-Agent": UA, "Referer": referer_for(url, referer)}
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.content


def fetch_images(images: list[ImageRef], scope: str, article_id: str | None,
                 source_material_id: str | None, page_url: str,
                 limit: int = 20) -> list[str]:
    """并发下载图片并摄取入库，返回 material_id 列表（失败的跳过）。"""
    from .watermark import check_image_heuristic

    min_w = int(config.get("collect.image_min_width", 400))
    workers = int(config.get("pipeline.concurrency.download", 4))
    saved: list[str] = []

    def _one(ref: ImageRef) -> str | None:
        try:
            data = download_file(ref.url, referer=page_url)
        except Exception:
            return None
        mid, _created = library.ingest_bytes(
            data, filename=ref.url.split("?")[0].rsplit("/", 1)[-1] or "image",
            scope=scope, article_id=article_id, source_url=ref.url,
            source_material_id=source_material_id, kind="image", title=ref.alt)
        from ...storage import dao, db as _db
        m = dao.get_material(mid)
        if m and m.get("width") and m["width"] < min_w:
            # 过小图片标记不可用但不删除文件，保留追溯
            _db.execute("UPDATE materials SET fetch_status='too_small' WHERE id=?", (mid,))
            return None
        wm = check_image_heuristic(mid, ref.url)
        if wm is not None:
            _db.execute("UPDATE materials SET watermark=? WHERE id=?", (wm, mid))
        return mid

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for mid in ex.map(_one, images[:limit]):
            if mid:
                saved.append(mid)
    return saved
