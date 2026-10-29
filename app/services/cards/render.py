"""卡片组图渲染：DraftDoc.xhs_pages → HTML 模板 → Playwright 逐页截图 PNG。

管线：构建页面数据 → 注入主题模板 → 无头浏览器打开 → 读取 JS 溢出校验结果
→ 逐 .page 截图。模板内 JS 自动缩字号防溢出（下限 min_font_px）。
主题为「编辑部快报」平面风格：纯色域、大字号、无渐变无阴影。
"""
from __future__ import annotations

import datetime
import html as html_mod
from pathlib import Path

import yaml

from ...core import blocks as bk
from ...core import config
from ...core.models import BlockType, DraftDoc
from ...storage import dao, library
from .. import brand, assets

THEMES_DIR = Path(__file__).parent / "themes"


class CardRenderError(Exception):
    pass


def _load_theme(name: str) -> tuple[dict, str]:
    d = (THEMES_DIR / name).resolve()
    if not d.is_relative_to(THEMES_DIR.resolve()):
        raise CardRenderError("卡片主题路径无效")
    if not d.exists():
        raise CardRenderError(f"卡片主题不存在: {name}")
    theme = yaml.safe_load((d / "theme.yaml").read_text(encoding="utf-8"))
    template = (d / "theme.html").read_text(encoding="utf-8")
    return theme, template


def _cover_html(doc: DraftDoc, total: int) -> str:
    esc = html_mod.escape
    title = (doc.meta.title_candidates or ["未命名"])[0]
    chips = "".join(f'<span class="chip">{esc(k)}</span>' for k in doc.meta.keywords[:4])
    logo = brand.badge_data_uri()
    logo_html = f'<img class="cover-logo" src="{logo}" alt="logo">' if logo else ""
    return (
        '<div class="page cover">'
        '<div class="cover-top">'
        f'<div class="brand"><span class="brand-mark"></span>{esc(brand.SLOGAN)}</div>'
        f"{logo_html}"
        "</div>"
        '<div class="cover-mid">'
        '<div class="cover-kicker">AI 要闻解读</div>'
        f"<h1>{esc(title)}</h1>"
        f'<div class="one-liner">{esc(doc.meta.one_liner)}</div>'
        "</div>"
        '<div class="cover-bottom">'
        f'<div class="chips">{chips}</div>'
        f'<div class="cover-total">共 {total} 页</div>'
        "</div></div>")


def _brand_footer() -> str:
    logo = brand.badge_data_uri()
    badge = f'<img class="brand-footer-logo" src="{logo}" alt="logo">' if logo else ""
    return ('<div class="brand-footer">' + badge +
            f'<span>{html_mod.escape(brand.SLOGAN)}</span></div>')


def _foot_title(title: str) -> str:
    """页脚标题前缀：按标题长度自适应截取前 5~8 字。"""
    t = (title or "").strip()
    n = 8 if len(t) > 12 else (6 if len(t) > 8 else len(t))
    return t[:n]


def _img_html(asset_id: str, caption: str = "") -> str:
    """正文内嵌插图（段落之间，不单独占页）。"""
    esc = html_mod.escape
    m = assets.get_material(asset_id)
    rel = (m or {}).get("path")
    p = library.material_abs_path(rel) if rel else None
    if not (p and p.exists()):
        return ""
    uri = "file:///" + str(p).replace("\\", "/")
    cap = esc(caption or (m or {}).get("title") or "")
    cap_html = f'<div class="fig-cap">{cap}</div>' if cap else ""
    return f'<figure class="fig"><img src="{uri}">{cap_html}</figure>'


def _page_html(page, doc: DraftDoc, idx: int, total: int, last: bool = False) -> str:
    esc = html_mod.escape
    no = f"{idx + 1:02d}"
    title0 = (doc.meta.title_candidates or [""])[0]
    pageno = (f'<div class="foot"><span class="logo">{esc(brand.BRAND)} · AI 要闻解读'
              f' · {esc(_foot_title(title0))}</span>'
              f'<span class="pageno">{no} / {total:02d}</span></div>')

    # 插图独占页（仅当该页没有任何文字块时兜底保留整页排版）
    if page.asset_id and not page.block_ids:
        m = assets.get_material(page.asset_id)
        rel = (m or {}).get("path")
        p = library.material_abs_path(rel) if rel else None
        if p and p.exists():
            uri = "file:///" + str(p).replace("\\", "/")
            credit_src = (m.get("note") or m.get("source_url") or "素材库")
            credit = f'图源：{esc(credit_src[:60])}'
            cap = esc(page.title) if page.title else ""
            return (f'<div class="page imgpage{" last-page" if last else ""}"><img class="page-image" src="{uri}">'
                    f'<div class="capband">{cap}<div class="credit">{credit}</div>'
                    f"</div>{_brand_footer() if last else ''}</div>")

    parts = []
    if page.title:
        parts.append(
            f'<div class="sec-head"><span class="sec-no">{no}</span>'
            f'<div class="sec-title">{esc(page.title)}</div></div>')
    body = []
    for i, bid in enumerate(page.block_ids):
        b = bk.get_block(doc, bid)
        if not b or not b.text:
            continue
        cls = ' class="quote"' if b.type == BlockType.QUOTE else ""
        body.append(f"<p{cls}>{esc(bk.sanitize_block_text(b.text))}</p>")
        # 插图内嵌：紧跟首个段落之后（多段页面视觉上居于正文中间）
        if i == 0 and page.asset_id:
            img = _img_html(page.asset_id)
            if img:
                body.append(img)
    # 页面无文字块但有插图（理论上分页器不会产生，兜底）
    if not body and page.asset_id:
        img = _img_html(page.asset_id)
        if img:
            body.append(img)
    parts.append('<div class="body">' + "".join(body) + "</div>")
    if last:
        parts.append(_brand_footer())
    parts.append(pageno)
    return '<div class="page content">' + "".join(parts) + "</div>"


def render_cards(article_id: str, theme_name: str | None = None,
                 out_dir: Path | None = None, doc: DraftDoc | None = None) -> list[Path]:
    draft = dao.latest_draft(article_id) if doc is None else {"doc_json": doc.model_dump_json()}
    if not draft:
        raise CardRenderError("没有草稿，无法生成卡片")
    doc = DraftDoc.model_validate_json(draft["doc_json"])
    if not doc.meta.xhs_pages:
        from ...core.pagination import paginate_xhs
        doc.meta.xhs_pages = paginate_xhs(doc, int(config.get("cards.max_chars_per_page", 300)),
                        int(config.get("cards.image_char_cost", 150)),
                        int((config.get("variants.xhs.pages") or [3, 9])[1]))

    theme_name = theme_name or config.get("cards.theme", "tech-note")
    theme, template = _load_theme(theme_name)
    size = theme["size"]

    pages = doc.meta.xhs_pages
    total = len(pages) + 1  # 封面 + 正文；品牌放在最后正文页底部
    pages_html = [_cover_html(doc, total)]
    for i, pg in enumerate(pages):
        pages_html.append(_page_html(pg, doc, i + 1, total, last=i == len(pages) - 1))

    html_text = (template
                 .replace("{{WIDTH}}", str(size["width"]))
                 .replace("{{HEIGHT}}", str(size["height"]))
                 .replace("{{PAD}}", str(theme.get("padding_px", 84)))
                 .replace("{{BODY}}", str(theme.get("body_font_px", 38)))
                 .replace("{{MINFONT}}", str(theme.get("min_font_px", 26)))
                 .replace("{{ACCENT}}", theme.get("accent", "#C63B24"))
                 .replace("{{INK}}", theme.get("ink", "#1B1A17"))
                 .replace("{{PAPER}}", theme.get("paper", "#FBFAF7"))
                 .replace("{{PAGES}}", "\n".join(pages_html)))

    out_dir = out_dir or (library.exports_dir(article_id) / "xhs" / "cards")
    out_dir.mkdir(parents=True, exist_ok=True)
    # Regeneration must not retain pages from a longer previous render.
    for previous in out_dir.glob("page-*.png"):
        previous.unlink()
    (out_dir / "_overflow_warning.txt").unlink(missing_ok=True)
    html_path = out_dir / "_cards.html"
    html_path.write_text(html_text, encoding="utf-8")

    return _screenshot(html_path, out_dir, size)


def _screenshot(html_path: Path, out_dir: Path, size: dict) -> list[Path]:
    from playwright.sync_api import sync_playwright

    results: list[Path] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": size["width"], "height": size["height"]})
        page.goto("file:///" + str(html_path).replace("\\", "/"))
        page.wait_for_timeout(300)
        overflow = page.evaluate(
            "Array.from(document.querySelectorAll('.page.content .body'))"
            ".map(b => b.dataset.overflow || '0')")
        count = page.locator(".page").count()
        for i in range(count):
            target = out_dir / f"page-{i + 1:02d}.png"
            page.locator(".page").nth(i).screenshot(path=str(target))
            results.append(target)
        browser.close()
    if "1" in overflow:
        # 已到最小字号仍溢出：记录告警，不阻断（人工在发布页可见）
        (out_dir / "_overflow_warning.txt").write_text(
            "部分页面在最小字号下仍溢出，建议回编辑器压缩该页文字。\n", encoding="utf-8")
    return results
