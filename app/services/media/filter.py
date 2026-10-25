"""纯规则的资源甄别与过滤（不调用 LLM，零成本）。

三道闸：
1. 文本清洗：剔除广告/求关注/转载声明/评论引导类行，砍掉「相关阅读/往期回顾」起的尾巴；
2. 图片规则：URL 黑名单特征 + 尺寸/比例/文件大小下限 + pHash 近似去重；
3. 段落过滤在爬虫 markdown 产出后即执行，保证入库素材干净。
"""
from __future__ import annotations

import re

# ---------- 文本垃圾 ----------

_JUNK_LINE = re.compile(
    r"点击.{0,4}(蓝字|上方|图片).{0,6}关注|关注公众号|设为星标|星标.{0,2}我们|"
    r"点亮.{0,2}【?在看】?|点赞.{0,4}(在看|转发|分享)|分享.{0,2}朋友圈|"
    r"扫码.{0,4}(关注|添加|进群)|长按.{0,2}(识别|二维码)|二维码.{0,4}关注|"
    r"加微信|微信号|商务合作|投稿邮箱|转载请联系|白名单|"
    r"版权声明|免责声明|侵权请联系|点击下方卡片|小程序.{0,4}购买|"
    r"留言.{0,4}(告诉|分享)|评论区.{0,4}(见|聊)|欢迎.{0,4}留言"
)

_JUNK_SECTION = re.compile(
    r"^(#{1,6}\s*)?(相关阅读|推荐阅读|往期回顾|热门文章|精选文章|更多精彩|"
    r"延伸阅读|为你推荐|喜欢此内容的人还喜欢|你可能还想看)[:：]?\s*$"
)


def clean_markdown(md: str) -> str:
    """剔除垃圾行并截断推荐类尾巴。保守原则：只删短行与明确的板块尾，不动正文长句。"""
    lines = md.split("\n")
    out: list[str] = []
    cut = False
    for line in lines:
        if _JUNK_SECTION.match(line.strip()):
            cut = True
            continue
        if cut:
            # 推荐区里只有遇到新的正式标题才恢复（极少见，保守不恢复）
            continue
        s = line.strip()
        if s and len(s) <= 80 and _JUNK_LINE.search(s):
            continue
        out.append(line)
    # 清理因删除产生的连续 3+ 空行
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------- 图片规则 ----------

_BAD_IMG_URL = re.compile(
    r"logo|icon|avatar|sprite|qrcode|emoji|emoticon|sticker|"
    r"ad[_-]?banner|adserv|doubleclick|track(?:ing)?pixel|pixel\.gif|"
    r"blank|spacer|loading|spinner|placeholder|default[_-]?(img|image|cover)",
    re.I,
)

MIN_W, MIN_H, MIN_BYTES = 400, 200, 12 * 1024
RATIO_MIN, RATIO_MAX = 0.2, 5.0


def image_url_ok(url: str) -> bool:
    return not _BAD_IMG_URL.search(url)


def image_file_ok(width: int | None, height: int | None, nbytes: int) -> tuple[bool, str]:
    if nbytes < MIN_BYTES:
        return False, "文件过小(图标/追踪图)"
    if width and width < MIN_W:
        return False, f"宽度过小({width}px)"
    if height and height < MIN_H:
        return False, f"高度过小({height}px)"
    if width and height:
        r = width / height
        if r < RATIO_MIN or r > RATIO_MAX:
            return False, f"比例异常({r:.2f}, 疑似横幅/广告条)"
    return True, ""


def phash_distance(ph1: str | None, ph2: str | None) -> int:
    """imagehash 十六进制串的海明距离；任一为空返回大数（不过滤）。"""
    if not ph1 or not ph2 or len(ph1) != len(ph2):
        return 999
    try:
        x = int(ph1, 16) ^ int(ph2, 16)
        return bin(x).count("1")
    except ValueError:
        return 999
