"""发布导出包单测：变体生成规则与导出目录结构（xhs 卡片依赖 Playwright，单独标记）。"""
from __future__ import annotations

import shutil

import pytest

from app.core.models import Block, BlockType, DraftDoc, DraftMeta, XhsPage
from app.services.publish.exporter import build_variant, export_variants
from app.storage import dao


def _article_with_draft() -> tuple[dict, dict]:
    art = dao.create_article("fixture://sample_article.md")
    doc = DraftDoc(
        id="", article_id=art["id"], version=1,
        blocks=[
            Block(id="b1", type=BlockType.HEADING, level=1, text="星河开源之夜"),
            Block(id="b2", type=BlockType.PARAGRAPH,
                  text="星河实验室把 StarRiver-2 的权重放了出来，Apache 2.0 可商用。"),
            Block(id="b3", type=BlockType.QUOTE, text="下一代聚焦视频理解与具身智能。"),
        ],
        meta=DraftMeta(keywords=["多模态", "开源", "MoE"],
                       one_liner="星河实验室开源 72B 多模态模型，API 价格降四成。",
                       title_candidates=["星河开源之夜", "72B 的诚意", "StarRiver-2 读解"],
                       xhs_pages=[XhsPage(title="要点", block_ids=["b2"])]),
    )
    doc.id = f"{art['id']}-v1"
    dao.save_draft(doc, origin="agent")
    return art, dao.latest_draft(art["id"])


def test_wechat_variant_html():
    art, _ = _article_with_draft()
    doc = _doc(art)
    v = build_variant(doc, "wechat_mp")
    assert "<h1" in v.body and "blockquote" in v.body
    assert "星河开源之夜" in v.title and v.extras["summary"]


def test_weibo_and_x_variants():
    art, _ = _article_with_draft()
    doc = _doc(art)
    wb = build_variant(doc, "weibo")
    assert len(wb.body) <= 160 and "#多模态#" in wb.body
    x = build_variant(doc, "x")
    tweets = x.extras["tweets"]
    assert tweets[0].startswith("1/ ") and len(tweets) <= 7


def test_export_wechat_weibo_x(tmp_path):
    art, _ = _article_with_draft()
    result = export_variants(art["id"], ["wechat_mp", "weibo", "x"])
    assert result["platforms"]["wechat_mp"]["ok"]
    assert result["platforms"]["weibo"]["ok"]
    assert result["platforms"]["x"]["ok"]
    from pathlib import Path
    root = Path(result["export_root"])
    assert (root / "wechat_mp" / "article.html").exists()
    assert (root / "weibo" / "weibo.txt").exists()
    assert (root / "x" / "thread.txt").exists()
    assert (root / "wechat_mp" / "README.txt").read_text(encoding="utf-8").startswith("平台:")


def _doc(art) -> DraftDoc:
    return DraftDoc.model_validate_json(dao.latest_draft(art["id"])["doc_json"])


def test_xhs_cards_render():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright  # noqa: F401
    art, _ = _article_with_draft()
    from pathlib import Path
    with sync_playwright() as pw:
        if not Path(pw.chromium.executable_path).exists():
            pytest.skip("Playwright Chromium is not installed")
    from app.services.cards.render import render_cards
    paths = render_cards(art["id"])
    assert len(paths) == 2                     # 封面 + 内容页，品牌不再独占尾页
    assert all(p.exists() and p.stat().st_size > 5000 for p in paths)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1440})
        page.goto((paths[0].parent / "_cards.html").as_uri())
        footer = page.locator(".content .brand-footer")
        assert footer.count() == 1
        assert footer.locator("img").count() == 1
        positions = page.evaluate("""() => {
            const body = document.querySelector('.content .body');
            const footer = document.querySelector('.content .brand-footer');
            return {bodyBottom: body.getBoundingClientRect().bottom,
                    footerTop: footer.getBoundingClientRect().top,
                    overflow: body.dataset.overflow};
        }""")
        assert positions["bodyBottom"] <= positions["footerTop"]
        assert positions["overflow"] == "0"
        browser.close()
