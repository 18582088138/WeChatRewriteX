"""审稿 / 发布导出 / 卡片 / 设置 / SSE / 健康检查路由。"""
from __future__ import annotations

import json
import queue as queue_mod
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..core import config, events
from ..core.models import ArticleStatus, DraftDoc
from ..pipeline import queue
from ..services import draft_service
from ..storage import dao

router = APIRouter(prefix="/api", tags=["ops"])


# ---------- 审稿 ----------

class ResolveItem(BaseModel):
    action: str           # accept | dismiss | fix
    note: str | None = None


@router.get("/articles/{aid}/reviews/latest")
def latest_review(aid: str) -> dict:
    review = dao.latest_review(aid)
    if not review:
        raise HTTPException(404, "尚无审稿记录")
    return {"review": review, "items": dao.list_review_items(review["id"])}


@router.post("/review-items/{item_id}/resolve")
def resolve_item(item_id: str, body: ResolveItem) -> dict:
    from ..storage import db
    item = db.query_one("SELECT * FROM review_items WHERE id=?", (item_id,))
    if not item:
        raise HTTPException(404, "条目不存在")
    if body.action == "dismiss":
        dao.set_review_item_status(item_id, "dismissed", body.note)
        return {"ok": True, "status": "dismissed"}
    if body.action == "accept":
        dao.set_review_item_status(item_id, "accepted", body.note)
        return {"ok": True, "status": "accepted"}
    if body.action == "fix":
        if not item["auto_fixable"] or not item["block_id"]:
            raise HTTPException(400, "该条目不支持 AI 修复")
        review = db.query_one("SELECT * FROM reviews WHERE id=?", (item["review_id"],))
        article_id = review["article_id"]
        doc, row = draft_service.get_doc(article_id)
        from ..agents.rewriter import RewriterAgent
        agent = RewriterAgent()
        if not agent.llm_available():
            raise HTTPException(503, "未配置 LLM 渠道")
        new = doc.model_copy(deep=True)
        instruction = f"根据审稿意见修改：{item['message']}；建议：{item['suggestion']}"
        try:
            new = agent.regenerate_blocks(article_id, new, [item["block_id"]], instruction)
        except Exception as e:
            raise HTTPException(502, f"AI 修复失败: {e}")
        saved = draft_service.save_new_version(new, origin="auto_fix")
        dao.set_review_item_status(item_id, "fixed", f"v{saved.version}", resolved_by="ai")
        return {"ok": True, "status": "fixed", "new_version": saved.version}
    raise HTTPException(400, "action 必须是 accept/dismiss/fix")


# ---------- 发布（导出） ----------

class Publish(BaseModel):
    platforms: list[str]


@router.post("/articles/{aid}/publish")
def publish(aid: str, body: Publish) -> dict:
    art = dao.get_article(aid)
    if not art:
        raise HTTPException(404, "文章不存在")
    if ArticleStatus(art["status"]) not in (ArticleStatus.FINALIZED, ArticleStatus.DONE,
                                            ArticleStatus.PUBLISHING):
        raise HTTPException(409, "请先定稿再发布")
    platforms = [p for p in body.platforms if p in ("wechat_mp", "xhs", "weibo", "x")]
    if not platforms:
        raise HTTPException(400, "platforms 为空或含未知平台")
    job_id = queue.enqueue("publish", aid, {"platforms": platforms})
    return {"job_id": job_id, "platforms": platforms}


@router.get("/articles/{aid}/publish-jobs")
def publish_jobs(aid: str) -> dict:
    return {"jobs": dao.list_publish_jobs(aid)}


@router.get("/articles/{aid}/exports")
def list_exports(aid: str) -> dict:
    root = config.data_dir() / "exports" / aid
    if not root.exists():
        return {"files": []}
    files = [str(p.relative_to(config.data_dir())) for p in sorted(root.rglob("*"))
             if p.is_file()]
    return {"root": str(root), "files": files}


@router.post("/articles/{aid}/cards")
def gen_cards(aid: str, theme: str | None = None) -> dict:
    from ..services.cards.render import CardRenderError, render_cards
    try:
        paths = render_cards(aid, theme)
    except CardRenderError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(502, f"卡片渲染失败（Playwright 是否已 install chromium？）: {e}")
    return {"files": [str(p.relative_to(config.data_dir())) for p in paths]}


# ---------- 设置 ----------

class SettingPut(BaseModel):
    key: str
    value: object


@router.get("/settings")
def get_settings() -> dict:
    from ..services.llm import router as llm_router
    from ..services.embed.embedder import get_embedder
    from ..services.search.registry import get_searcher
    channels = [{"name": c["name"], "provider": c["provider"],
                 "configured": bool(config.get_env(c.get("env_key", "")))}
                for c in config.get("llm.channels", [])]
    return {"settings": config.all_settings(), "channels": channels,
            "llm_available": llm_router.available(),
            "searcher": get_searcher().name,
            "embedding_available": get_embedder().available}


@router.put("/settings")
def put_setting(body: SettingPut) -> dict:
    if body.key.startswith(("llm.channels",)):   # 渠道含密钥引用，走 yaml 不走 UI
        raise HTTPException(400, "llm.channels 请直接编辑 config/settings.yaml")
    dao.set_setting(body.key, body.value)
    config.reload()
    return {"ok": True}


# ---------- SSE / 健康 ----------

@router.get("/sse")
def sse():
    q = events.bus.subscribe()

    def stream():
        try:
            yield ": connected\n\n"
            while True:
                try:
                    msg = q.get(timeout=15)
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                except queue_mod.Empty:
                    yield ": heartbeat\n\n"
        finally:
            events.bus.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/health")
def health() -> dict:
    return {"ok": True}
