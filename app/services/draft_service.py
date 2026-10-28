"""草稿版本服务（块级增量版本，类 Git）：

- drafts 表只存**稀疏 checkpoint**（创建 v1 / 定稿 / 回滚点），不再是每版全量备份；
- 每次编辑只往 draft_changes 记**变更块的差异**（old/new 块快照 + meta diff）；
- 当前稿 HEAD = 最近 checkpoint + 后续变更重放（dao.latest_draft 透明处理）；
- 任意版本可重建（get_draft(aid, version)），回滚 = 重建目标态存为新 checkpoint。
"""
from __future__ import annotations

import json

from ..core import blocks as bk
from ..core import config, events
from ..core.models import Block, BlockType, DraftDoc
from ..storage import dao, library


def resolve_head_row(draft_id: str) -> dict | None:
    """把前端持有的 draft id 解析为当前 HEAD 行。

    增量版本下，编辑后的 HEAD 不一定是 drafts 实体行（v2+ 只记在变更日志），
    所以先按 id 精确查，查不到则按 `<article_id>-vN` 形态回退到该文章 HEAD
    （修复「编辑后提示草稿不存在」——前端拿到的是上一版编号而非实体 id）。
    """
    row = dao.get_draft_by_id(draft_id)
    if row:
        return row
    if "-v" in draft_id:
        aid = draft_id.rsplit("-v", 1)[0]
        return dao.latest_draft(aid)
    return None


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
    old_meta = old.meta.model_dump(exclude={"xhs_pages"})
    new_meta = new.meta.model_dump(exclude={"xhs_pages"})
    if old_meta != new_meta:
        changes.append({"block_id": "__meta__", "op": "meta",
                        "old": json.dumps(old_meta, ensure_ascii=False),
                        "new": json.dumps(new_meta, ensure_ascii=False)})
    return changes


def save_named_version(article_id: str, note: str = "") -> DraftDoc:
    """【保存版本】（V1.4 主动保存模式）：当前 HEAD 落为命名版本，进可回滚列表。"""
    head = dao.latest_draft(article_id)
    if not head:
        raise ValueError("没有草稿")
    doc = DraftDoc.model_validate_json(head["doc_json"])
    doc.version = dao.next_version(article_id)
    doc.id = f"{article_id}-v{doc.version}"
    row = dao.save_draft(doc, origin="manual", note=note.strip())
    library.save_draft_files(doc, bk.to_markdown(doc))
    events.bus.publish(events.DRAFT_SAVED, article_id, version=doc.version,
                       origin="manual", checkpoint=True)
    return DraftDoc.model_validate_json(row["doc_json"])


def save_new_version(doc: DraftDoc, origin: str, checkpoint: bool = False,
                     note: str = "") -> DraftDoc:
    """保存：默认只记块级变更；checkpoint=True 时写稀疏全量快照（创建/定稿/回滚）。"""
    # 内容变更后小红书分页必须重算（V1.10：分页缓存随内容保鲜，
    # 审稿字数检查与卡片渲染读同一份）
    from ..agents.creator import CreatorAgent
    doc.meta.xhs_pages = CreatorAgent._paginate_xhs(doc)
    seq = dao.next_version(doc.article_id)
    head = dao.latest_draft(doc.article_id)
    if head and not checkpoint:
        old = DraftDoc.model_validate_json(head["doc_json"])
        changes = _diff_blocks(old, doc)
        for c in changes:
            dao.record_change(doc.article_id, seq, c["block_id"], c["op"],
                              c["old"], c["new"], origin)
    doc.version = seq
    doc.id = f"{doc.article_id}-v{seq}"
    doc.meta.word_count = bk.doc_word_count(doc)
    if checkpoint or not head:
        dao.save_draft(doc, origin=origin, note=note)
        library.save_draft_files(doc, bk.to_markdown(doc))   # 文件只随 checkpoint 落盘
    events.bus.publish(events.DRAFT_SAVED, doc.article_id, version=doc.version,
                       origin=origin, checkpoint=checkpoint)
    return doc


def save_checkpoint(article_id: str, origin: str, status: str = "editing",
                    note: str = "") -> DraftDoc | None:
    """把当前 HEAD 落为一个稀疏 checkpoint（定稿/手动存档用）。"""
    head = dao.latest_draft(article_id)
    if not head:
        return None
    doc = DraftDoc.model_validate_json(head["doc_json"])
    row = save_new_version(doc, origin=origin, checkpoint=True, note=note)
    dao.set_draft_status(row.id, status)
    return row


def rollback(article_id: str, target_version: int) -> DraftDoc:
    """一键回滚：重建目标版本状态并存为新 checkpoint（HEAD 立即指向它）。"""
    row = dao.get_draft(article_id, target_version)
    if not row:
        raise ValueError(f"版本 v{target_version} 不存在")
    doc = DraftDoc.model_validate_json(row["doc_json"])
    seq = dao.next_version(article_id)
    dao.record_change(article_id, seq, "__doc__", "rollback",
                      None, json.dumps({"target": target_version}), "human")
    doc.version = seq                      # checkpoint 用新序号，内容为目标态（防 UNIQUE 冲突）
    doc.id = f"{article_id}-v{seq}"
    out = dao.save_draft(doc, origin="rollback")
    out_doc = DraftDoc.model_validate_json(out["doc_json"])
    library.save_draft_files(out_doc, bk.to_markdown(out_doc))
    events.bus.publish(events.DRAFT_SAVED, article_id, version=out["version"],
                       origin="rollback", checkpoint=True)
    return out_doc


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
                    and dao.get_material(asset):
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
        queue.enqueue("review", article_id)
        return True
    return False
