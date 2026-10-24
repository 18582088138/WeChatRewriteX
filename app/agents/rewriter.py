"""洗稿 Agent：证据包 grounding → 成稿 → 词数控制 → 元数据 → 分页建议。

编辑期能力（段落重生成 / 资料融合插入）也在这里，供 API 层直接调用。
"""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from ..core import blocks as bk
from ..core import config, events
from ..core.models import Block, BlockType, DraftDoc, DraftMeta
from ..storage import dao, library
from .base import AgentBase


class DraftPayload(BaseModel):
    title_candidates: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    one_liner: str = ""
    blocks: list[dict] = Field(default_factory=list)


class BlocksPayload(BaseModel):
    blocks: list[dict] = Field(default_factory=list)


_REF_LABEL = {"primary": "原文", "reference": "参考", "foundational": "基础资料"}


class RewriterAgent(AgentBase):
    name = "rewriter"

    # ---------- 主流程 ----------

    def run(self, article_id: str) -> DraftDoc:
        article = dao.get_article(article_id)
        if not article:
            raise ValueError(f"文章不存在: {article_id}")
        style = self.load_style_pack(article.get("style_pack"))
        evidence = self._evidence_pack(article_id)
        images = self._available_images(article_id)
        word_target = int(article.get("target_word_count")
                          or config.get("rewrite.target_word_count", 1500))

        if not self.llm_available():
            doc = self._degraded_doc(article_id, evidence)
        else:
            prompt = self.prompt("draft", style=style, word_target=word_target,
                                 evidence=evidence, images=images,
                                 user_notes=article.get("user_notes") or "")
            result = self.complete("rewrite", [{"role": "user", "content": prompt}],
                                   schema=DraftPayload, article_id=article_id,
                                   stage="rewriter.draft", max_tokens=8000)
            doc = self._payload_to_doc(article_id, result.parsed)
            doc = self._enforce_word_count(doc, style, word_target, article_id)
            doc.meta.xhs_pages = self._paginate_xhs(doc)

        version = dao.next_version(article_id)
        doc.version = version
        doc.id = f"{article_id}-v{version}"
        dao.save_draft(doc, origin="agent")
        library.save_draft_files(doc, bk.to_markdown(doc))
        events.bus.publish(events.REWRITE_FINISHED, article_id, version=version,
                           word_count=bk.doc_word_count(doc))
        return doc

    # ---------- 编辑期能力 ----------

    def regenerate_blocks(self, article_id: str, doc: DraftDoc, block_ids: list[str],
                          instruction: str = "") -> DraftDoc:
        style = self.load_style_pack()
        targets = [b for b in doc.blocks if b.id in set(block_ids)]
        if not targets:
            raise ValueError("未找到目标块")
        first_idx = doc.blocks.index(targets[0])
        before = "\n".join(b.text for b in doc.blocks[max(0, first_idx - 2):first_idx])
        after_blocks = doc.blocks[doc.blocks.index(targets[-1]) + 1:
                                  doc.blocks.index(targets[-1]) + 3]
        after = "\n".join(b.text for b in after_blocks)
        prompt = self.prompt("regenerate", style=style, blocks=targets,
                             instruction=instruction, before=before, after=after)

        class RegenOut(BaseModel):
            blocks: list[dict] = Field(default_factory=list)

        result = self.complete("rewrite", [{"role": "user", "content": prompt}],
                               schema=RegenOut, article_id=article_id,
                               stage="rewriter.regenerate")
        by_index = {int(x.get("index", -1)): str(x.get("text", ""))
                    for x in result.parsed.blocks}
        for i, b in enumerate(targets):
            if i in by_index and by_index[i]:
                b.text = by_index[i]
        return doc

    def insert_references(self, article_id: str, doc: DraftDoc, material_ids: list[str],
                          after_block_id: str | None, instruction: str = "") -> DraftDoc:
        style = self.load_style_pack()
        refs = [{"id": mid, "content": dao.get_material_text(mid)[:2500]}
                for mid in material_ids]
        refs = [r for r in refs if r["content"].strip()]
        if not refs:
            raise ValueError("参考素材无文本内容")
        idx = next((i for i, b in enumerate(doc.blocks) if b.id == after_block_id),
                   len(doc.blocks) - 1)
        before = "\n".join(b.text for b in doc.blocks[max(0, idx - 1):idx + 1])
        after = "\n".join(b.text for b in doc.blocks[idx + 1:idx + 3])
        prompt = self.prompt("insert_refs", style=style, refs=refs,
                             instruction=instruction, before=before, after=after)
        result = self.complete("rewrite", [{"role": "user", "content": prompt}],
                               schema=BlocksPayload, article_id=article_id,
                               stage="rewriter.insert_refs")
        new_blocks = bk.blocks_from_llm(result.parsed.model_dump())
        anchor = after_block_id
        for nb in new_blocks:
            bk.insert_block(doc, anchor, nb)
            anchor = nb.id
        return doc

    # ---------- 内部 ----------

    def _evidence_pack(self, article_id: str) -> list[dict]:
        mats = dao.list_materials(article_id=article_id)
        pack = []
        for m in mats:
            if m["kind"] != "text" or m["fetch_status"] != "ok":
                continue
            content = dao.get_material_text(m["id"])
            if not content.strip():
                continue
            pack.append({
                "id": m["id"], "title": m.get("title") or m["id"],
                "ref_type_label": _REF_LABEL.get(m.get("ref_type") or "", "参考"),
                "site": (json.loads(m.get("meta_json") or "{}").get("site") or ""),
                "content": content[:4500],
            })
        order = {"primary": 0, "reference": 1, "foundational": 2}
        pack.sort(key=lambda x: order.get(next(
            (k for k, v in _REF_LABEL.items() if v == x["ref_type_label"]), ""), 1))
        return pack

    @staticmethod
    def _available_images(article_id: str) -> list[dict]:
        mats = dao.list_materials(article_id=article_id, kind="image")
        out = []
        for m in mats:
            if m.get("watermark") == 1 or m.get("fetch_status") != "ok":
                continue
            out.append({"id": m["id"], "title": m.get("title") or "",
                        "width": m.get("width"), "height": m.get("height"),
                        "source": m.get("source_url") or ""})
        return out

    def _payload_to_doc(self, article_id: str, payload: DraftPayload) -> DraftDoc:
        blocks = bk.blocks_from_llm(payload.model_dump())
        # 校验图片块 asset_id 存在性，不存在则丢弃该块（防幻觉配图）
        valid = []
        for b in blocks:
            if b.type == BlockType.IMAGE:
                if b.asset_id and dao.get_material(b.asset_id):
                    valid.append(b)
                continue
            valid.append(b)
        doc = DraftDoc(id="", article_id=article_id, version=0, blocks=valid,
                       meta=DraftMeta(keywords=payload.keywords,
                                      one_liner=payload.one_liner,
                                      title_candidates=payload.title_candidates[:3]))
        doc.meta.word_count = bk.doc_word_count(doc)
        return doc

    def _enforce_word_count(self, doc: DraftDoc, style: dict, target: int,
                            article_id: str) -> DraftDoc:
        wc = bk.doc_word_count(doc)
        if wc <= target * 1.15:
            return doc
        blocks_json = json.dumps([b.model_dump() for b in doc.blocks], ensure_ascii=False)
        try:
            prompt = self.prompt("compress", style=style, word_target=int(target * 1.05),
                                 current=wc, blocks_json=blocks_json[:12000])
            result = self.complete("compress", [{"role": "user", "content": prompt}],
                                   schema=BlocksPayload, article_id=article_id,
                                   stage="rewriter.compress", max_tokens=8000)
            new_blocks = bk.blocks_from_llm(result.parsed.model_dump())
            # 保留原图片块（压缩 prompt 可能丢图）
            images = [b for b in doc.blocks if b.type in (BlockType.IMAGE, BlockType.VIDEO)]
            doc.blocks = new_blocks + [b for b in images
                                       if not any(n.asset_id == b.asset_id
                                                  for n in new_blocks if n.asset_id)]
            doc.meta.word_count = bk.doc_word_count(doc)
        except Exception:
            pass  # 压缩失败保留原稿
        return doc

    @staticmethod
    def _paginate_xhs(doc: DraftDoc):
        """规则式分页：按字数贪心打包（≤max_chars/页），视觉分页由 cards 服务最终保证。"""
        from ..core.models import XhsPage
        max_chars = int(config.get("cards.max_chars_per_page", 300))
        max_pages = int((config.get("variants.xhs.pages") or [3, 9])[1])
        pages: list[XhsPage] = []
        cur = XhsPage()
        cur_len = 0
        for b in doc.blocks:
            if b.type in (BlockType.IMAGE, BlockType.VIDEO):
                if cur.block_ids or cur.title:
                    pages.append(cur)
                pages.append(XhsPage(title="", block_ids=[], asset_id=b.asset_id))
                cur, cur_len = XhsPage(), 0
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

    @staticmethod
    def _degraded_doc(article_id: str, evidence: list[dict]) -> DraftDoc:
        """无 LLM 渠道的保底稿：标题 + 要点罗列，保证流程可演示、可人工接续。"""
        blocks = [Block(id=bk.new_block_id(), type=BlockType.HEADING, level=1,
                        text=evidence[0]["title"] if evidence else "（未配置 LLM）"),
                  Block(id=bk.new_block_id(), type=BlockType.PARAGRAPH,
                        text="当前未配置 LLM 渠道密钥，以下为素材要点罗列，请在设置页配置 "
                             "DEEPSEEK_API_KEY 等后重新生成。")]
        for m in evidence[:5]:
            first = m["content"].strip().split("\n")[0][:200]
            blocks.append(Block(id=bk.new_block_id(), type=BlockType.PARAGRAPH,
                                text=f"· {first}", citations=[m["id"]]))
        return DraftDoc(id="", article_id=article_id, version=0, blocks=blocks,
                        meta=DraftMeta(one_liner="待配置 LLM 后生成"))
