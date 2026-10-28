"""媒体下载：防盗链 Referer 规则 + 并发控制 + 纯规则过滤 + 摄取入库。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from ...core import config
from ...storage import library
from ..crawl.base import ImageRef
from . import filter as media_filter
from .. import http

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
    limit = int(config.get("storage.material_size_limit_mb", 500)) * 1024 * 1024
    resp = http.get(url, headers=headers, timeout=timeout, follow_redirects=True,
                    untrusted=True, max_bytes=limit)
    resp.raise_for_status()
    return resp.content


def fetch_images(images: list[ImageRef], scope: str, article_id: str | None,
                 source_material_id: str | None, page_url: str,
                 limit: int = 20) -> list[str]:
    """并发下载图片：URL 黑名单 → 内容规则（尺寸/比例/大小）→ pHash 近似去重 → 入库。

    被过滤的直接不入库（素材库保持干净），返回入库 material_id 列表。
    """
    from .watermark import check_image_heuristic

    workers = int(config.get("pipeline.concurrency.download", 4))
    saved: list[str] = []

    def _one(ref: ImageRef) -> str | None:
        if not media_filter.image_url_ok(ref.url):
            return None
        try:
            data = download_file(ref.url, referer=page_url)
        except Exception:
            return None
        if len(data) < media_filter.MIN_BYTES:
            return None
        mid, created = library.ingest_bytes(
            data, filename=ref.url.split("?")[0].rsplit("/", 1)[-1] or "image",
            scope=scope, article_id=article_id, source_url=ref.url,
            source_material_id=source_material_id, kind="image", title=ref.alt)
        if not created:
            return None
        from ...storage import dao, db as _db
        m = dao.get_material(mid)
        ok, _reason = media_filter.image_file_ok(m.get("width"), m.get("height"), len(data))
        if not ok:
            # 不入库：删行删文件，保持素材库干净
            dao.archive_material(mid)
            return None
        # pHash 近似去重（与本项目已入库图比对）
        if m.get("phash"):
            for other in dao.list_materials(scope="article", article_id=article_id, kind="image"):
                if other["id"] != mid and other.get("phash") and \
                        media_filter.phash_distance(m["phash"], other["phash"]) <= 6:
                    dao.archive_material(mid)
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


def fetch_videos(entries: list, scope: str, article_id: str | None,
                 source_material_id: str | None, page_url: str,
                 limit: int = 3) -> list[str]:
    """下载文内视频（yt-dlp 解析 v.qq/bilibili/直链）。

    entries 为 VideoRef 列表。readtemplate/wxv_ 播放器页已知服务端无法取流，
    直接跳过（由收集器降级为链接+封面素材），避免慢速失败。
    """
    from .video_dl import download_video
    saved: list[str] = []
    count = 0
    for v in entries:
        if count >= limit:
            break
        url = v.url if hasattr(v, "url") else str(v)
        if "mp/readtemplate" in url or "readtemplate" in url:
            continue
        try:
            if url.lower().split("?")[0].endswith((".mp4", ".mov", ".webm")):
                data = download_file(url, referer=page_url, timeout=120)
                fname = url.split("?")[0].rsplit("/", 1)[-1]
                # 文件头校验：防防盗链错误页落盘（公众号签名直链尤其需要）
                from ..crawl.wechat_video import looks_like_video
                if not looks_like_video(data):
                    continue
                got = (data, fname)
            else:
                got = download_video(url)
            if not got:
                continue
            data, fname = got
            # 文件命名标题：优先来源文章标题（供「idx-类型-标题」规则取前 5~8 字）
            src_title = f"视频 · {urlparse(url).netloc}"
            if source_material_id:
                from ...storage import dao as _dao
                parent = _dao.get_material(source_material_id)
                if parent and parent.get("title"):
                    src_title = parent["title"]
            mid, created = library.ingest_bytes(
                data, filename=fname, scope=scope, article_id=article_id,
                source_url=url, source_material_id=source_material_id, kind="video",
                title=src_title)
            if created:
                saved.append(mid)
                count += 1
        except Exception:
            continue
    return saved


def fetch_audios(urls: list[str], scope: str, article_id: str | None,
                 source_material_id: str | None, page_url: str,
                 limit: int = 3) -> list[str]:
    """下载文内音频（mpvoice 等直链）。"""
    saved: list[str] = []
    for url in urls[:limit]:
        try:
            data = download_file(url, referer=page_url, timeout=60)
        except Exception:
            continue
        if len(data) < 1024:      # 错误页/空响应
            continue
        ext = ".mp3"
        for cand in (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".amr"):
            if cand in url.lower():
                ext = cand
                break
        mid, created = library.ingest_bytes(
            data, filename=f"audio{ext}", scope=scope, article_id=article_id,
            source_url=url, source_material_id=source_material_id, kind="audio",
            title="音频素材")
        if created:
            saved.append(mid)
    return saved
