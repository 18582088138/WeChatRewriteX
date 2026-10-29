"""V1.15 acceptance: stable working versions, review context, fixed exports, social formats."""
from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from app.core.models import ArticleStatus, Block, BlockType, DraftDoc, DraftMeta, ChecklistItem, XhsPage
from app.main import create_app
from app.services import draft_service, workflow
from app.services.publish import exporter
from app.services.publish.text_rules import weighted_length
from app.storage import dao, db, library


def seed():
    aid = dao.create_article("local://v115", title="V115验收")["id"]
    doc = draft_service.save_new_version(DraftDoc(id="", article_id=aid, version=0,
        blocks=[Block(id="a", type=BlockType.PARAGRAPH, text="第一段"),
                Block(id="b", type=BlockType.PARAGRAPH, text="第二段")],
        meta=DraftMeta(one_liner="内容摘要")), "agent")
    dao.set_article_status(aid, ArticleStatus.EDITING)
    return aid, doc


def test_continuous_repairs_and_acceptance_share_working_version(monkeypatch):
    from app.agents.creator import CreatorAgent
    from app.agents.reviewer import ReviewerAgent
    aid, doc = seed()
    monkeypatch.setattr(ReviewerAgent, "_check_layout", lambda *_: [ChecklistItem(
        id="", category="layout", severity="warn", block_id=bid,
        message="改进表达", auto_fixable=True) for bid in ("a", "b")])
    rid, _, _ = ReviewerAgent().run(aid)
    monkeypatch.setattr(CreatorAgent, "llm_available", lambda *_: True)
    def repair(self, aid, doc, bids, instruction):
        for block in doc.blocks:
            if block.id in bids:
                block.text += " 已修复"
        return doc
    monkeypatch.setattr(CreatorAgent, "regenerate_blocks", repair)
    items = dao.list_review_items(rid)
    with TestClient(create_app(start_worker=False)) as client:
        for item in items:
            head, _ = draft_service.get_doc(aid)
            response = client.post(f"/api/review-items/{item['id']}/resolve", json={
                "action": "fix", "expected_revision": head.edit_revision})
            assert response.status_code == 200, response.text
            assert response.json()["new_version"] == 1
            assert client.get(f"/api/articles/{aid}/reviews/latest").json()["current"]
        head, _ = draft_service.get_doc(aid)
        assert all(b.text.endswith("已修复") for b in head.blocks)
        # Same-version stale UI requests still receive 409; they cannot overwrite repairs.
        stale = client.put(f"/api/drafts/{head.id}/edit", json={"expected_revision": doc.edit_revision,
            "ops": [{"op": "update", "block_id": "a", "text": "旧窗口"}]})
        assert stale.status_code == 409
        result = client.post(f"/api/articles/{aid}/finalize", json={
            "expected_version": 1, "expected_revision": head.edit_revision})
        assert result.status_code == 200 and result.json()["version"] == 1
        sealed, _ = draft_service.get_doc(aid)
        edited = client.put(f"/api/drafts/{sealed.id}/edit", json={"expected_revision": sealed.edit_revision,
            "ops": [{"op": "update", "block_id": "a", "text": "下一版"}]})
        assert edited.json()["version"] == 2
        assert client.get(f"/api/articles/{aid}/draft").json()["draft"]["version"] == 2
        old = client.post(f"/api/review-items/{items[0]['id']}/resolve", json={"action": "accept"})
        assert old.status_code == 409


def test_late_same_version_review_is_not_actionable(monkeypatch):
    from app.agents.reviewer import ReviewerAgent
    aid, doc = seed()
    reviewer = ReviewerAgent()
    snapshot = dao.latest_draft(aid)
    doc.blocks[0].text = "审稿期间修改"
    draft_service.save_new_version(doc, "human")
    _, _, scores = reviewer.run(aid, snapshot)
    assert scores["stale"]
    assert not workflow.review_matches(dao.latest_review(aid), draft_service.get_doc(aid)[0])


def test_export_survives_title_rename_and_missing_directory(monkeypatch):
    aid, doc = seed()
    mid, _ = library.ingest_bytes(b"image bytes", "image.png", "article", aid)
    doc.blocks.append(Block(id="image", type=BlockType.IMAGE, asset_id=mid))
    draft_service.save_new_version(doc, "human")
    original = exporter._export_one
    def rename_during_export(doc, aid, platform, root):
        library.rename_to_created_title(aid, "生成期间改名")
        return original(doc, aid, platform, root)
    monkeypatch.setattr(exporter, "_export_one", rename_during_export)
    result = exporter.export_variants(aid, ["wechat_mp"])
    assert result["ok"], result
    directory = library.exports_dir(aid) / "wechat_mp"
    assert (directory / "article.html").exists()
    assert not (library.exports_dir(aid) / "runs").exists()
    assert not (directory / "snapshot.json").exists()
    assert len(list((directory / "media").glob("mat_*.png"))) == 1
    from app.services.file_access import recorded_file
    path = (directory / "article.html").relative_to(library.library_root()).as_posix()
    assert recorded_file(path) == (directory / "article.html").resolve()
    # Fixed packages remain discoverable after a later directory rename.
    library.rename_to_created_title(aid, "再次改名")
    path = (library.exports_dir(aid) / "wechat_mp" / "article.html").relative_to(library.library_root()).as_posix()
    assert recorded_file(path).is_file()


def test_failed_replace_keeps_previous_complete_files(monkeypatch):
    aid, doc = seed()
    first = exporter.export_variants(aid, ["weibo"])
    directory = Path(first["export_root"]) / "weibo"
    before = (directory / "weibo.txt").read_bytes()
    original = Path.rename
    def fail_install(self, target):
        if self.parent.parent.name == ".export-staging" and self.name == "weibo":
            raise FileNotFoundError(3, "模拟 WinError 3 安装失败")
        return original(self, target)
    monkeypatch.setattr(Path, "rename", fail_install)
    doc.meta.one_liner = "不应覆盖旧文件"
    draft_service.save_new_version(doc, "human")
    result = exporter.export_variants(aid, ["weibo"])
    assert not result["ok"] and "路径不可用" in result["platforms"]["weibo"]["message"]
    assert (directory / "weibo.txt").read_bytes() == before
    with TestClient(create_app(start_worker=False)) as client:
        files = client.get(f"/api/articles/{aid}/exports").json()["files"]
        assert any(p.endswith("weibo.txt") for p in files)
        assert client.get("/files/" + next(p for p in files if p.endswith("weibo.txt"))).status_code == 200


def test_x_chinese_urls_thread_mapping_and_weibo_final_length():
    aid, doc = seed()
    doc.blocks[0].text = ("中文与 ASCII 混排。" * 80) + " https://example.com/" + "a" * 300
    doc.meta.one_liner = "中文摘要" * 100
    doc.meta.keywords = ["完整话题", "超长话题" * 50]
    doc.meta.ref_links = [{"url": "https://example.com/source"}]
    draft_service.save_new_version(doc, "human")
    result = exporter.export_variants(aid, ["x", "weibo"])
    assert result["ok"]
    directory = Path(result["export_root"])
    thread = json.loads((directory / "x" / "thread.json").read_text(encoding="utf-8"))
    assert thread["truncated"] and len(thread["posts"]) <= 6
    for item in thread["posts"]:
        text = (directory / "x" / item["file"]).read_text(encoding="utf-8")
        assert weighted_length(text) <= 280
        assert item["reply_to_index"] == (item["index"] - 1 or None)
    assert weighted_length("中文") == 4
    assert weighted_length("https://example.com/" + "x" * 400) == 23
    assert weighted_length("e\u0301") == 1
    assert weighted_length("https://example.com。") == 25
    assert weighted_length("example.com") == 23
    wb = (directory / "weibo" / "weibo.txt").read_text(encoding="utf-8")
    assert len(wb) <= 140 and wb.count("#") % 2 == 0


def test_cards_last_page_brand_and_image_layout(monkeypatch, tmp_path):
    from app.services.cards import render
    aid, doc = seed()
    doc.meta.xhs_pages = [XhsPage(title="正文页", block_ids=["a", "b"])]
    def capture(html_path, out, size):
        text = html_path.read_text(encoding="utf-8")
        assert 'class="page closing"' not in text
        assert text.count('class="page ') == 2
        assert text.count('class="brand-footer"') == 1
        assert text.index('class="brand-footer"') > text.index("第二段")
        return []
    monkeypatch.setattr(render, "_screenshot", capture)
    render.render_cards(aid, doc=doc, out_dir=tmp_path)
    mid, _ = library.ingest_bytes(b"image", "page.png", "article", aid)
    image_html = render._page_html(XhsPage(asset_id=mid), doc, 1, 2, last=True)
    assert 'imgpage last-page' in image_html and 'brand-footer' in image_html
