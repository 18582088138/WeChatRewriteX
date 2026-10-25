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

THEMES_DIR = Path(__file__).parent / "themes"


class CardRenderError(Exception):
    pass


def _load_theme(name: str) -> tuple[dict, str]:
    d = THEMES_DIR / name
    if not d.exists():
        raise CardRenderError(f"卡片主题不存在: {name}")
    theme = yaml.safe_load((d / "theme.yaml").read_text(encoding="utf-8"))
    template = (d / "theme.html").read_text(encoding="utf-8")
    return theme, template


def _cover_html(doc: DraftDoc, total: int) -> str:
    esc = html_mod.escape
    title = (doc.meta.title_candidates or ["未命名"])[0]
    today = datetime.date.today().strftime("%Y-%m-%d")
    chips = "".join(f'<span class="chip">{esc(k)}</span>' for k in doc.meta.keywords[:4])
    return (
        '<div class="page cover">'
        '<div class="cover-top">'
        '<div class="brand"><span class="brand-mark"></span>技术传火人</div>'
        f'<div class="cover-date">{today}</div>'
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


def _page_html(page, doc: DraftDoc, idx: int, total: int) -> str:
    esc = html_mod.escape
    no = f"{idx + 1:02d}"
    pageno = f'<div class="foot"><span class="logo">技术传火人 · AI 要闻解读</span>' \
             f'<span class="pageno">{no} / {total:02d}</span></div>'

    if page.asset_id:
        m = dao.get_material(page.asset_id)
        rel = (m or {}).get("path")
        p = library.material_abs_path(rel) if rel else None
        if p and p.exists():
            uri = "file:///" + str(p).replace("\\", "/")
            credit = f'图源：{esc(m.get("note") or m.get("source_url") or "素材库")}'
            cap = esc(page.title) if page.title else ""
            return (f'<div class="page imgpage"><img src="{uri}">'
                    f'<div class="capband">{cap}<div class="credit">{credit}</div>'
                    f"</div></div>")

    parts = []
    if page.title:
        parts.append(
            f'<div class="sec-head"><span class="sec-no">{no}</span>'
            f'<div class="sec-title">{esc(page.title)}</div></div>')
    body = []
    for bid in page.block_ids:
        b = bk.get_block(doc, bid)
        if not b or not b.text:
            continue
        cls = ' class="quote"' if b.type == BlockType.QUOTE else ""
        body.append(f"<p{cls}>{esc(bk.sanitize_block_text(b.text))}</p>")
    parts.append('<div class="body">' + "".join(body) + "</div>")
    parts.append(pageno)
    return '<div class="page content">' + "".join(parts) + "</div>"


def render_cards(article_id: str, theme_name: str | None = None,
                 out_dir: Path | None = None) -> list[Path]:
    draft = dao.latest_draft(article_id)
    if not draft:
        raise CardRenderError("没有草稿，无法生成卡片")
    doc = DraftDoc.model_validate_json(draft["doc_json"])
    if not doc.meta.xhs_pages:
        from ...agents.creator import CreatorAgent
        doc.meta.xhs_pages = CreatorAgent._paginate_xhs(doc)

    theme_name = theme_name or config.get("cards.theme", "tech-note")
    theme, template = _load_theme(theme_name)
    size = theme["size"]

    pages = doc.meta.xhs_pages
    total = len(pages) + 1  # +封面
    pages_html = [_cover_html(doc, total)]
    for i, pg in enumerate(pages):
        pages_html.append(_page_html(pg, doc, i + 1, total))

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

    out_dir = out_dir or (library.exports_dir(article_id) / "xhs_cards")
    out_dir.mkdir(parents=True, exist_ok=True)
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
