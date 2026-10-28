"""Application boundary for finalization and review validity."""
from __future__ import annotations

import json

from ..core import config, events
from ..core.models import ArticleStatus, DraftDoc
from ..storage import dao, db
from . import draft_service


def review_matches(review: dict | None, doc: DraftDoc) -> bool:
    if not review:
        return False
    scores = json.loads(review.get("scores_json") or "{}")
    # Legacy reviews require rerun; version equality alone is insufficient.
    return scores.get("content_hash") == draft_service.content_hash(doc)


def finalize(article_id: str, force: bool = False, expected_version: int | None = None) -> dict:
    with db.transaction():
        art = dao.get_article(article_id)
        if not art:
            raise ValueError("文章不存在")
        doc, row = draft_service.get_doc(article_id)
        if expected_version is not None and doc.version != expected_version:
            raise draft_service.VersionConflict("草稿已更新，请刷新后重试")
        cur = ArticleStatus(art["status"])
        if cur in (ArticleStatus.FINALIZED, ArticleStatus.DONE) and row["status"] == "finalized":
            return {"ok": True, "version": doc.version, "forced_blockers": 0,
                    "already_finalized": True}
        if cur not in (ArticleStatus.DRAFTED, ArticleStatus.REVIEWED, ArticleStatus.EDITING):
            raise ValueError(f"当前状态 {cur.value} 不允许定稿")
        review = dao.latest_review(article_id)
        matching = review_matches(review, doc)
        scores = json.loads(review["scores_json"]) if review else {}
        coverage = scores.get("coverage", "missing") if matching else "stale"
        blockers = dao.pending_blockers(review["id"]) if matching else 0
        reasons = []
        if not matching:
            reasons.append("当前内容尚未审稿或审稿已过期")
        elif coverage not in ("full", "rules_only"):
            reasons.append("AI 审稿未完成")
        if blockers and config.get("review.block_on_blocker", True):
            reasons.append(f"存在 {blockers} 个未处理 blocker")
        if reasons and not force:
            raise ValueError("；".join(reasons))
        cp = draft_service.save_checkpoint(article_id, "finalized", "finalized",
                 note="定稿快照" + ("；强制：" + "；".join(reasons) if reasons else ""))
        dao.set_article_status(article_id, ArticleStatus.FINALIZED)
        db.after_commit(lambda: events.bus.publish(events.DRAFT_FINALIZED, article_id,
                       version=cp.version, forced=bool(force and reasons)))
        return {"ok": True, "version": cp.version,
                "forced_blockers": blockers if force else 0,
                "review_coverage": coverage, "forced_reasons": reasons if force else []}
