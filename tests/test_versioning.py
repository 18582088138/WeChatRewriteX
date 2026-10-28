"""块级增量版本（类 Git）专项：checkpoint 稀疏 + 变更日志 + 版本重建 + 一键回滚。"""
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


def test_incremental_versions_and_rollback():
    aid = _mk_article()["id"]
    # v1 checkpoint
    doc = draft_service.save_new_version(_v1_doc(aid), origin="agent", checkpoint=True)
    assert doc.version == 1

    # v2: 改一段（只记差异，不写新快照）
    d2, _ = draft_service.get_doc(aid)
    draft_service.apply_ops(d2, [{"op": "update", "block_id": "b2",
                                  "text": "第一段改过的内容"}])
    draft_service.save_new_version(d2, origin="human")
    # drafts 表仍只有 v1 一个 checkpoint
    assert len(dao.list_drafts(aid)) == 1
    # 变更日志记了一条 update
    changes = dao.changes_after(aid, 1)
    block_changes = [c for c in changes if c["block_id"] != "__meta__"]
    assert len(block_changes) == 1 and block_changes[0]["op"] == "update" and block_changes[0]["block_id"] == "b2"

    # HEAD 已是新文本；v1 重建仍是原文
    head = DraftDoc.model_validate_json(dao.latest_draft(aid)["doc_json"])
    assert any(b.text == "第一段改过的内容" for b in head.blocks)
    v1 = DraftDoc.model_validate_json(dao.get_draft(aid, 1)["doc_json"])
    assert any(b.text == "第一段原文" for b in v1.blocks)

    # v3: 插入新块
    d3, _ = draft_service.get_doc(aid)
    draft_service.apply_ops(d3, [{"op": "insert_after", "block_id": "b2",
                                  "block_type": "paragraph", "text": "插入的新段"}])
    draft_service.save_new_version(d3, origin="human")
    head = DraftDoc.model_validate_json(dao.latest_draft(aid)["doc_json"])
    assert len(head.blocks) == 4

    # 版本时间线含 checkpoint v1 + 两个变更组
    timeline = dao.list_draft_versions(aid)
    assert any(v["checkpoint"] and v["version"] == 1 for v in timeline)
    assert sum(1 for v in timeline if not v["checkpoint"]) == 2

    # 一键回滚到 v1 → 新 checkpoint，HEAD 回原文
    rb = draft_service.rollback(aid, 1)
    assert any(b.text == "第一段原文" for b in rb.blocks) and len(rb.blocks) == 3
    assert len(dao.list_drafts(aid)) == 2     # 新增回滚 checkpoint
    head = DraftDoc.model_validate_json(dao.latest_draft(aid)["doc_json"])
    assert any(b.text == "第一段原文" for b in head.blocks) and len(head.blocks) == 3


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
    # meta 变更也进了变更日志
    assert any(c["op"] == "meta" for c in dao.changes_after(aid, 1))
