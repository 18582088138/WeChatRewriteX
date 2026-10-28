"""Failure and concurrency regressions for architectural invariants."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest

from app.core.models import ArticleStatus, Block, BlockType, DraftDoc
from app.services import draft_service, workflow
from app.storage import dao, db


def seeded():
    aid = dao.create_article("local://regression", title="regression")["id"]
    doc = draft_service.save_new_version(DraftDoc(id="", article_id=aid, version=0,
                blocks=[Block(id="a", type=BlockType.PARAGRAPH, text="alpha"),
                        Block(id="b", type=BlockType.PARAGRAPH, text="beta")]),
                "agent", checkpoint=True)
    dao.set_article_status(aid, ArticleStatus.EDITING)
    return aid, doc


def test_replay_historical_order_and_metadata():
    aid, doc = seeded()
    doc.blocks.insert(0, Block(id="first", type=BlockType.PARAGRAPH, text="first"))
    saved = draft_service.save_new_version(doc, "human")
    row = dao.get_draft(aid, 2)
    historical = DraftDoc.model_validate_json(row["doc_json"])
    assert historical.model_dump() == saved.model_dump()
    assert row["word_count"] == historical.meta.word_count
    assert historical.blocks[0].id == "first"
    saved.blocks = list(reversed(saved.blocks))
    v3 = draft_service.save_new_version(saved, "human")
    assert DraftDoc.model_validate_json(dao.get_draft(aid, 3)["doc_json"]) == v3
    assert dao.get_draft(aid, 999) is None
    with pytest.raises(draft_service.VersionConflict):
        draft_service.resolve_head_row(f"{aid}-v1")
    assert draft_service.resolve_head_row(f"{aid}-v999") is None


def test_atomic_edit_rollback_on_partial_failure(monkeypatch):
    aid, doc = seeded()
    original = dao.record_change
    calls = 0
    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected disk failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(dao, "record_change", fail_second)
    for block in doc.blocks:
        block.text += " changed"
    with pytest.raises(RuntimeError):
        draft_service.save_new_version(doc, "human")
    assert dao.changes_after(aid, 1) == []
    assert dao.next_version(aid) == 2


def test_two_writers_only_one_wins():
    aid, doc = seeded()
    barrier = threading.Barrier(2)
    def write(text):
        candidate = doc.model_copy(deep=True)
        candidate.blocks[0].text = text
        barrier.wait()
        try:
            return draft_service.save_new_version(candidate, "human").version
        except draft_service.VersionConflict:
            return "conflict"
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(write, ("one", "two")))
    assert sorted(map(str, results)) == ["2", "conflict"]
    assert dao.next_version(aid) == 3


def test_finalization_and_all_mutations_share_validity():
    aid, doc = seeded()
    with pytest.raises(ValueError, match="尚未审稿"):
        workflow.finalize(aid)
    assert dao.next_version(aid) == 2  # rejected finalization leaves no checkpoint
    dao.create_review(aid, doc.id, doc.version, [],
                      {"content_hash": draft_service.content_hash(doc), "coverage": "full"})
    result = workflow.finalize(aid)
    assert workflow.finalize(aid)["already_finalized"]
    dao.set_article_status(aid, ArticleStatus.DONE)
    head, _ = draft_service.get_doc(aid)
    head.blocks[0].text = "AI repair"
    draft_service.save_new_version(head, "auto_fix")
    assert dao.get_article(aid)["status"] == "EDITING"
    with pytest.raises(ValueError, match="过期"):
        workflow.finalize(aid)
    forced = workflow.finalize(aid, force=True)
    assert forced["forced_reasons"]
    draft_service.rollback(aid, 1)
    assert dao.get_article(aid)["status"] == "EDITING"
    assert result["version"] < forced["version"]


def test_nested_transaction_does_not_publish_rolled_back_callbacks():
    received = []
    with db.transaction():
        db.after_commit(lambda: received.append("outer"))
        with pytest.raises(RuntimeError):
            with db.transaction():
                db.after_commit(lambda: received.append("inner"))
                raise RuntimeError()
        assert not received
    assert received == ["outer"]


def test_shared_assets_survive_archive_and_rename():
    from app.storage import library
    aid, _ = seeded()
    other, _ = seeded()
    mid, _ = library.ingest_bytes(b"shared bytes", "asset.bin", "article", aid)
    copied = library._clone_for_scope(dao.get_material(mid), "article", other, "copy")
    assert library.article_dir(aid) != library.article_dir(other)
    library.rename_to_created_title(aid, "new title")
    shared_path = library.material_abs_path(dao.get_material(copied)["path"])
    assert shared_path.read_bytes() == b"shared bytes"
    dao.archive_material(mid)
    assert shared_path.exists()
    assert not any(m["id"] == mid for m in dao.list_materials(article_id=aid))
    assert dao.get_material(mid)  # retained for historical blocks/citations
    reused, created = library.ingest_bytes(b"shared bytes", "asset.bin", "article", other)
    assert reused == copied and not created


def test_export_failure_aggregation_preserves_finalization(monkeypatch):
    from app.pipeline import queue
    from app.services.publish import exporter
    from app.services.publish.base import PushResult
    aid, doc = seeded()
    approved = workflow.finalize(aid, force=True)
    monkeypatch.setattr(exporter, "_export_one", lambda *a: (_ for _ in ()).throw(RuntimeError("disk")))
    result = queue._run_publish(aid, {"platforms": ["weibo", "x"],
                                    "snapshot_id": f"{aid}-v{approved['version']}"})
    assert result["status"] == "FAILED" and not result["ok"]
    assert dao.get_article(aid)["status"] == "FINALIZED"
    assert all(j["status"] == "failed" for j in dao.list_publish_jobs(aid))


def test_export_uses_approved_snapshot_after_edit():
    from app.services.publish.exporter import export_variants
    from pathlib import Path
    aid, doc = seeded()
    approved = workflow.finalize(aid, force=True)
    old_id = f"{aid}-v{approved['version']}"
    current, _ = draft_service.get_doc(aid)
    current.meta.one_liner = "unapproved new text"
    draft_service.save_new_version(current, "human")
    result = export_variants(aid, ["weibo"], old_id)
    output = Path(result["platforms"]["weibo"]["export_dir"])
    assert "unapproved new text" not in (output / "weibo.txt").read_text(encoding="utf-8")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["snapshot_id"] == old_id
    assert manifest["files"]["weibo.txt"]
