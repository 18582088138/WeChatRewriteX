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


def test_replay_legacy_historical_order_and_metadata():
    aid, doc = seeded()
    # Build the old sparse-checkpoint + delta layout explicitly; upgrades keep it readable.
    db.execute("DELETE FROM draft_workspaces WHERE article_id=?", (aid,))
    dao.save_draft(doc, "agent")
    candidate = doc.model_copy(deep=True)
    candidate.blocks.insert(0, Block(id="first", type=BlockType.PARAGRAPH, text="first"))
    for change in draft_service._diff_blocks(doc, candidate):
        dao.record_change(aid, 2, change["block_id"], change["op"], change["old"], change["new"], "human")
    historical = DraftDoc.model_validate_json(dao.get_draft(aid, 2)["doc_json"])
    assert historical.blocks[0].id == "first"
    historical.blocks = list(reversed(historical.blocks))
    saved = draft_service.save_new_version(historical, "human")
    assert saved.version == 2  # Adopt the unfinalized legacy HEAD into a workspace.
    assert DraftDoc.model_validate_json(dao.get_draft(aid, 2)["doc_json"]) == saved
    assert dao.get_draft(aid, 999) is None
    with pytest.raises(draft_service.VersionConflict):
        draft_service.resolve_head_row(f"{aid}-v1")
    assert draft_service.resolve_head_row(f"{aid}-v999") is None
    assert DraftDoc.model_validate_json(dao.get_draft(aid, 1)["doc_json"]).blocks[0].id == "a"


def test_atomic_edit_rollback_on_partial_failure(monkeypatch):
    aid, doc = seeded()
    original = dao.save_workspace
    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected disk failure")
    monkeypatch.setattr(dao, "save_workspace", fail_after_write)
    doc.blocks[0].text += " changed"
    with pytest.raises(RuntimeError):
        draft_service.save_new_version(doc, "human")
    restored, _ = draft_service.get_doc(aid)
    assert restored.blocks[0].text == "alpha"
    assert restored.edit_revision == doc.edit_revision


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
    assert sorted(map(str, results)) == ["1", "conflict"]
    assert dao.next_version(aid) == 2


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


def test_late_review_cannot_reopen_finalized_content(monkeypatch):
    from app.pipeline import orchestrator
    aid, original = seeded()
    started, release = threading.Event(), threading.Event()
    class SlowReview:
        def run(self, article_id, draft):
            started.set()
            assert release.wait(5)
            doc = DraftDoc.model_validate_json(draft["doc_json"])
            scores = {"coverage": "full", "content_hash": draft_service.content_hash(doc)}
            rid = dao.create_review(article_id, doc.id, doc.version, [], scores)
            return rid, [], scores
    monkeypatch.setattr(orchestrator, "_get_agents", lambda llm=None: {"review": SlowReview()})
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(orchestrator.run_stage, "review", aid)
        assert started.wait(5)
        try:
            original.blocks[0].text = "edited while review was running"
            draft_service.save_new_version(original, "human")
            workflow.finalize(aid, force=True)
        finally:
            release.set()
        assert future.result()["stale"]
    assert dao.get_article(aid)["status"] == "FINALIZED"


def test_export_regeneration_replaces_fixed_package():
    from pathlib import Path
    from app.core.execution import context
    from app.services.publish.exporter import export_variants
    aid, _ = seeded()
    token = context.set({"job_id": "export-recovery"})
    try:
        first = export_variants(aid, ["weibo"])
        output = Path(first["platforms"]["weibo"]["export_dir"])
        mtime = (output / "weibo.txt").stat().st_mtime_ns
        second = export_variants(aid, ["weibo"])
        assert first["export_root"] == second["export_root"]
        assert (output / "weibo.txt").stat().st_mtime_ns >= mtime
        assert output.parent.name == "exports"
        assert not (output.parent / "runs").exists()
        assert second["ok"]
    finally:
        context.reset(token)


def test_historical_pages_do_not_change_after_settings_update():
    import copy
    from app.core import config
    aid, doc = seeded()
    settings = copy.deepcopy(config.all_settings())
    settings["cards"]["max_chars_per_page"] = 50
    doc.blocks[0].text = "long text " * 20
    with config.using_snapshot(settings):
        saved = draft_service.save_new_version(doc, "human")
    restored = DraftDoc.model_validate_json(dao.get_draft(aid, saved.version)["doc_json"])
    assert restored == saved


def test_publish_retry_keeps_snapshot_and_skips_successful_platforms(monkeypatch):
    from pathlib import Path
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.core import config
    from app.core.execution import context
    from app.pipeline import queue
    from app.services import assets
    from app.services.publish import exporter
    aid, _ = seeded()
    approved = workflow.finalize(aid, force=True)
    doc, row = draft_service.get_doc(aid)
    payload = {"platforms": ["weibo", "x"], "snapshot_id": row["id"],
               "assets": assets.manifest(doc), "settings": config.all_settings()}
    original = exporter._export_one
    def fail_x(doc, article_id, platform, root):
        if platform == "x":
            raise RuntimeError("injected export failure")
        return original(doc, article_id, platform, root)
    monkeypatch.setattr(exporter, "_export_one", fail_x)
    jid = dao.enqueue_job("publish", aid, payload)
    token = context.set({"job_id": jid})
    try:
        result = queue._run_publish(aid, payload)
    finally:
        context.reset(token)
    assert result["status"] == "PARTIAL_FAILED"
    with db.transaction():
        dao.fail_job(jid, "x failed")
        db.execute("UPDATE jobs SET result_json=? WHERE id=?", (json.dumps(result), jid))
    successful = Path(result["platforms"]["weibo"]["export_dir"]) / "weibo.txt"
    timestamp = successful.stat().st_mtime_ns
    doc.blocks[0].text = "unapproved edit after the failed export"
    draft_service.save_new_version(doc, "human")
    dao.set_setting("variants.x.max_tweets", 1)
    config.reload()
    try:
        with TestClient(create_app(start_worker=False)) as client:
            retry = client.post(f"/api/articles/{aid}/publish/retry", json={"platform": "x"})
            assert retry.status_code == 200, retry.text
            selected = retry.json()
            assert selected["platforms"] == ["x"]
            assert selected["snapshot_id"] == f"{aid}-v{approved['version']}"
            duplicate = client.post(f"/api/articles/{aid}/publish/retry", json={"platform": "x"})
            assert duplicate.json()["job_id"] == selected["job_id"]
            queued = db.query_one("SELECT * FROM jobs WHERE id=?", (selected["job_id"],))
            saved_payload = json.loads(queued["payload_json"])
            assert saved_payload["settings"] == payload["settings"]
            assert saved_payload["assets"] == payload["assets"]
            monkeypatch.setattr(exporter, "_export_one", original)
            token = context.set({"job_id": queued["id"]})
            try:
                retried = queue._run_publish(aid, saved_payload)
            finally:
                context.reset(token)
            dao.finish_job(queued["id"], retried)
            assert retried["ok"]
            assert list(retried["platforms"]) == ["x"]
            assert successful.stat().st_mtime_ns == timestamp
            snapshot = Path(retried["platforms"]["x"]["export_dir"]) / "thread.txt"
            assert "unapproved edit" not in snapshot.read_text(encoding="utf-8")
            assert dao.get_article(aid)["status"] == "EDITING"
            assert client.post(f"/api/articles/{aid}/publish/retry", json={"platform": "x"}).status_code == 404
    finally:
        db.execute("DELETE FROM settings WHERE key='variants.x.max_tweets'")
        config.reload()


def test_rolled_back_enqueue_has_no_visible_job_or_event():
    from app.core import events
    from app.pipeline import queue
    messages = events.bus.subscribe()
    try:
        with pytest.raises(RuntimeError):
            with db.transaction():
                jid = queue.enqueue("ingest", payload={"urls": ["https://example.com/rollback"]})
                assert messages.empty()
                raise RuntimeError("abort enqueue")
        assert not db.query_one("SELECT id FROM jobs WHERE id=?", (jid,))
        assert messages.empty()
    finally:
        events.bus.unsubscribe(messages)
