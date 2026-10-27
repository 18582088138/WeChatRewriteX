"""审稿 Agent：六维检查。

- layout / originality / compliance(词表)：纯规则，确定可测；
- fact / attribution / compliance(LLM) / ai_flavor：一次 LLM 调用出结构化条目；
- originality 采用拍板的双保险：创作侧 prompt 预防 + 审稿侧强约束（blocker + 修改指导）。
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..core import blocks as bk
from ..core import config, events
from ..core.models import Block, BlockType, ChecklistItem, DraftDoc
from ..storage import dao
from ..services.dedup.similarity import literal_similarity
from ..services.rag import index as rag_index
from .base import AgentBase

_WORD_PARA_LIMIT = 150          # 公众号段落字数上限
# 审稿引文中的成对引号：「」/『』/“”/""，用于 LLM 条目引文接地校验
_QUOTE_RE = re.compile(r"[「『“\"]([^「」『』“”\"]{4,80})[」』”\"]")
_QUOTE_CHARS = "「」『』“”\"'‘’"


class ReviewLLMItem(BaseModel):
    category: str = "fact"
    severity: str = "info"
    block_index: int = -1
    message: str = ""
    suggestion: str = ""
    auto_fixable: bool = False


class ReviewLLMOut(BaseModel):
    ai_flavor_score: int = 1
    items: list[ReviewLLMItem] = Field(default_factory=list)


class ReviewerAgent(AgentBase):
    name = "reviewer"

    def run(self, article_id: str) -> tuple[str, list[ChecklistItem], dict]:
        draft = dao.latest_draft(article_id)
        if not draft:
            raise ValueError("没有可审稿的草稿")
        doc = DraftDoc.model_validate_json(draft["doc_json"])
        style = self.load_style_pack()

        items: list[ChecklistItem] = []
        self.progress(article_id, "规则检查（排版/禁用词）…")
        items += self._check_layout(doc)
        items += self._check_banlist(doc, style.get("banlist", []))
        self.progress(article_id, "撞稿查重（SimHash 双阈值）…")
        orig_items, orig_score = self._check_originality(doc, article_id)
        items += orig_items

        scores: dict = {"originality_max_jaccard": orig_score,
                        "layout_issues": sum(1 for i in items if i.category == "layout")}

        if self.llm_available():
            self.progress(article_id, "LLM 四维审稿（事实/来源/合规/AI味）…")
            llm_items, ai_score = self._llm_review(doc, article_id, style)
            items += llm_items
            scores["ai_flavor"] = ai_score
        else:
            scores["ai_flavor"] = None

        self.progress(article_id, f"审稿完成：{len(items)} 条意见"
                                  f"（阻断 {sum(1 for i in items if i.severity == 'blocker')}）")
        review_id = dao.create_review(article_id, draft["id"], draft["version"],
                                      items, scores)
        events.bus.publish(events.REVIEW_FINISHED, article_id,
                           review_id=review_id,
                           blockers=sum(1 for i in items if i.severity == "blocker"))
        return review_id, items, scores

    # ---------- 规则维度 ----------

    def _check_layout(self, doc: DraftDoc) -> list[ChecklistItem]:
        out: list[ChecklistItem] = []
        headings = [b for b in doc.blocks if b.type == BlockType.HEADING]
        if len(headings) > 6:
            out.append(ChecklistItem(
                id="", category="layout", severity="warn",
                message=f"小标题 {len(headings)} 个，超过 6 个上限，层级易显碎",
                suggestion="合并相邻小节，保留主干结构", auto_fixable=False))
        for b in doc.blocks:
            if b.type == BlockType.PARAGRAPH:
                wc = bk.word_count(b.text)
                if wc > _WORD_PARA_LIMIT:
                    out.append(ChecklistItem(
                        id="", category="layout", severity="info", block_id=b.id,
                        message=f"段落 {wc} 字，超过 {_WORD_PARA_LIMIT} 字，移动端阅读压力大",
                        suggestion="拆成两段，各说一件事", auto_fixable=True))
        if doc.meta.one_liner and bk.word_count(doc.meta.one_liner) > 40:
            out.append(ChecklistItem(
                id="", category="layout", severity="info",
                message="一句话总结超过 40 字，列表页与微博开头会显长",
                suggestion="压缩到 40 字内", auto_fixable=True))
        if not any(b.type == BlockType.IMAGE for b in doc.blocks):
            out.append(ChecklistItem(
                id="", category="layout", severity="info",
                message="全文无配图，图文平台观感偏弱",
                suggestion="从素材库补 1~3 张配图", auto_fixable=False))
        lo_hi = config.get("variants.wechat_mp.word_range") or []
        if len(lo_hi) == 2:
            lo, hi = int(lo_hi[0]), int(lo_hi[1])
            total = bk.doc_word_count(doc)
            if hi and total > hi:
                out.append(ChecklistItem(
                    id="", category="layout", severity="warn",
                    message=f"正文 {total} 字，超出公众号建议区间 {lo}~{hi} 上限",
                    suggestion="压缩次要段落，或把延展内容移到评论区置顶", auto_fixable=False))
            elif lo and total < lo:
                out.append(ChecklistItem(
                    id="", category="layout", severity="info",
                    message=f"正文 {total} 字，低于公众号建议区间 {lo}~{hi} 下限",
                    suggestion="补充事实细节或案例分析", auto_fixable=False))
        xhs_limit = int(config.get("cards.max_chars_per_page", 300))
        for page in doc.meta.xhs_pages:
            chars = sum(bk.word_count((bk.get_block(doc, bid) or Block(id="", type=BlockType.PARAGRAPH)).text)
                        for bid in page.block_ids)
            if chars > xhs_limit:
                out.append(ChecklistItem(
                    id="", category="layout", severity="warn",
                    message=f"小红书某分页约 {chars} 字，超过 {xhs_limit} 字/页",
                    suggestion="重新分页或压缩该页文字", auto_fixable=False))
        return out

    def _check_banlist(self, doc: DraftDoc, banlist: list[str]) -> list[ChecklistItem]:
        out: list[ChecklistItem] = []
        for b in bk.iter_text_blocks(doc):
            for w in banlist:
                if w and w in b.text:
                    out.append(ChecklistItem(
                        id="", category="compliance", severity="warn", block_id=b.id,
                        message=f"命中禁用词「{w}」",
                        suggestion=f"删除或替换「{w}」", auto_fixable=True))
        return out

    def _check_originality(self, doc: DraftDoc,
                           article_id: str) -> tuple[list[ChecklistItem], float]:
        cfg = config.get("review.originality", {})
        warn_t = float(cfg.get("simhash_warn", 0.35))
        block_t = float(cfg.get("simhash_block", 0.55))
        refs = [m for m in dao.list_materials(article_id=article_id, kind="text")
                if m["fetch_status"] == "ok"]
        draft_text = "\n".join(b.text for b in bk.iter_text_blocks(doc))
        items: list[ChecklistItem] = []
        max_j = 0.0
        for m in refs:
            ref_text = dao.get_material_text(m["id"])
            if not ref_text.strip():
                continue
            sim = literal_similarity(draft_text, ref_text[:8000])
            max_j = max(max_j, sim["jaccard"])
            if sim["jaccard"] >= block_t:
                worst = self._worst_blocks(doc, ref_text, top=3)
                items.append(ChecklistItem(
                    id="", category="originality", severity="blocker",
                    message=f"与素材「{m.get('title') or m['id']}」字面相似度 "
                            f"{sim['jaccard']:.2f}（≥{block_t}），撞稿风险高",
                    suggestion="重写高相似段落：换叙事顺序、换例子、只保留事实不保留句式。",
                    evidence=[m["id"], *worst], auto_fixable=True))
            elif sim["jaccard"] >= warn_t:
                items.append(ChecklistItem(
                    id="", category="originality", severity="warn",
                    message=f"与素材「{m.get('title') or m['id']}」字面相似度 "
                            f"{sim['jaccard']:.2f}（≥{warn_t}）",
                    suggestion="对高重合段落做结构性改写", evidence=[m["id"]],
                    auto_fixable=True))
        return items, round(max_j, 4)

    @staticmethod
    def _worst_blocks(doc: DraftDoc, ref_text: str, top: int = 3) -> list[str]:
        scored = []
        for b in bk.iter_text_blocks(doc):
            if bk.word_count(b.text) < 30:
                continue
            scored.append((b.id, literal_similarity(b.text, ref_text[:8000])["jaccard"]))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [bid for bid, s in scored[:top] if s > 0.3]

    # ---------- LLM 维度 ----------

    def _llm_review(self, doc: DraftDoc, article_id: str,
                    style: dict) -> tuple[list[ChecklistItem], int | None]:
        text_blocks = list(bk.iter_text_blocks(doc))
        evidence_chars = int(config.get("review.evidence_chars", 8000))
        evidence = [{"id": m["id"], "title": m.get("title") or "",
                     "content": dao.get_material_text(m["id"])[:evidence_chars]}
                    for m in dao.list_materials(article_id=article_id, kind="text")
                    if m["fetch_status"] == "ok"]
        prompt = self.prompt("review", style=style, text_blocks=text_blocks,
                             evidence=evidence)
        try:
            result = self.complete("review", [{"role": "user", "content": prompt}],
                                   schema=ReviewLLMOut, article_id=article_id,
                                   stage="reviewer.llm", max_tokens=4000)
        except Exception:
            return [], None
        raw = [it for it in result.parsed.items
               if it.category in ("fact", "attribution", "compliance", "ai_flavor")]
        self._ground_llm_items(raw, doc, evidence)
        out: list[ChecklistItem] = []
        for it in raw:
            if it.severity not in ("info", "warn", "blocker"):
                it.severity = "warn"
            block_id = None
            if 0 <= it.block_index < len(text_blocks):
                block_id = text_blocks[it.block_index].id
            evidence_ids: list[str] = []
            if it.category == "fact" and block_id:
                block = bk.get_block(doc, block_id)
                if block:
                    evidence_ids = [e["material_id"] for e in
                                    rag_index.evidence_for_claim(block.text[:200],
                                                                 article_id, top_k=2)]
            out.append(ChecklistItem(
                id="", category=it.category, severity=it.severity, block_id=block_id,
                message=it.message, suggestion=it.suggestion,
                evidence=evidence_ids, auto_fixable=it.auto_fixable))
        score = max(1, min(5, result.parsed.ai_flavor_score))
        threshold = int(config.get("review.ai_flavor_score_max", 3))
        if score > threshold:
            out.append(ChecklistItem(
                id="", category="ai_flavor", severity="warn",
                message=f"AI 味评分 {score}/5（阈值 {threshold}）",
                suggestion="按反模式清单改写：去套话、打散排比、补具体细节",
                auto_fixable=True))
        return out, score

    # ---------- LLM 条目引文接地 ----------

    @staticmethod
    def _norm_quote(s: str) -> str:
        for ch in _QUOTE_CHARS:
            s = s.replace(ch, "")
        s = re.sub(r"[*_`#]+", "", s)      # 爬取 markdown 的强调/标题符号
        s = re.sub(r"<[^>]+>", "", s)      # 残留 HTML 标签
        return re.sub(r"\s+", "", s)

    def _ground_llm_items(self, items: list[ReviewLLMItem], doc: DraftDoc,
                          evidence: list[dict]) -> None:
        """LLM 审稿条目的引文接地校验：message 中成对引号包裹的片段，
        必须能在稿件或证据包中逐字找到（归一化后包含）；都找不到即疑似
        幻觉引文，严重级降一档并在 message 留痕。suggestion 里的引号片段
        是建议替换文本，不参与校验。"""
        draft_hay = self._norm_quote(
            "\n".join(b.text or "" for b in bk.iter_text_blocks(doc)))
        evidence_hay = self._norm_quote("\n".join(e.get("content") or ""
                                                  for e in evidence))
        downgrade = {"blocker": "warn", "warn": "info"}
        for it in items:
            for q in _QUOTE_RE.findall(it.message or ""):
                nq = self._norm_quote(q)
                if len(nq) < 4:
                    continue
                if nq not in draft_hay and nq not in evidence_hay:
                    if it.severity in downgrade:
                        it.severity = downgrade[it.severity]
                        it.message = (it.message or "") + "（引文未在稿件/证据中逐字核实，已自动降级）"
                    break
