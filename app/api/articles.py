"""文章与流水线控制路由。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core import config, events
from ..core.models import ArticleStatus
from ..core.statemachine import ui_status
from ..pipeline import orchestrator, queue
from ..storage import dao, db

router = APIRouter(prefix="/api/articles", tags=["articles"])
jobs_router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class CreateArticle(BaseModel):
    url: str
    user_notes: str = ""
    style_pack: str | None = None
    target_word_count: int | None = None
    auto_collect: bool = True


class Finalize(BaseModel):
    force: bool = False


def _shape(row: dict) -> dict:
    out = dict(row)
    st = ArticleStatus(row["status"])
    out["ui_status"] = ui_status(st)
    out["progress"] = queue.progress(row["id"])
    return out


@router.post("")
def create_article(body: CreateArticle) -> dict:
    if not body.url.strip():
        raise HTTPException(400, "url 不能为空")
    art = dao.create_article(body.url.strip(), user_notes=body.user_notes,
                             style_pack=body.style_pack,
                             target_word_count=body.target_word_count)
    events.bus.publish(events.ARTICLE_ADDED, art["id"])
    job_id = None
    if body.auto_collect:
        job_id = queue.enqueue("collect", art["id"])
    return {"article": _shape(art), "collect_job": job_id}


@router.get("")
def list_articles(status: str | None = None, q: str | None = None) -> dict:
    rows = dao.list_articles(status_ui=status if status in ("New", "Process", "Done") else None,
                             q=q)
    return {"articles": [_shape(r) for r in rows]}


@router.get("/{aid}")
def article_detail(aid: str) -> dict:
    art = dao.get_article(aid)
    if not art:
        raise HTTPException(404, "文章不存在")
    out = _shape(art)
    out["materials_count"] = len(dao.list_materials(article_id=aid))
    out["versions"] = dao.list_drafts(aid)
    out["latest_review"] = dao.latest_review(aid)
    out["publish_jobs"] = dao.list_publish_jobs(aid)
    import json as _json
    try:
        out["selected_material_ids"] = _json.loads(art.get("selected_json") or "[]")
    except Exception:
        out["selected_material_ids"] = []
    return out


class Advance(BaseModel):
    stage: str          # collect | create | review
    selected_material_ids: list[str] | None = None   # create 阶段: 勾选参与创作的素材


class Selection(BaseModel):
    material_ids: list[str]


@router.put("/{aid}/selection")
def set_selection(aid: str, body: Selection) -> dict:
    """保存创作会话的勾选素材集合（左侧素材浏览窗口数据源）。"""
    if not dao.get_article(aid):
        raise HTTPException(404, "文章不存在")
    import json
    db.execute("UPDATE articles SET selected_json=? WHERE id=?",
               (json.dumps(body.material_ids, ensure_ascii=False), aid))
    return {"ok": True, "count": len(body.material_ids)}


@router.post("/{aid}/advance")
def advance(aid: str, body: Advance) -> dict:
    art = dao.get_article(aid)
    if not art:
        raise HTTPException(404, "文章不存在")
    if body.stage not in ("collect", "create", "review"):
        raise HTTPException(400, "stage 必须是 collect/create/review")
    status = ArticleStatus(art["status"])
    if not orchestrator.can_start(body.stage, status):
        raise HTTPException(409, f"当前状态 {status.value} 不能启动 {body.stage}")
    if body.stage == "create":
        texts = [m for m in dao.list_materials(article_id=aid, kind="text")
                 if m["fetch_status"] == "ok"]
        if not texts:
            raise HTTPException(409, "素材库为空，先完成收集")
    if body.stage == "review" and not dao.latest_draft(aid):
        raise HTTPException(409, "没有草稿，先完成创作")
    payload = {}
    if body.selected_material_ids:
        payload["selected_material_ids"] = body.selected_material_ids
    job_id = queue.enqueue(body.stage, aid, payload)
    return {"job_id": job_id, "stage": body.stage}


@router.post("/{aid}/finalize")
def finalize(aid: str, body: Finalize) -> dict:
    art = dao.get_article(aid)
    if not art:
        raise HTTPException(404, "文章不存在")
    draft = dao.latest_draft(aid)
    if not draft:
        raise HTTPException(409, "没有草稿")
    review = dao.latest_review(aid)
    blockers = 0
    if review:
        blockers = dao.pending_blockers(review["id"])
    if blockers and not body.force and config.get("review.block_on_blocker", True):
        raise HTTPException(409, f"存在 {blockers} 个未处理 blocker，禁止定稿")
    # 定稿 = 落一个稀疏 checkpoint（块级增量版本下，checkpoint 只在 创建/定稿/回滚 时产生）
    from ..services import draft_service
    cp = draft_service.save_checkpoint(aid, origin="finalized", status="finalized")
    from ..core.statemachine import transition
    cur = ArticleStatus(art["status"])
    if cur == ArticleStatus.REVIEWED:
        dao.set_article_status(aid, ArticleStatus.EDITING)
        cur = ArticleStatus.EDITING
    transition(cur, ArticleStatus.FINALIZED)
    dao.set_article_status(aid, ArticleStatus.FINALIZED)
    events.bus.publish(events.DRAFT_FINALIZED, aid, version=(cp.version if cp else draft["version"]),
                       forced=bool(body.force and blockers))
    return {"ok": True, "version": (cp.version if cp else draft["version"]),
            "forced_blockers": blockers if body.force else 0}


@router.post("/{aid}/reopen")
def reopen(aid: str) -> dict:
    art = dao.get_article(aid)
    if not art:
        raise HTTPException(404, "文章不存在")
    cur = ArticleStatus(art["status"])
    if cur not in (ArticleStatus.FINALIZED, ArticleStatus.DONE):
        raise HTTPException(409, "仅定稿/完成后可回炉编辑")
    dao.set_article_status(aid, ArticleStatus.EDITING)
    return {"ok": True}


@router.post("/{aid}/deepsearch")
def deepsearch(aid: str) -> dict:
    """深度搜索（反馈 3.3）：基于已提取主题的新一轮检索，仅增量补充 reference。"""
    art = dao.get_article(aid)
    if not art:
        raise HTTPException(404, "文章不存在")
    if ArticleStatus(art["status"]) not in (ArticleStatus.COLLECTED, ArticleStatus.DRAFTED,
                                            ArticleStatus.REVIEWED, ArticleStatus.EDITING):
        raise HTTPException(409, "请先完成初次收集")
    job_id = queue.enqueue("deepsearch", aid)
    return {"job_id": job_id}


@jobs_router.get("")
def list_jobs(article_id: str | None = None, limit: int = 50) -> dict:
    return {"jobs": dao.list_jobs(article_id, limit)}
