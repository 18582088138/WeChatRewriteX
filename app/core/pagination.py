"""Deterministic card pagination, independent of agents and storage."""
from . import blocks as bk
from .models import BlockType, DraftDoc, XhsPage

def paginate_xhs(doc: DraftDoc, max_chars: int = 300, img_cost: int = 150, max_pages: int = 9) -> list[XhsPage]:
    # 插图在卡片上的占位等价字数（46vh 高的图 ≈ 6~7 行正文）
    pages: list[XhsPage] = []
    cur = XhsPage()
    cur_len = 0
    for b in doc.blocks:
        if b.type in (BlockType.IMAGE, BlockType.VIDEO):
            # 插图内嵌正文页（V1.10）：图片按等价字数计入当前页容量，
            # 嵌在首个段落之后展示；仅当当前页已有插图或容量不足时才开新页
            cost = img_cost
            if cur.asset_id is not None or                         (cur_len + cost > max_chars and (cur.block_ids or cur.title)):
                pages.append(cur)
                cur, cur_len = XhsPage(), 0
            cur.asset_id = b.asset_id
            cur_len += cost
            continue
        tlen = bk.word_count(b.text or "")
        if cur_len + tlen > max_chars and cur.block_ids:
            pages.append(cur)
            cur, cur_len = XhsPage(), 0
        if b.type == BlockType.HEADING and b.level <= 2 and not cur.title:
            cur.title = b.text
            continue
        cur.block_ids.append(b.id)
        cur_len += tlen
        if len(pages) >= max_pages:
            break
    if cur.block_ids or cur.title:
        pages.append(cur)
    return pages[:max_pages]

