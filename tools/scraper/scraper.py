"""media-scraper 核心：抓取单篇文章的文本/图片/视频/音频到本地文件夹。

CLI 与 GUI 服务共用的核心函数；不连数据库，仅落盘。
用法: python tools/scraper/scraper.py <url> [-o outdir]
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

# 复用项目爬虫与过滤规则（把项目根加入 sys.path，独立运行）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.crawl import registry as crawl_registry  # noqa: E402
from app.services.media import filter as media_filter  # noqa: E402
from app.services.media.download import download_file  # noqa: E402
from app.services.media.video_dl import download_video  # noqa: E402

DEFAULT_OUT = Path(__file__).parent / "output"


def _safe(title: str, fallback: str = "article", limit: int = 40) -> str:
    t = re.sub(r'[\\/:*?"<>|\r\n\t]+', "", (title or "")).strip()
    return t[:limit] or fallback


def scrape(url: str, out_root: Path | None = None,
           max_images: int = 30, max_videos: int = 3, max_audios: int = 3,
           log=print) -> dict:
    raw = crawl_registry.fetch(url)
    dt = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    out_dir = (out_root or DEFAULT_OUT) / f"{_safe(raw.title or 'article')}-{dt}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("图片", "视频", "音频"):
        (out_dir / sub).mkdir(exist_ok=True)

    log(f"标题: {raw.title}")
    (out_dir / "content.md").write_text(raw.markdown, encoding="utf-8")
    if raw.html:
        (out_dir / "page.html").write_text(raw.html, encoding="utf-8")

    summary = {"title": raw.title, "url": url, "out_dir": str(out_dir),
               "text_chars": len(raw.markdown), "images": 0, "videos": 0, "audios": 0,
               "filtered": 0, "files": []}

    # ---- 图片（URL 黑名单 → 大小/尺寸/比例 → pHash 去重）----
    phashes: list[str] = []
    for ref in raw.images[:max_images]:
        if not media_filter.image_url_ok(ref.url):
            summary["filtered"] += 1
            continue
        try:
            data = download_file(ref.url, referer=raw.url)
        except Exception:
            continue
        if len(data) < media_filter.MIN_BYTES:
            summary["filtered"] += 1
            continue
        name = re.sub(r"[?#].*$", "", ref.url.rsplit("/", 1)[-1]) or "image"
        if "." not in name[-5:]:
            name += ".jpg"
        dest = out_dir / "图片" / f"{len(summary['files']):03d}-{name}"
        dest.write_bytes(data)
        w = h = None
        try:
            from PIL import Image
            with Image.open(dest) as im:
                w, h = im.width, im.height
        except Exception:
            pass
        ok, _ = media_filter.image_file_ok(w, h, len(data))
        if not ok:
            dest.unlink()
            summary["filtered"] += 1
            continue
        ph = None
        try:
            import imagehash
            from PIL import Image
            with Image.open(dest) as im:
                ph = str(imagehash.phash(im))
        except Exception:
            pass
        if ph and any(media_filter.phash_distance(ph, x) <= 6 for x in phashes):
            dest.unlink()
            summary["filtered"] += 1
            continue
        if ph:
            phashes.append(ph)
        summary["images"] += 1
        summary["files"].append(f"图片/{dest.name}")

    # ---- 视频 ----
    for v in (raw.videos or [])[:max_videos]:
        vurl = v.url if hasattr(v, "url") else str(v)
        if "readtemplate" in vurl:
            # 视频号取不到流：保存封面图 + 播放器链接到 summary
            poster = getattr(v, "poster", "")
            if poster and media_filter.image_url_ok(poster):
                try:
                    data = download_file(poster, referer=raw.url)
                    dest = out_dir / "图片" / f"poster-{len(summary['files']):03d}.jpg"
                    dest.write_bytes(data)
                    summary["images"] += 1
                    summary["files"].append(f"图片/{dest.name}")
                except Exception:
                    pass
            summary["files"].append(f"视频(在线): {vurl}")
            continue
        try:
            got = download_video(vurl) or (
                (download_file(vurl, referer=raw.url, timeout=120),
                 vurl.split("?")[0].rsplit("/", 1)[-1] or "video.mp4")
                if vurl.lower().split("?")[0].endswith((".mp4", ".mov", ".webm")) else None)
            if not got:
                continue
            data, fname = got
            dest = out_dir / "视频" / fname
            dest.write_bytes(data)
            summary["videos"] += 1
            summary["files"].append(f"视频/{dest.name}")
        except Exception:
            continue

    # ---- 音频 ----
    for aurl in (raw.audios or [])[:max_audios]:
        try:
            data = download_file(aurl, referer=raw.url, timeout=60)
        except Exception:
            continue
        if len(data) < 1024:
            continue
        ext = ".mp3" if "." not in aurl[-6:] else "." + aurl.split("?")[0].rsplit(".", 1)[-1]
        dest = out_dir / "音频" / f"audio-{summary['audios']}{ext}"
        dest.write_bytes(data)
        summary["audios"] += 1
        summary["files"].append(f"音频/{dest.name}")

    (out_dir / "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"完成: 图 {summary['images']} 视频 {summary['videos']} 音频 {summary['audios']} "
        f"过滤 {summary['filtered']} → {out_dir}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="media-scraper 单篇素材抓取")
    parser.add_argument("url")
    parser.add_argument("-o", "--out", default=None, help="输出根目录（默认 tools/scraper/output）")
    args = parser.parse_args()
    summary = scrape(args.url, Path(args.out) if args.out else None)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
