"""存储层单测：DAO CRUD / 素材摄取去重 / inbox 扫描 / FTS。"""
from __future__ import annotations

from app.core.models import ArticleStatus, Block, BlockType, ChecklistItem, DraftDoc, DraftMeta
from app.storage import dao, db, library


def _mk_article() -> dict:
    return dao.create_article("fixture://sample_article.md", user_notes="测试")


def test_article_and_status():
    art = _mk_article()
    assert art["status"] == "NEW"
    dao.set_article_status(art["id"], ArticleStatus.COLLECTING)
    assert dao.get_article(art["id"])["status"] == "COLLECTING"
    assert len(dao.list_articles()) >= 1
    assert dao.list_articles(q="sample_article")


def test_material_dedup_and_fts():
    art = _mk_article()
    data1 = "这是一段关于大模型推理优化的技术文本，包含 KV Cache 与量化。".encode()
    mid1, created1 = library.ingest_bytes(data1, "a.txt", "article", art["id"], kind="text")
    dao.set_material_text(mid1, data1.decode())
    mid2, created2 = library.ingest_bytes(data1, "a-copy.txt", "article", art["id"], kind="text")
    assert created1 and not created2 and mid1 == mid2       # sha256 去重
    hits = dao.search_materials_fts("KV Cache")
    assert any(mid == mid1 for mid, _ in hits)               # FTS 或 LIKE 兜底均命中


def test_draft_version_chain_and_review():
    art = _mk_article()
    doc = DraftDoc(id="", article_id=art["id"], version=1,
                   blocks=[Block(id="b1", type=BlockType.PARAGRAPH, text="第一段内容。")],
                   meta=DraftMeta(one_liner="一句话"))
    doc.id = f"{art['id']}-v1"
    dao.save_draft(doc, origin="agent")
    doc2 = doc.model_copy(deep=True)
    doc2.version = 2
    doc2.id = f"{art['id']}-v2"
    dao.save_draft(doc2, origin="human")
    assert dao.latest_draft(art["id"])["version"] == 2
    assert [d["version"] for d in dao.list_drafts(art["id"])] == [2, 1]

    rid = dao.create_review(art["id"], doc2.id, 2,
                            [ChecklistItem(id="", category="originality", severity="blocker",
                                           message="与原文高度相似", auto_fixable=True)],
                            {"originality_max_jaccard": 0.8})
    assert dao.pending_blockers(rid) == 1
    item = dao.list_review_items(rid)[0]
    dao.set_review_item_status(item["id"], "fixed", resolved_by="ai")
    assert dao.pending_blockers(rid) == 0


def test_inbox_scan():
    art = _mk_article()
    library.ensure_dirs(art["id"])
    inbox = library.article_dir(art["id"]) / "inbox"
    (inbox / "note.txt").write_text("手动补充的参考资料内容。", encoding="utf-8")
    ingested = library.scan_inbox(art["id"])
    assert len(ingested) == 1
    assert dao.get_material_text(ingested[0]).startswith("手动补充")
