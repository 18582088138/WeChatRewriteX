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
        markdown = "\n\n".join(x for x in lines if x.strip())

        title = _clean(" ".join(doc.xpath("//h1[contains(@class,'rich_media_title')]//text()")
                                or doc.xpath("//h1[@id='activity-name']//text()")))
        author = _clean(" ".join(doc.xpath("//*[@id='js_name']//text()")))
        published_at = _extract_publish_time(raw_html)
        return RawArticle(
            url=url, title=title, html=raw_html, markdown=markdown,
            published_at=published_at, author=author, site="微信公众号", images=images,
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
