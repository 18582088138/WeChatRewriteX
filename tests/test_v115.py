"""V1.15 acceptance: stable working versions, review context, fixed exports, social formats."""
from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from app.core.models import ArticleStatus, Block, BlockType, DraftDoc, DraftMeta, ChecklistItem, XhsPage
from app.main import create_app
from app.services import draft_service, workflow
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


