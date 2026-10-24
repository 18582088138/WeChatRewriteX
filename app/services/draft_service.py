"""草稿版本服务：一切修改产生新版本 + 落盘 + 触发增量复审判断。"""
from __future__ import annotations

from ..core import blocks as bk
from ..core import config, events
from ..core.models import BlockType, DraftDoc
from ..storage import dao, library


def get_doc(article_id: str, version: int | None = None) -> tuple[DraftDoc, dict]:
    row = dao.get_draft(article_id, version) if version else dao.latest_draft(article_id)
    if not row:
        raise ValueError("草稿不存在")
    return DraftDoc.model_validate_json(row["doc_json"]), row


def save_new_version(doc: DraftDoc, origin: str) -> DraftDoc:
    doc.version = dao.next_version(doc.article_id)
    doc.id = f"{doc.article_id}-v{doc.version}"
    doc.meta.word_count = bk.doc_word_count(doc)
    dao.save_draft(doc, origin=origin)
    library.save_draft_files(doc, bk.to_markdown(doc))
    events.bus.publish(events.DRAFT_SAVED, doc.article_id, version=doc.version,
                       origin=origin)
    return doc


def apply_ops(doc: DraftDoc, ops: list[dict]) -> int:
    """应用编辑操作，返回改动计数。

    op: update(块文本) | remove | replace_image | set_caption | update_meta(元信息)。
    update_meta 的 field ∈ title_selected | one_liner | keywords | title_candidates。
    """
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
        elif kind == "update_meta":
            field, value = op.get("field"), op.get("value")
            if field == "one_liner" and isinstance(value, str):
                doc.meta.one_liner = value.strip()
                changed += 1
            elif field == "keywords" and isinstance(value, list):
                doc.meta.keywords = [str(x).strip() for x in value if str(x).strip()][:8]
                changed += 1
            elif field == "title_candidates" and isinstance(value, list):
                doc.meta.title_candidates = [str(x).strip() for x in value
                                             if str(x).strip()][:5]
                changed += 1
            elif field == "title_selected" and isinstance(value, str):
                # 把选中标题挪到候选首位（发布/卡片取 [0]）
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
