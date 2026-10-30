"""V1.18 real browser layout regression: shared font and post-image fitting."""
from PIL import Image
import pytest
from playwright.sync_api import sync_playwright

from app.core.models import Block, BlockType, DraftDoc, DraftMeta, XhsPage
from app.services.cards import render
from app.storage import dao, library


@pytest.mark.parametrize("repetitions,overflow", [(28, False), (400, True)])
def test_cards_share_body_size_after_media_load(tmp_path, monkeypatch, repetitions, overflow):
    article = dao.create_article("local://font-test", title="统一字号")
    image = tmp_path / "配图 # 1.png"
    Image.new("RGB", (1000, 160), "#cc5544").save(image)
    mid, _ = library.ingest_bytes(image.read_bytes(), image.name, "article", article["id"])
    theme, template = render._load_theme("tech-note")
    theme = {**theme, "body_font_px": 37, "min_font_px": 26}
    monkeypatch.setattr(render, "_load_theme", lambda name: (theme, template))
    doc = DraftDoc(id="", article_id=article["id"], version=1,
        blocks=[Block(id="short", type=BlockType.PARAGRAPH, text="短页正文。"),
                Block(id="quote", type=BlockType.QUOTE, text="引用正文也需保持相同字号。"),
                Block(id="dense", type=BlockType.PARAGRAPH, text="这是需要统一字号的正文内容。" * repetitions)],
        meta=DraftMeta(title_candidates=["统一字号测试"], one_liner="封面摘要使用同组正文的字号。",
            xhs_pages=[XhsPage(title="短页", block_ids=["short", "quote"]),
                       XhsPage(title="图文末页", block_ids=["dense"], asset_id=mid)]))
    output = tmp_path / "卡片 # 阅览"
    files = render.render_cards(article["id"], out_dir=output, doc=doc)
    assert len(files) == 3 and all(f.stat().st_size > 1000 for f in files)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1080, "height": 1440})
            page.goto((output / "_cards.html").as_uri())
            page.evaluate("() => window.__cardsReady")
            sizes = page.locator(".body p, .cover .one-liner").evaluate_all(
                "nodes => nodes.map(n => parseFloat(getComputedStyle(n).fontSize))")
            assert len(set(sizes)) == 1
            assert 26 <= sizes[0] < 37  # dense page must reduce the short page too
            assert page.locator(".fig img").evaluate("image => image.complete && image.naturalWidth === 1000")
            actual_overflow = page.locator(".body").evaluate_all(
                "nodes => nodes.some(n => n.scrollHeight > n.clientHeight)")
            assert actual_overflow == overflow
            if overflow:
                assert sizes[0] == 26
        finally:
            browser.close()
    assert (output / "_overflow_warning.txt").exists() == overflow
