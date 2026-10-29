"""编排器：状态推进 + Agent 调用 + auto 模式连跑。业务逻辑全在 agents/，这里只做编排。"""
from __future__ import annotations

from ..core import config, events
from ..core.models import ArticleStatus
from ..core.statemachine import transition
from ..storage import dao, db

_agents: dict[str, object] = {}


def _get_agents(llm=None):
    # V1.16: defer crawl/LLM/template imports until the first pipeline job.
    # The HTTP UI no longer waits for trafilatura and Agent initialization.
    from ..agents.collector import CollectorAgent
    from ..agents.reviewer import ReviewerAgent
    from ..agents.creator import CreatorAgent
    if llm is not None:
        return {"collect": CollectorAgent(llm), "create": CreatorAgent(llm),
                "review": ReviewerAgent(llm)}
    if not _agents:
        _agents.update({"collect": CollectorAgent(), "create": CreatorAgent(),
                        "review": ReviewerAgent()})
    return _agents


def _set_status(article_id: str, dst: ArticleStatus, error: str | None = None) -> None:
    with db.transaction():
        art = dao.get_article(article_id)
        if not art:
            raise ValueError("文章不存在")
        src = ArticleStatus(art["status"])
        if src == dst:
            return
        transition(src, dst)
        dao.set_article_status(article_id, dst, error)
        db.after_commit(lambda: events.bus.publish(events.STATUS_CHANGED, article_id,
                       status=dst.value, error=error))


def run_stage(stage: str, article_id: str, llm=None, payload: dict | None = None) -> dict:
    """执行一个阶段。stage ∈ collect | create | review。返回结果摘要。"""
    art = dao.get_article(article_id)
    if not art:
        raise ValueError(f"文章不存在: {article_id}")
    # 迟到/失效任务保护：当前状态不允许该阶段时静默跳过（不定罪文章）
    if stage in STAGE_ENTRY and ArticleStatus(art["status"]) not in STAGE_ENTRY[stage]:
        return {"skipped": True, "stage": stage, "status": art["status"]}
    if stage == "create" and (payload or {}).get("draft_version") is not None:
        head = dao.latest_draft(article_id)
        version = head["version"] if head else 0
        key = (payload or {}).get("_job_id")
        replay = key and head and not head.get("reconstructed") and head.get("note") == f"job:{key}"
        from ..core.models import DraftDoc
        revision = DraftDoc.model_validate_json(head["doc_json"]).edit_revision if head else 0
        if (version != payload["draft_version"] or (payload.get("edit_revision") is not None and payload["edit_revision"] != revision)) and not replay:
            return {"skipped": True, "reason": "stale_create", "version": version}
    agents = _get_agents(llm)
    if stage == "collect":
        _set_status(article_id, ArticleStatus.COLLECTING)
        events.bus.publish(events.COLLECT_STARTED, article_id)
        report = agents["collect"].run(article_id)
        _set_status(article_id, ArticleStatus.COLLECTED)
        result = {"topic": report.topic, "refs": len(report.refs), "scarce": report.scarce}
    elif stage == "create":
        _set_status(article_id, ArticleStatus.CREATING)
        events.bus.publish(events.CREATE_STARTED, article_id)
        selected = (payload or {}).get("selected_material_ids")
        doc = agents["create"].run(article_id, selected_material_ids=selected)
        _set_status(article_id, ArticleStatus.DRAFTED)
        result = {"version": doc.version, "word_count": doc.meta.word_count}
    elif stage == "review":
        with db.transaction():
            snapshot = dao.latest_draft(article_id)
            if not snapshot:
                raise ValueError("没有草稿")
            expected = (payload or {}).get("draft_version")
            from ..core.models import DraftDoc
            revision = (payload or {}).get("edit_revision")
            snapshot_doc = DraftDoc.model_validate_json(snapshot["doc_json"])
            if (expected is not None and expected != snapshot["version"]) or (revision is not None and revision != snapshot_doc.edit_revision):
                return {"skipped": True, "reason": "stale_review", "version": snapshot["version"]}
            current = dao.get_article(article_id)
            soft = current["status"] in ("FINALIZED", "DONE", "PUBLISHING")
            if not soft:
                _set_status(article_id, ArticleStatus.REVIEWING)
        events.bus.publish(events.REVIEW_STARTED, article_id)
        review_id, items, scores = agents["review"].run(article_id, draft=snapshot)
        with db.transaction():
            head = dao.latest_draft(article_id)
            current = dao.get_article(article_id)
            stale = not head or (head["version"], DraftDoc.model_validate_json(head["doc_json"]).edit_revision) != (snapshot["version"], snapshot_doc.edit_revision)
            if not soft and not stale and current["status"] == "REVIEWING":
                _set_status(article_id, ArticleStatus.REVIEWED)
                _set_status(article_id, ArticleStatus.EDITING)
        result = {"review_id": review_id, "items": len(items), "scores": scores,
                  "soft": soft, "stale": stale}
    else:
        raise ValueError(f"未知阶段: {stage}")

    if config.get("pipeline.auto", False):
        _maybe_chain(stage, article_id)
    return result


def _maybe_chain(just_finished: str, article_id: str) -> None:
    nxt = {"collect": "create", "create": "review"}.get(just_finished)
    if nxt:
        dao.enqueue_job(nxt, article_id)


def mark_failed(article_id: str | None, error: str) -> None:
    if not article_id:
        return
    art = dao.get_article(article_id)
    if not art:
        return
    with db.transaction():
        art = dao.get_article(article_id)
        if art and art["status"] in ("COLLECTING", "CREATING", "REVIEWING"):
            dao.set_article_status(article_id, ArticleStatus.FAILED, error[:500])
    events.bus.publish(events.JOB_FAILED, article_id, error=error[:500])


# 阶段准入：当前状态 → 允许启动的阶段。含自身进行态以支持失败重试的幂等。
STAGE_ENTRY = {
    "collect": {ArticleStatus.NEW, ArticleStatus.COLLECTED, ArticleStatus.FAILED,
                ArticleStatus.COLLECTING},
    "create": {ArticleStatus.COLLECTED, ArticleStatus.DRAFTED, ArticleStatus.EDITING,
                ArticleStatus.CREATING, ArticleStatus.FAILED},
    "review": {ArticleStatus.DRAFTED, ArticleStatus.EDITING, ArticleStatus.REVIEWING,
               ArticleStatus.FINALIZED, ArticleStatus.DONE, ArticleStatus.PUBLISHING, ArticleStatus.FAILED},
}


def can_start(stage: str, status: ArticleStatus) -> bool:
    return status in STAGE_ENTRY.get(stage, set())
