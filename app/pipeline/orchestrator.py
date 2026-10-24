"""编排器：状态推进 + Agent 调用 + auto 模式连跑。业务逻辑全在 agents/，这里只做编排。"""
from __future__ import annotations

from ..agents.collector import CollectorAgent
from ..agents.reviewer import ReviewerAgent
from ..agents.rewriter import RewriterAgent
from ..core import config, events
from ..core.models import ArticleStatus
from ..core.statemachine import transition
from ..storage import dao

_agents: dict[str, object] = {}


def _get_agents(llm=None):
    if llm is not None:
        return {"collect": CollectorAgent(llm), "rewrite": RewriterAgent(llm),
                "review": ReviewerAgent(llm)}
    if not _agents:
        _agents.update({"collect": CollectorAgent(), "rewrite": RewriterAgent(),
                        "review": ReviewerAgent()})
    return _agents


def _set_status(article_id: str, dst: ArticleStatus, error: str | None = None) -> None:
    art = dao.get_article(article_id)
    src = ArticleStatus(art["status"])
    if src == dst:
        return  # 幂等：任务重试时阶段入口态与目标态相同
    transition(src, dst)  # 非法迁移抛 InvalidTransition
    dao.set_article_status(article_id, dst, error)
    events.bus.publish(events.STATUS_CHANGED, article_id,
                       status=dst.value, error=error)


def run_stage(stage: str, article_id: str, llm=None) -> dict:
    """执行一个阶段。stage ∈ collect | rewrite | review。返回结果摘要。"""
    art = dao.get_article(article_id)
    if not art:
        raise ValueError(f"文章不存在: {article_id}")
    # 迟到/失效任务保护：当前状态不允许该阶段时静默跳过（不定罪文章）
    if stage in STAGE_ENTRY and ArticleStatus(art["status"]) not in STAGE_ENTRY[stage]:
        return {"skipped": True, "stage": stage, "status": art["status"]}
    agents = _get_agents(llm)
    if stage == "collect":
        _set_status(article_id, ArticleStatus.COLLECTING)
        events.bus.publish(events.COLLECT_STARTED, article_id)
        report = agents["collect"].run(article_id)
        _set_status(article_id, ArticleStatus.COLLECTED)
        result = {"topic": report.topic, "refs": len(report.refs), "scarce": report.scarce}
    elif stage == "rewrite":
        _set_status(article_id, ArticleStatus.WRITING)
        events.bus.publish(events.REWRITE_STARTED, article_id)
        doc = agents["rewrite"].run(article_id)
        _set_status(article_id, ArticleStatus.DRAFTED)
        result = {"version": doc.version, "word_count": doc.meta.word_count}
    elif stage == "review":
        # 定稿/发布后的复审是「软审」：只出报告不改动状态，避免把已定稿文章拽回编辑态
        soft = ArticleStatus(art["status"]) in (ArticleStatus.FINALIZED, ArticleStatus.DONE,
                                                ArticleStatus.PUBLISHING)
        if not soft:
            _set_status(article_id, ArticleStatus.REVIEWING)
        events.bus.publish(events.REVIEW_STARTED, article_id)
        review_id, items, scores = agents["review"].run(article_id)
        if not soft:
            _set_status(article_id, ArticleStatus.REVIEWED)
            # 审稿完成即进入人工编辑态（人工关卡）
            _set_status(article_id, ArticleStatus.EDITING)
        result = {"review_id": review_id, "items": len(items), "scores": scores,
                  "soft": soft}
    else:
        raise ValueError(f"未知阶段: {stage}")

    if config.get("pipeline.auto", False):
        _maybe_chain(stage, article_id)
    return result


def _maybe_chain(just_finished: str, article_id: str) -> None:
    nxt = {"collect": "rewrite", "rewrite": "review"}.get(just_finished)
    if nxt:
        dao.enqueue_job(nxt, article_id)


def mark_failed(article_id: str | None, error: str) -> None:
    if not article_id:
        return
    art = dao.get_article(article_id)
    if not art:
        return
    try:
        src = ArticleStatus(art["status"])
        transition(src, ArticleStatus.FAILED)
        dao.set_article_status(article_id, ArticleStatus.FAILED, error[:500])
    except Exception:
        dao.set_article_status(article_id, ArticleStatus.FAILED, error[:500])
    events.bus.publish(events.JOB_FAILED, article_id, error=error[:500])


# 阶段准入：当前状态 → 允许启动的阶段。含自身进行态以支持失败重试的幂等。
STAGE_ENTRY = {
    "collect": {ArticleStatus.NEW, ArticleStatus.COLLECTED, ArticleStatus.FAILED,
                ArticleStatus.COLLECTING},
    "rewrite": {ArticleStatus.COLLECTED, ArticleStatus.DRAFTED, ArticleStatus.EDITING,
                ArticleStatus.WRITING, ArticleStatus.FAILED},
    "review": {ArticleStatus.DRAFTED, ArticleStatus.EDITING, ArticleStatus.REVIEWING,
               ArticleStatus.FINALIZED, ArticleStatus.FAILED},
}


def can_start(stage: str, status: ArticleStatus) -> bool:
    return status in STAGE_ENTRY.get(stage, set())
