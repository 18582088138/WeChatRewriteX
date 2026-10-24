"""文档块模型操作：编辑、重生成、导出 Markdown 的统一入口。

一切对文案的修改都走这里并产生新块 id / 新版本（版本管理在 storage.drafts）。
"""
from __future__ import annotations

import re
import uuid
from typing import Iterable

from .models import Block, BlockType, DraftDoc


def new_block_id() -> str:
    return f"b_{uuid.uuid4().hex[:8]}"


def assign_block_ids(doc: DraftDoc) -> DraftDoc:
    """为缺 id 的块补齐 id（LLM 输出入库前调用）。"""
    for b in doc.blocks:
        if not b.id:
            b.id = new_block_id()
    return doc


def get_block(doc: DraftDoc, block_id: str) -> Block | None:
    for b in doc.blocks:
        if b.id == block_id:
            return b
    return None


def word_count(text: str) -> int:
    """CJK 字符 + 拉丁词计数，贴近公众号编辑器口径。"""
    cjk = len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))
    latin = len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*", text))
    return cjk + latin


def doc_word_count(doc: DraftDoc) -> int:
    return sum(word_count(b.text or "") for b in doc.blocks)


def replace_block_text(doc: DraftDoc, block_id: str, new_text: str) -> bool:
    b = get_block(doc, block_id)
    if b is None or b.type in (BlockType.IMAGE, BlockType.VIDEO, BlockType.DIVIDER):
        return False
    b.text = new_text
    return True


def insert_block(doc: DraftDoc, after_id: str | None, block: Block) -> None:
    if not block.id:
        block.id = new_block_id()
    if after_id is None:
        doc.blocks.append(block)
        return
    for i, b in enumerate(doc.blocks):
        if b.id == after_id:
            doc.blocks.insert(i + 1, block)
            return
    doc.blocks.append(block)


def remove_block(doc: DraftDoc, block_id: str) -> bool:
    for i, b in enumerate(doc.blocks):
        if b.id == block_id:
            doc.blocks.pop(i)
            return True
    return False


def iter_text_blocks(doc: DraftDoc) -> Iterable[Block]:
    return (b for b in doc.blocks if b.type in (BlockType.HEADING, BlockType.PARAGRAPH, BlockType.QUOTE))


def to_markdown(doc: DraftDoc) -> str:
    lines: list[str] = []
    for b in doc.blocks:
        if b.type == BlockType.HEADING:
            lines.append("#" * max(1, min(b.level, 6)) + " " + b.text)
        elif b.type == BlockType.PARAGRAPH:
            lines.append(b.text)
        elif b.type == BlockType.QUOTE:
            lines.append("> " + b.text.replace("\n", "\n> "))
        elif b.type == BlockType.IMAGE:
            cap = b.caption or ""
            lines.append(f"![{cap}](asset://{b.asset_id})")
            if b.source:
                lines.append(f"*图源: {b.source}*")
        elif b.type == BlockType.VIDEO:
            lines.append(f"[视频](asset://{b.asset_id})")
        elif b.type == BlockType.DIVIDER:
            lines.append("---")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def blocks_from_llm(payload: dict) -> list[Block]:
    """解析洗稿 Agent 的 JSON 输出为块列表并分配 id。

    接受结构: {"blocks": [{"type": "heading|paragraph|quote|image|divider",
    "text": ..., "level": 2, "asset_hint": "素材id或描述", "citations": [...]}]}
    """
    out: list[Block] = []
    for raw in payload.get("blocks", []):
        t = raw.get("type", "paragraph")
        try:
            bt = BlockType(t)
        except ValueError:
            bt = BlockType.PARAGRAPH
        out.append(
            Block(
                id=new_block_id(),
                type=bt,
                level=int(raw.get("level", 2)),
                text=str(raw.get("text", "")),
                asset_id=raw.get("asset_id"),
                caption=raw.get("caption"),
                source=raw.get("source"),
                citations=list(raw.get("citations", [])),
            )
        )
    return out


def changed_blocks(old: DraftDoc, new: DraftDoc) -> tuple[int, float]:
    """返回 (改动块数, 词数变化比例)，供增量复审触发判断。"""
    old_map = {b.id: b for b in old.blocks}
    changed = 0
    for b in new.blocks:
        ob = old_map.get(b.id)
        if ob is None or ob.model_dump() != b.model_dump():
            changed += 1
    changed += len(set(old_map) - {b.id for b in new.blocks})
    ow, nw = doc_word_count(old), doc_word_count(new)
    delta = abs(nw - ow) / max(ow, 1)
    return changed, delta * 100
