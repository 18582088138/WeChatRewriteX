"""Agent 单测：审稿规则维度 / 创作分页 / 降级稿；以及 FakeLLM 跑通创作主流程。"""
from __future__ import annotations

import json

from app.agents.reviewer import ReviewerAgent
from app.agents.creator import CreatorAgent
from app.core.models import Block, BlockType, DraftDoc, DraftMeta
from app.services.llm.router import LLMResult
from app.storage import dao, library


def _mk_article_with_source() -> tuple[dict, str]:
    art = dao.create_article("fixture://sample_article.md")
    # 素材按 sha256 全局去重，跨测试需内容唯一（缀上文章 id）
    src = ("星河实验室发布开源多模态模型 StarRiver-2，参数规模 72B，"
           "在 MMMU 基准上取得 68.4 分，较上一代提升 12%。" * 4) + art["id"]
    mid = library.ingest_text(src, title="原文", scope="article", article_id=art["id"],
                              source_url="fixture://sample_article.md", ref_type="primary")
    return art, mid


def _doc_with(text: str, article_id: str) -> DraftDoc:
    return DraftDoc(id="", article_id=article_id, version=1,
                    blocks=[Block(id="b1", type=BlockType.HEADING, level=1, text="标题"),
                            Block(id="b2", type=BlockType.PARAGRAPH, text=text)],
                    meta=DraftMeta(one_liner="一句话总结"))


def test_reviewer_layout_and_banlist():
    art, _ = _mk_article_with_source()
    long_para = "这是一段很长的段落。" * 40       # >150 字
    doc = _doc_with(long_para + " 综上所述，未来可期。", art["id"])
    agent = ReviewerAgent()
    layout = agent._check_layout(doc)
    assert any(i.category == "layout" and i.block_id == "b2" for i in layout)
    style = agent.load_style_pack()
    ban = agent._check_banlist(doc, style["banlist"])
    hits = {i.message for i in ban}
    assert any("综上所述" in m for m in hits) and any("未来可期" in m for m in hits)


def test_reviewer_originality_blocker():
    art, primary_mid = _mk_article_with_source()
    src_text = dao.get_material_text(primary_mid)
    doc = _doc_with(src_text[:1500], art["id"])     # 大段照抄 → blocker
    dao.save_draft(_with_ids(doc, art["id"]), origin="agent")
    agent = ReviewerAgent()
    items, max_j = agent._check_originality(doc, art["id"])
    assert max_j > 0.55
    assert any(i.severity == "blocker" and i.category == "originality" for i in items)


def _with_ids(doc: DraftDoc, article_id: str) -> DraftDoc:
    doc.version = dao.next_version(article_id)
    doc.id = f"{article_id}-v{doc.version}"
    return doc


def test_creator_pagination_greedy():
    doc = DraftDoc(id="", article_id="a", version=1, blocks=[], meta=DraftMeta())
    for i in range(6):
        doc.blocks.append(Block(id=f"b{i}", type=BlockType.PARAGRAPH, text="字" * 200))
    pages = CreatorAgent._paginate_xhs(doc)
    assert len(pages) == 6            # 200 字/块，上限 300 → 每页一块
    assert all(len(p.block_ids) == 1 for p in pages)


class FakeLLM:
    """按 stage 返回脚本化输出，验证创作主流程无需真实 LLM。"""

    def __call__(self, purpose, messages, schema=None, article_id=None, stage="", max_tokens=None):
        if "draft" in stage:
            payload = {
                "title_candidates": ["72B 的诚意之作", "StarRiver-2 上手读", "开源又多一员"],
                "keywords": ["多模态", "MoE", "开源"],
                "one_liner": "星河实验室开源 72B 多模态模型，价格砍掉四成。",
                "blocks": [
                    {"type": "heading", "level": 1, "text": "72B 的诚意之作"},
                    {"type": "paragraph",
                     "text": "如果你最近觉得开源模型卷得有点疲，这条新闻值得看一眼："
                             "星河实验室把 StarRiver-2 的权重直接放了出来，Apache 2.0，可商用。",
                     "citations": ["$PRIMARY"]},
                    {"type": "paragraph",
                     "text": "参数 72B、激活 13B 的 MoE 架构，128K 上下文，"
                             "MMMU 拿到 68.4 分——比上代高出约 12%，属于稳步前进。",
                     "citations": ["$PRIMARY"]},
                ],
            }
        elif "compress" in stage:
            payload = {"blocks": []}
        else:
            payload = {"topic": "多模态开源模型", "keywords": ["StarRiver-2"],
                       "core_points": [], "entities": [], "foundational_queries": []}
        text = json.dumps(payload, ensure_ascii=False)
        parsed = schema.model_validate(payload) if schema else None
        return LLMResult(text=text, parsed=parsed, model="fake/fake", channel="fake")


def test_creator_run_with_fake_llm():
    art, primary_mid = _mk_article_with_source()
    agent = CreatorAgent(llm=FakeLLM())
    # 把 FakeLLM 输出里的占位引用替换为真实素材 id（模拟 LLM 正确引用）
    orig_complete = agent.complete

    def patched(purpose, messages, schema=None, article_id=None, stage="", max_tokens=None):
        r = orig_complete(purpose, messages, schema=schema, article_id=article_id,
                          stage=stage, max_tokens=max_tokens)
        if stage == "creator.draft" and r.parsed:
            for b in r.parsed.blocks:
                if b.get("citations"):
                    b["citations"] = [primary_mid]
        return r

    agent.complete = patched
    doc = agent.run(art["id"])
    assert doc.version == 1
    assert doc.meta.title_candidates[0] == "72B 的诚意之作"
    assert any(b.citations == [primary_mid] for b in doc.blocks)
    latest = dao.latest_draft(art["id"])
    assert latest and latest["origin"] == "agent"


def test_reviewer_xhs_page_limit_follows_config():
    """小红书分页字数上限读 cards.max_chars_per_page（仓库配置 380），
    不再用旧硬编码 300：350 字页不报，400 字页报。"""
    from app.core.models import XhsPage
    art, _ = _mk_article_with_source()
    doc = _doc_with("正文。" * 50, art["id"])
    b350 = Block(id="b350", type=BlockType.PARAGRAPH, text="字" * 350)
    b400 = Block(id="b400", type=BlockType.PARAGRAPH, text="字" * 400)
    doc.blocks += [b350, b400]
    doc.meta.xhs_pages = [XhsPage(block_ids=["b350"]), XhsPage(block_ids=["b400"])]
    agent = ReviewerAgent()
    msgs = [i.message for i in agent._check_layout(doc) if "小红书" in i.message]
    assert len(msgs) == 1 and "400" in msgs[0] and "380" in msgs[0]


def test_reviewer_word_range_check():
    """总词数对 variants.wechat_mp.word_range(1200~1800)：超出 warn，不足 info。"""
    art, _ = _mk_article_with_source()
    agent = ReviewerAgent()
    over = agent._check_layout(_doc_with("字" * 2000, art["id"]))
    assert any("超出公众号建议区间" in i.message and i.severity == "warn" for i in over)
    under = agent._check_layout(_doc_with("短。" * 100, art["id"]))
    assert any("低于公众号建议区间" in i.message and i.severity == "info" for i in under)


def test_review_grounding_downgrades_hallucinated_quotes():
    """LLM 条目 message 里的引文片段必须在稿件或证据中逐字找到，
    都找不到（疑似幻觉引文）→ 严重级降一档并留痕；真实引文不动。"""
    from app.agents.reviewer import ReviewLLMItem
    art, _ = _mk_article_with_source()
    doc = _doc_with("OpenAI 把网线拔了，然后 AI 学会了用 CPU 缓存聊天。" * 2, art["id"])
    evidence = [{"id": "m1", "title": "t",
                 "content": "证据原文：缓存侧信道与离线环境。年初每天服务的Token大约是**4000亿**。"}]
    items = [
        ReviewLLMItem(category="fact", severity="blocker",
                      message="「AI 学会了用 CPU 缓存聊天」与证据矛盾"),
        ReviewLLMItem(category="compliance", severity="warn",
                      message="「为了保证系统的绝对安全」属绝对化用语"),
        ReviewLLMItem(category="fact", severity="warn",
                      message="证据写『缓存侧信道』，稿件口径放大"),
        ReviewLLMItem(category="fact", severity="warn",
                      message="证据写『每天服务的Token大约是4000亿』，数字一致"),
    ]
    ReviewerAgent()._ground_llm_items(items, doc, evidence)
    assert items[0].severity == "blocker"                    # 稿件引文真实 → 不动
    assert items[1].severity == "info"                       # 捏造引文 → warn 降 info
    assert "已自动降级" in items[1].message
    assert items[2].severity == "warn"                       # 证据引文真实 → 不动
    assert items[3].severity == "warn"                       # markdown 强调符归一化后命中 → 不动
