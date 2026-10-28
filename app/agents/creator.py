"""创作 Agent：证据包 grounding → 成稿 → 词数控制 → 元数据 → 分页建议。

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
    subtitle: str = ""                               # 副标题（V1.3）
    keywords: list[str] = Field(default_factory=list)
    one_liner: str = ""
    blocks: list[dict] = Field(default_factory=list)


class BlocksPayload(BaseModel):
    blocks: list[dict] = Field(default_factory=list)


_REF_LABEL = {"primary": "原文", "reference": "参考", "foundational": "基础资料"}


class CreatorAgent(AgentBase):
    name = "creator"

    # ---------- 主流程 ----------

    def run(self, article_id: str, selected_material_ids: list[str] | None = None) -> DraftDoc:
        article = dao.get_article(article_id)
        if not article:
            raise ValueError(f"文章不存在: {article_id}")
        base = dao.latest_draft(article_id)
        expected_version = base["version"] if base else 0
        style = self.load_style_pack(article.get("style_pack"))
        self.progress(article_id, "汇总证据包与可用素材…")
        evidence = self._evidence_pack(article_id, selected_material_ids)
        media = self._available_media(article_id, selected_material_ids)
        images = media["images"]
        videos = media["videos"]
        self.progress(article_id, f"证据 {len(evidence)} 份 · 图片 {len(images)} 张 · 视频 {len(videos)} 个")
        word_target = int(article.get("target_word_count")
                          or config.get("create.target_word_count", 1500))
        self._evidence_now = evidence            # 供 ref_links 使用

        if not self.llm_available():
            self.progress(article_id, "LLM 未配置，走降级保底稿…")
            doc = self._degraded_doc(article_id, evidence)
        else:
            self.progress(article_id, f"LLM 成稿中（目标 {word_target} 字）…")
            prompt = self.prompt("draft", style=style, word_target=word_target,
                                 evidence=evidence, images=images, videos=videos,
                                 user_notes=article.get("user_notes") or "")
            result = self.complete("create", [{"role": "user", "content": prompt}],
                                   schema=DraftPayload, article_id=article_id,
                                   stage="creator.draft", max_tokens=8000)
            doc = self._payload_to_doc(article_id, result.parsed)
            doc = self._enforce_word_count(doc, style, word_target, article_id)
            self._ensure_images(doc, images)
            doc.meta.xhs_pages = self._paginate_xhs(doc)
            self.progress(article_id, f"成稿完成：{doc.meta.word_count or 0} 字 · "
                                      f"{len(doc.blocks)} 块 · 小红书分页 {len(doc.meta.xhs_pages)} 页")
        # 参考文字链接：记录本次创作用到的文章素材（标题+链接）
        doc.meta.ref_links = bk.dedupe_ref_links([
            {"title": m.get("title") or "", "url": m.get("source_url") or ""}
            for m in getattr(self, "_evidence_now", [])
        ])

        # 创作定题 → 项目文件夹从「输入标题-日期」改名为「拟定标题-日期」（先于落盘）
        new_title = (doc.meta.title_candidates or [""])[0]

        from ..services import draft_service
        doc = draft_service.save_new_version(doc, origin="agent", checkpoint=True,
                                             expected_version=expected_version)
        if new_title:
            library.rename_to_created_title(article_id, new_title)
        events.bus.publish(events.CREATE_FINISHED, article_id, version=doc.version,
                           word_count=bk.doc_word_count(doc))
        return doc

    # ---------- 编辑期能力 ----------

    def regenerate_blocks(self, article_id: str, doc: DraftDoc, block_ids: list[str],
                          instruction: str = "") -> DraftDoc:
        style = self.load_style_pack((dao.get_article(article_id) or {}).get("style_pack"))
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

        result = self.complete("create", [{"role": "user", "content": prompt}],
                               schema=RegenOut, article_id=article_id,
                               stage="creator.regenerate")
        by_index = {int(x.get("index", -1)): str(x.get("text", ""))
                    for x in result.parsed.blocks}
        for i, b in enumerate(targets):
            if i in by_index and by_index[i]:
                b.text = bk.sanitize_block_text(by_index[i])
        return doc

    def insert_references(self, article_id: str, doc: DraftDoc, material_ids: list[str],
                          after_block_id: str | None, instruction: str = "") -> DraftDoc:
        style = self.load_style_pack((dao.get_article(article_id) or {}).get("style_pack"))
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
        result = self.complete("create", [{"role": "user", "content": prompt}],
                               schema=BlocksPayload, article_id=article_id,
                               stage="creator.insert_refs")
        new_blocks = bk.blocks_from_llm(result.parsed.model_dump())
        anchor = after_block_id
        for nb in new_blocks:
            bk.insert_block(doc, anchor, nb)
            anchor = nb.id
        return doc

    # ---------- 内部 ----------

    def _evidence_pack(self, article_id: str,
                       selected_ids: list[str] | None = None) -> list[dict]:
        mats = dao.list_materials(article_id=article_id)
        if selected_ids:
            keep = set(selected_ids)
            mats = [m for m in mats if m["id"] in keep]
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
    def _available_images(article_id: str,
                          selected_ids: list[str] | None = None) -> list[dict]:
        """兼容名：返回图片列表。"""
        return CreatorAgent._available_media(article_id, selected_ids)["images"]

    @staticmethod
    def _available_media(article_id: str,
                         selected_ids: list[str] | None = None) -> dict:
        """可用媒体：图片 + 已下载视频（实体文件可插入正文）。水印图垫底。"""
        mats = dao.list_materials(article_id=article_id)
        if selected_ids:
            keep = set(selected_ids)
            mats = [m for m in mats if m["id"] in keep]
        images, videos = [], []
        for m in mats:
            if m.get("fetch_status") != "ok":
                continue
            item = {"id": m["id"], "title": m.get("title") or "",
                    "width": m.get("width"), "height": m.get("height"),
                    "watermark": m.get("watermark"), "duration": m.get("duration"),
                    "source": m.get("source_url") or ""}
            if m["kind"] == "image":
                images.append(item)
            elif m["kind"] == "video" and m.get("path"):
                videos.append(item)
        images.sort(key=lambda x: x.get("watermark") or 0)
        return {"images": images, "videos": videos}
        """可用图片：含水印图（拍板 #7：暂可用，排在最后），只排除下载失败/过小。
        勾选集合给定时只从勾选图片中取。"""
        mats = dao.list_materials(article_id=article_id, kind="image")
        if selected_ids:
            keep = set(selected_ids)
            mats = [m for m in mats if m["id"] in keep]
        out = []
        for m in mats:
            if m.get("fetch_status") != "ok":
                continue
            out.append({"id": m["id"], "title": m.get("title") or "",
                        "width": m.get("width"), "height": m.get("height"),
                        "watermark": m.get("watermark"),
                        "source": m.get("source_url") or ""})
        out.sort(key=lambda x: x.get("watermark") or 0)   # 无水印发前，水印垫底
        return out

    @staticmethod
    def _ensure_images(doc: DraftDoc, images: list[dict]) -> None:
        """文案必须有配图：LLM 没配图时按序补插（首图第二段后，次图 2/3 处）。
        升序插入并累计偏移，保持原顺序与下标正确。"""
        if any(b.type in (BlockType.IMAGE, BlockType.VIDEO) for b in doc.blocks):
            return
        if not images:
            return
        paras = [i for i, b in enumerate(doc.blocks) if b.type == BlockType.PARAGRAPH]
        if not paras:
            return
        spots = sorted({paras[min(1, len(paras) - 1)], paras[int(len(paras) * 0.66)]})
        for offset, (img, pos) in enumerate(zip(images, spots)):
            doc.blocks.insert(pos + 1 + offset, Block(
                id=bk.new_block_id(), type=BlockType.IMAGE, asset_id=img["id"],
                caption=img.get("title") or "配图", source="素材库"))

    def _payload_to_doc(self, article_id: str, payload: DraftPayload) -> DraftDoc:
        blocks = bk.blocks_from_llm(payload.model_dump())
        # 校验图片块 asset_id 存在性，不存在则丢弃该块（防幻觉配图）
        valid = []
        for b in blocks:
            if b.type in (BlockType.IMAGE, BlockType.VIDEO):
                if b.asset_id and dao.get_material(b.asset_id):
                    valid.append(b)
                continue
            valid.append(b)
        doc = DraftDoc(id="", article_id=article_id, version=0, blocks=valid,
                       meta=DraftMeta(keywords=payload.keywords,
                                      one_liner=payload.one_liner,
                                      subtitle=payload.subtitle,
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
                                   stage="creator.compress", max_tokens=8000)
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
        from ..core.pagination import paginate_xhs
        return paginate_xhs(doc, int(config.get("cards.max_chars_per_page", 300)),
                            int(config.get("cards.image_char_cost", 150)),
                            int((config.get("variants.xhs.pages") or [3, 9])[1]))

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
