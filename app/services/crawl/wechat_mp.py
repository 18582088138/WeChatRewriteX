"""微信公众号文章解析器。

公众号正文是静态 HTML，直接解析 #js_content 节点比通用提取器还原更准：
- 图片真实地址在 data-src（懒加载），下载需带 Referer: https://mp.weixin.qq.com/
- 发布时间在页面脚本 var ct / var createTime（unix 秒）
"""
from __future__ import annotations

import re

import httpx
from lxml import html as lxml_html

from .base import CrawlError, ImageRef, RawArticle

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_HEADING = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_BLOCK = {"p", "section", "div", "blockquote", "ul", "ol", "table", "h1", "h2", "h3",
          "h4", "h5", "h6", "img", "figure"}


def _clean(text: str) -> str:
    return re.sub(r"[​\xa0]", "", text).strip()


class WechatMpCrawler:
    name = "wechat_mp"

    def can_handle(self, url: str) -> bool:
        return "mp.weixin.qq.com" in url

    def fetch(self, url: str) -> RawArticle:
        try:
            resp = httpx.get(url, headers={"User-Agent": UA}, timeout=30, follow_redirects=True)
        except httpx.HTTPError as e:
            raise CrawlError(f"公众号文章请求失败: {e}") from e
        if resp.status_code != 200:
            raise CrawlError(f"公众号文章 HTTP {resp.status_code}")
        raw_html = resp.text
        try:
            doc = lxml_html.fromstring(raw_html)
        except Exception as e:
            raise CrawlError(f"HTML 解析失败: {e}") from e

        content = doc.xpath("//div[@id='js_content']")
        if not content:
            raise CrawlError("未找到 #js_content，可能需要微信环境或链接已失效")
        content_el = content[0]

        lines: list[str] = []
        images: list[ImageRef] = []
        _walk(content_el, lines, images)
        from ..media.filter import clean_markdown
        markdown = clean_markdown("\n\n".join(x for x in lines if x.strip()))

        title = _clean(" ".join(doc.xpath("//h1[contains(@class,'rich_media_title')]//text()")
                                or doc.xpath("//h1[@id='activity-name']//text()")))
        author = _clean(" ".join(doc.xpath("//*[@id='js_name']//text()")))
        published_at = _extract_publish_time(raw_html)
        videos, audios = _extract_media(doc, raw_html)
        return RawArticle(
            url=url, title=title, html=raw_html, markdown=markdown,
            published_at=published_at, author=author, site="微信公众号", images=images,
            videos=videos, audios=audios,
        )


def _walk(el, lines: list[str], images: list[ImageRef], depth: int = 0) -> None:
    if depth > 12:
        return
    for child in el.iterchildren():
        tag = child.tag if isinstance(child.tag, str) else ""
        tag = tag.lower()
        if tag in _HEADING:
            text = _clean(child.text_content())
            if text:
                lines.append("#" * _HEADING[tag] + " " + text)
        elif tag == "p":
            # p 内可能直接嵌 img
            imgs = child.xpath(".//img")
            for im in imgs:
                _record_img(im, images, lines)
            text = _clean(child.text_content())
            if text:
                lines.append(text)
        elif tag == "blockquote":
            text = _clean(child.text_content())
            if text:
                lines.append("> " + text.replace("\n", "\n> "))
        elif tag in ("ul", "ol"):
            for i, li in enumerate(child.xpath("./li"), 1):
                text = _clean(li.text_content())
                if text:
                    prefix = f"{i}." if tag == "ol" else "-"
                    lines.append(f"{prefix} {text}")
        elif tag == "img":
            _record_img(child, images, lines)
        elif tag in _BLOCK or tag in ("span", "a", "strong", "em", "figure", "figcaption"):
            if tag in ("span", "a", "strong", "em") and not child.xpath(".//img"):
                text = _clean(child.text_content())
                if text:
                    lines.append(text)
            else:
                _walk(child, lines, images, depth + 1)
        else:
            _walk(child, lines, images, depth + 1)


def _record_img(im, images: list[ImageRef], lines: list[str]) -> None:
    src = im.get("data-src") or im.get("src") or ""
    if not src.startswith("http"):
        return
    alt = im.get("alt") or ""
    images.append(ImageRef(url=src, alt=alt))
    lines.append(f"![{alt}]({src})")


def _extract_publish_time(raw_html: str) -> str | None:
    import datetime
    m = re.search(r"var\s+ct\s*=\s*\"?(\d{10})\"?", raw_html) or \
        re.search(r"var\s+createTime\s*=\s*[\"']([^\"']+)[\"']", raw_html)
    if not m:
        return None
    token = m.group(1)
    try:
        if token.isdigit():
            return datetime.datetime.fromtimestamp(int(token)).strftime("%Y-%m-%d %H:%M:%S")
        return token
    except (ValueError, OSError):
        return None


def _extract_media(doc, raw_html: str) -> tuple[list, list[str]]:
    """提取公众号文内视频与音频。

    视频分两类：
    - 可下载：v.qq.com/bilibili 页面、<video> 直链（yt-dlp 支持）
    - wxv_ 视频号（readtemplate 播放器）：服务端无法稳定取流 → 降级为
      「链接 + 封面」素材（封面 mmbiz 图本身即优质配图），由收集器处理
    音频：mpvoice 标签 voice_encode_fileid → res.wx.qq.com 播放地址。
    """
    from .base import VideoRef
    videos: list[VideoRef] = []
    audios: list[str] = []
    for iframe in doc.xpath("//iframe"):
        src = iframe.get("data-src") or iframe.get("src") or ""
        mpvid = iframe.get("data-mpvid") or ""
        cover = iframe.get("data-cover") or ""
        if "v.qq.com" in src or "player.bilibili.com" in src:
            videos.append(VideoRef(
                url=src if src.startswith("http") else "https:" + src.lstrip("/"),
                poster=cover, vid=mpvid))
        elif "mp/readtemplate" in src or mpvid.startswith("wxv_"):
            from urllib.parse import unquote
            vid = mpvid or (re.search(r"vid=(wxv_\d+)", src).group(1)
                            if re.search(r"vid=(wxv_\d+)", src) else "")
            poster = unquote(cover) if cover else ""
            videos.append(VideoRef(url=unquote(src) if "%" in src else src,
                                   poster=poster, vid=vid))
    for v in doc.xpath("//video"):
        src = v.get("data-src") or v.get("src") or ""
        if src.startswith("http"):
            videos.append(VideoRef(url=src, poster=v.get("poster") or ""))
        for s in v.xpath(".//source"):
            ssrc = s.get("src") or ""
            if ssrc.startswith("http"):
                videos.append(VideoRef(url=ssrc))
    # 脚本中的腾讯视频 vid → v.qq.com 页面（yt-dlp 可解析常规 vid）
    for vid in set(re.findall(r'"vid"\s*:\s*"((?!wxv_)[a-zA-Z0-9]{8,})"', raw_html)):
        videos.append(VideoRef(url=f"https://v.qq.com/x/page/{vid}.html"))
    # mpvoice 音频
    for voice in doc.xpath("//mpvoice"):
        fid = voice.get("voice_encode_fileid") or ""
        if fid:
            audios.append(f"https://res.wx.qq.com/voice/getvoice?mediaid={fid}")
    for fid in set(re.findall(r'voice_encode_fileid\s*=\s*["\']([^"\']+)["\']', raw_html)):
        audios.append(f"https://res.wx.qq.com/voice/getvoice?mediaid={fid}")
    # 按 url 去重保序
    seen, uniq = set(), []
    for v in videos:
        if v.url and v.url not in seen:
            seen.add(v.url)
            uniq.append(v)
    audios = list(dict.fromkeys(audios))
    return uniq, audios
