"""工作副本、定稿版本和历史兼容回归。"""
from __future__ import annotations

from app.core.models import Block, BlockType, DraftDoc, DraftMeta
from app.services import draft_service
from app.storage import dao


def _mk_article():
    return dao.create_article("fixture://sample_article.md")


def _v1_doc(aid: str) -> DraftDoc:
    return DraftDoc(id="", article_id=aid, version=0,
                    blocks=[Block(id="b1", type=BlockType.HEADING, level=1, text="标题甲"),
                            Block(id="b2", type=BlockType.PARAGRAPH, text="第一段原文"),
                            Block(id="b3", type=BlockType.PARAGRAPH, text="第二段原文")],
                    meta=DraftMeta(one_liner="一句话甲"))


def test_working_version_finalization_and_rollback():
    from app.core.models import ArticleStatus
    from app.services import workflow
    aid = _mk_article()["id"]
    doc = draft_service.save_new_version(_v1_doc(aid), origin="agent", checkpoint=True)
    dao.set_article_status(aid, ArticleStatus.EDITING)
    for text in ("第一次修改", "第二次修改", "第三次修改"):
        candidate, _ = draft_service.get_doc(aid)
        candidate.blocks[1].text = text
        saved = draft_service.save_new_version(candidate, "human")
        assert saved.version == 1
    assert saved.edit_revision == doc.edit_revision + 3
    assert len(dao.list_draft_versions(aid)) == 1
    assert not dao.list_drafts(aid)  # 未定稿的工作副本不是正式快照
    # 重新读取模拟刷新/重启，最新修改仍在；定稿封存当前 v1。
    reloaded, _ = draft_service.get_doc(aid)
    assert reloaded.blocks[1].text == "第三次修改"
    assert workflow.finalize(aid, force=True)["version"] == 1
    sealed = dao.get_draft_by_id(f"{aid}-v1")["doc_json"]
    next_doc, _ = draft_service.get_doc(aid)
    next_doc.blocks[1].text = "定稿后的新改动"
    next_doc = draft_service.save_new_version(next_doc, "human")
    assert next_doc.version == 2
    next_doc.blocks[2].text = "继续修改"
    assert draft_service.save_new_version(next_doc, "human").version == 2
    assert dao.get_draft_by_id(f"{aid}-v1")["doc_json"] == sealed
    rb = draft_service.rollback(aid, 1)
    assert rb.version == 2 and rb.blocks[1].text == "第三次修改"
    assert workflow.finalize(aid, force=True)["version"] == 2
    assert len(dao.list_drafts(aid)) == 2


def test_meta_change_and_title_linkage_fields():
    aid = _mk_article()["id"]
    draft_service.save_new_version(_v1_doc(aid), origin="agent", checkpoint=True)
    d, _ = draft_service.get_doc(aid)
    draft_service.apply_ops(d, [
        {"op": "update_meta", "field": "keywords", "value": ["#大模型", "#开源"]},
        {"op": "update_meta", "field": "one_liner", "value": "新总结"},
        {"op": "update_meta", "field": "title_selected", "value": "标题乙"},
    ])
    saved = draft_service.save_new_version(d, origin="human")
    assert saved.meta.keywords == ["大模型", "开源"]       # # 前缀剥离
    assert saved.meta.one_liner == "新总结"
    assert saved.meta.title_candidates[0] == "标题乙"      # 置顶
    restored, _ = draft_service.get_doc(aid)
    assert restored == saved and saved.version == 1
