"""品牌资产：个人 Logo 圆形徽章化 + 各平台导出统一页脚标识。

- Logo 源图放在 `config/brand/logo.png`（或 logo.jpg），随包内置；
- 卡片/导出用圆形透明徽章（源图浅色方底会与其他图片撞色，故中心方形裁切 +
  圆形蒙版透明化外缘，4x 超采样抗锯齿），缓存在 resource/brand/logo-badge.png，
  源图更新后自动重建；
- 固定文案 SLOGAN 用于卡片首尾页与各平台导出末尾。
"""
from __future__ import annotations

from pathlib import Path

from ..core import config

SLOGAN = "传火，让科技薪火相传"
BRAND = "传火"
BADGE_SIZE = 512          # 徽章输出边长（渲染缩放由使用方控制）


def logo_source() -> Path | None:
    for name in ("logo.png", "logo.jpg", "logo.jpeg", "logo.webp"):
        p = config.CONFIG_DIR / "brand" / name
        if p.is_file():
            return p
    return None


def badge_path() -> Path | None:
    """圆形透明徽章 PNG（缓存于数据根 brand/，源图更新自动重建）。源缺失返回 None。"""
    src = logo_source()
    if not src:
        return None
    out = config.data_dir() / "brand" / "logo-badge.png"
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    _circle_badge(src, out)
    return out


def _circle_badge(src: Path, dst: Path) -> None:
    """中心方形裁切 + 圆形蒙版（4% 内缩保留环形描边），外缘透明。"""
    from PIL import Image, ImageDraw

    im = Image.open(src).convert("RGBA")
    side = min(im.width, im.height)
    im = im.crop(((im.width - side) // 2, (im.height - side) // 2,
                  (im.width + side) // 2, (im.height + side) // 2))
    im = im.resize((BADGE_SIZE, BADGE_SIZE), Image.LANCZOS)

    ss = 4                                     # 超采样抗锯齿
    big = BADGE_SIZE * ss
    mask = Image.new("L", (big, big), 0)
    inset = int(big * 0.02)                    # 微内缩，保住外圈描边不吃边
    ImageDraw.Draw(mask).ellipse([inset, inset, big - inset, big - inset], fill=255)
    mask = mask.resize((BADGE_SIZE, BADGE_SIZE), Image.LANCZOS)

    im.putalpha(mask)
    im.save(dst, "PNG")


def badge_data_uri() -> str | None:
    """卡片 HTML 内嵌用（Playwright file:// 也可读，data URI 更稳）。"""
    import base64
    p = badge_path()
    if not p:
        return None
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
