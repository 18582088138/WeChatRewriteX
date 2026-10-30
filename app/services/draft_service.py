"""持久工作副本与定稿快照。编辑只递增 revision，定稿后首次修改才开版。

旧 draft_changes 历史继续可读；新工作副本保存在 SQLite，重启不丢失。
"""
from __future__ import annotations

import json

from ..core import blocks as bk
from ..core import config, events
from ..core.models import Block, BlockType, DraftDoc
from ..storage import dao, db, library


class VersionConflict(ValueError):
    """The caller's snapshot is no longer HEAD; reload before retrying."""


def content_hash(doc: DraftDoc) -> str:
    import hashlib
    payload = doc.model_dump(exclude={"id", "version", "edit_revision", "created_at"})
    # Pagination/word count are derived and may change with display configuration.
    payload["meta"].pop("word_count", None)
    payload["meta"].pop("xhs_pages", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     default=str).encode("utf-8")).hexdigest()


def resolve_head_row(draft_id: str, expected_revision: int | None = None) -> dict | None:
    from . import team
    if team.enabled() and team.actor.get() and expected_revision is None:
        from fastapi import HTTPException
        raise HTTPException(428, "需携带当前文稿 revision")
    if "-v" not in draft_id:
        return None
    aid, version = draft_id.rsplit("-v", 1)
    if not version.isdigit():
        return None
    head = dao.latest_draft(aid)
    if not head or not dao.get_draft(aid, int(version)):
        return None
    if head["version"] != int(version):
        raise VersionConflict(f"草稿已更新至 v{head['version']}，请刷新后重试")
    check_revision(DraftDoc.model_validate_json(head["doc_json"]), expected_revision)
    return head


def check_revision(doc: DraftDoc, expected_revision: int | None) -> None:
    from . import team
    if team.enabled() and team.actor.get() and expected_revision is None:
        from fastapi import HTTPException
        raise HTTPException(428, "需携带当前文稿 revision")
    if expected_revision is not None and expected_revision != doc.edit_revision:
        raise VersionConflict("当前版本的内容已更新，请刷新后重试")


def get_doc(article_id: str, version: int | None = None) -> tuple[DraftDoc, dict]:
    row = dao.get_draft(article_id, version) if version else dao.latest_draft(article_id)
    if not row:
        raise ValueError("草稿不存在")
    return DraftDoc.model_validate_json(row["doc_json"]), row


def _diff_blocks(old: DraftDoc, new: DraftDoc) -> list[dict]:
    """块级差异：update / insert / remove。insert 记录 _after 供重放定位。"""
    changes: list[dict] = []
    old_map = {b.id: b for b in old.blocks}
    new_map = {b.id: b for b in new.blocks}
    for bid, b in old_map.items():
        if bid not in new_map:
            changes.append({"block_id": bid, "op": "remove",
                            "old": b.model_dump_json(), "new": None})
    for i, b in enumerate(new.blocks):
        if b.id not in old_map:
            payload = json.loads(b.model_dump_json())
            payload["_after"] = new.blocks[i - 1].id if i > 0 else None
            changes.append({"block_id": b.id, "op": "insert",
                            "old": None, "new": json.dumps(payload, ensure_ascii=False)})
        elif old_map[b.id].model_dump() != b.model_dump():
            changes.append({"block_id": b.id, "op": "update",
                            "old": old_map[b.id].model_dump_json(),
                            "new": b.model_dump_json()})
    old_meta = old.meta.model_dump()
    new_meta = new.meta.model_dump()
    if old_meta != new_meta:
        changes.append({"block_id": "__meta__", "op": "meta",
                        "old": json.dumps(old_meta, ensure_ascii=False),
                        "new": json.dumps(new_meta, ensure_ascii=False)})
    old_order = [b.id for b in old.blocks if b.id in new_map]
    new_order = [b.id for b in new.blocks if b.id in old_map]
    if old_order != new_order:
        changes.append({"block_id": "__order__", "op": "order", "old": None,
                        "new": json.dumps([b.id for b in new.blocks])})
    return changes


def _project_checkpoint(doc: DraftDoc) -> None:
    # DB is authoritative; files can be rebuilt after an interrupted projection.
    try:
        library.save_draft_files(doc, bk.to_markdown(doc))
    except OSError:
        from .. import logging_setup
        logging_setup.log("error", "Checkpoint projection failed %s", doc.id, exc_info=True)


def save_named_version(article_id: str, note: str = "", expected_version: int | None = None,
                       expected_revision: int | None = None) -> DraftDoc:
    with db.transaction():
        doc, head = get_doc(article_id)
        check_revision(doc, expected_revision)
        return save_new_version(doc, "manual", note=note.strip(), expected_version=expected_version)


def save_new_version(doc: DraftDoc, origin: str, checkpoint: bool = False,
                     note: str = "", expected_version: int | None = None) -> DraftDoc:
    """Save working content with version + revision compare-and-swap semantics.

    AI/network work must finish before entering this short unit of work.
    """
    from ..core.pagination import paginate_xhs
    doc = doc.model_copy(deep=True)
    expected = doc.version if expected_version is None else expected_version
    doc.meta.word_count = bk.doc_word_count(doc)
    doc.meta.xhs_pages = paginate_xhs(doc, int(config.get("cards.max_chars_per_page", 300)),
                                     int(config.get("cards.image_char_cost", 150)),
                                     int((config.get("variants.xhs.pages") or [3, 9])[1]))
    with db.transaction():
        from . import team
        if team.enabled() and team.actor.get():
            team.require(doc.article_id, "write")
            for block in doc.blocks:
                for mid in ([block.asset_id] if block.asset_id else []) + list(block.citations or []):
                    material = dao.get_material(mid)
                    if not team.material_allowed(team.actor.get(), material) or (material["scope"] == "article" and material["article_id"] != doc.article_id):
                        raise ValueError("文稿素材不属于当前项目或获准公共范围")
        head = dao.latest_draft(doc.article_id)
        current = head["version"] if head else 0
        if expected != current:
            raise VersionConflict(f"草稿已更新至 v{current}，请刷新后重试")
        old = DraftDoc.model_validate_json(head["doc_json"]) if head else None
        if old:
            check_revision(old, doc.edit_revision)
        changes = _diff_blocks(old, doc) if old else []
        if head and not changes and origin != "rollback" and not (origin == "manual" and note and head["status"] != "finalized"):
            return old
        doc.version = dao.next_version(doc.article_id) if not head or head["status"] == "finalized" else current
        doc.id = f"{doc.article_id}-v{doc.version}"
        doc.edit_revision = (old.edit_revision + 1) if old else 1
        dao.save_workspace(doc, origin, note)
        if team.enabled() and not team.write_guard.get():
            db.execute("UPDATE project_access SET revision=revision+1 WHERE article_id=?", (doc.article_id,))
        team.audit("draft." + origin, doc.id, doc.article_id, {"version": doc.version, "revision": doc.edit_revision})
        if old and (content_hash(old) != content_hash(doc) or origin == "rollback"):
            # Every mutation path shares this rule, including AI repair and rollback.
            art = dao.get_article(doc.article_id)
            if art and art["status"] in ("FINALIZED", "DONE", "PUBLISHING", "REVIEWING", "REVIEWED"):
                from ..core.models import ArticleStatus
                dao.set_article_status(doc.article_id, ArticleStatus.EDITING)
                db.after_commit(lambda: events.bus.publish(events.STATUS_CHANGED, doc.article_id,
                                                          status="EDITING"))
        db.after_commit(lambda: events.bus.publish(events.DRAFT_SAVED, doc.article_id,
                        version=doc.version, origin=origin, checkpoint=checkpoint))
    return doc


def save_checkpoint(article_id: str, origin: str, status: str = "editing",
                    note: str = "") -> DraftDoc | None:
    with db.transaction():
        head = dao.latest_draft(article_id)
        if not head:
            return None
        doc = DraftDoc.model_validate_json(head["doc_json"])
        if head["status"] == "finalized":
            return doc
        # Sealing changes the concurrency token but keeps the user's version.
        doc.edit_revision += 1
        dao.seal_workspace(doc, origin, status, note)
        db.after_commit(lambda: _project_checkpoint(doc))
        return doc


def rollback(article_id: str, target_version: int, expected_version: int | None = None,
             expected_revision: int | None = None) -> DraftDoc:
    with db.transaction():
        head = dao.latest_draft(article_id)
        row = dao.get_draft(article_id, target_version)
        if not row or not head:
            raise ValueError(f"版本 v{target_version} 不存在")
        doc = DraftDoc.model_validate_json(row["doc_json"])
        doc.version = head["version"]
        current = DraftDoc.model_validate_json(head["doc_json"])
        check_revision(current, expected_revision)
        doc.edit_revision = current.edit_revision
        return save_new_version(doc, "rollback", checkpoint=True,
                                note=f"回滚到 v{target_version}", expected_version=expected_version)


def _editable_asset(doc: DraftDoc, mid: str) -> bool:
    material = dao.get_material(mid)
    return bool(material and not material.get("deleted_at") and
                (material["scope"] == "common" or material.get("article_id") == doc.article_id))


def apply_ops(doc: DraftDoc, ops: list[dict]) -> int:
    """应用编辑操作，返回改动计数。op: update|remove|replace_image|set_caption|update_meta|insert_after。"""
    changed = 0
    for op in ops:
        kind = op.get("op", "update")
        bid = op.get("block_id", "")
        if kind == "update" and op.get("text") is not None:
            changed += 1 if bk.replace_block_text(doc, bid, str(op["text"])) else 0
        elif kind == "remove":
            changed += 1 if bk.remove_block(doc, bid) else 0
        elif kind == "replace_image":
            b = bk.get_block(doc, bid)
            asset = op.get("asset_id")
            if b and b.type in (BlockType.IMAGE, BlockType.VIDEO) and asset \
                    and _editable_asset(doc, asset):
                b.asset_id = asset
                changed += 1
        elif kind == "set_caption":
            b = bk.get_block(doc, bid)
            if b and b.type in (BlockType.IMAGE, BlockType.VIDEO):
                b.caption = op.get("caption") or ""
                changed += 1
        elif kind == "insert_after":
            nb = Block(id=bk.new_block_id(), type=BlockType(op.get("block_type", "paragraph")),
                       text=str(op.get("text", "")),
                       asset_id=op.get("asset_id"), caption=op.get("caption"))
            if bid and not bk.get_block(doc, bid):
                raise ValueError("插入位置不存在")
            if nb.type in (BlockType.IMAGE, BlockType.VIDEO) and not _editable_asset(doc, nb.asset_id or ""):
                raise ValueError("素材不存在")
            bk.insert_block(doc, bid or None, nb)
            changed += 1
        elif kind == "update_meta":
            field, value = op.get("field"), op.get("value")
            if field == "one_liner" and isinstance(value, str):
                doc.meta.one_liner = value.strip()
                changed += 1
            elif field == "keywords" and isinstance(value, list):
                doc.meta.keywords = [str(x).strip().lstrip("#") for x in value
                                     if str(x).strip().lstrip("#")][:8]
                changed += 1
            elif field == "title_candidates" and isinstance(value, list):
                doc.meta.title_candidates = [str(x).strip() for x in value
                                             if str(x).strip()][:5]
                changed += 1
            elif field == "subtitle" and isinstance(value, str):
                doc.meta.subtitle = value.strip()
                changed += 1
            elif field == "ref_links" and isinstance(value, list):
                doc.meta.ref_links = bk.dedupe_ref_links(
                    [{"title": str(x.get("title", "")), "url": str(x.get("url", ""))}
                     for x in value if isinstance(x, dict)])[:20]
                changed += 1
            elif field == "title_selected" and isinstance(value, str):
                cands = [c for c in doc.meta.title_candidates if c != value]
                doc.meta.title_candidates = [value.strip()] + cands
                changed += 1
    return changed


def maybe_recheck(article_id: str, old: DraftDoc, new: DraftDoc) -> bool:
    """改动超过阈值时自动挂一个复审任务。返回是否触发。"""
    cfg = config.get("review.recheck_on_edit", {})
    if not cfg.get("enabled", True):
        return False
    changed, delta_pct = bk.changed_blocks(old, new)
    if changed >= int(cfg.get("min_changed_blocks", 3)) or \
            delta_pct >= float(cfg.get("min_word_delta_pct", 20)):
        from ..pipeline import queue
        queue.enqueue("review", article_id, {"draft_version": new.version,
                                             "edit_revision": new.edit_revision})
        return True
    return False
