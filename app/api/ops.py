"""审稿 / 发布导出 / 卡片 / 设置 / SSE / 健康检查路由。"""
from __future__ import annotations

import json
import queue as queue_mod
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..core import config, events
from ..core.models import ArticleStatus, DraftDoc
from ..pipeline import queue
from ..services import draft_service
from ..storage import dao
from ..storage import db

router = APIRouter(prefix="/api", tags=["ops"])


# ---------- 审稿 ----------

class ResolveItem(BaseModel):
    expected_revision: int | None = None
    action: str           # accept | dismiss | fix
    note: str | None = None


@router.get("/articles/{aid}/reviews/latest")
@db.read_snapshot
def latest_review(aid: str) -> dict:
    review = dao.latest_review(aid)
    if not review:
        raise HTTPException(404, "尚无审稿记录")
    from ..services.workflow import review_matches
    draft = dao.latest_draft(aid)
    current = bool(draft and review_matches(review, DraftDoc.model_validate_json(draft["doc_json"])))
    return {"review": review, "items": dao.list_review_items(review["id"]), "current": current,
            "content_changed": bool(draft and json.loads(review["scores_json"]).get("content_hash") !=
                                    draft_service.content_hash(DraftDoc.model_validate_json(draft["doc_json"]))),
            "coverage": json.loads(review["scores_json"]).get("coverage", "unknown")}


@router.get("/articles/{aid}/review-context")
@db.read_snapshot
def review_context(aid: str) -> dict:
    """Document and review from a single read snapshot for reactive panels."""
    from .drafts import _doc_view
    try:
        draft = _doc_view(aid)
    except ValueError:
        draft = None
    try:
        review = latest_review(aid)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        review = None
    return {"draft": draft, "review": review}


@router.post("/review-items/{item_id}/resolve")
def resolve_item(item_id: str, body: ResolveItem) -> dict:
    from ..storage import db
    item = db.query_one("SELECT * FROM review_items WHERE id=?", (item_id,))
    if not item:
        raise HTTPException(404, "条目不存在")
    with db.transaction():
        review = db.query_one("SELECT * FROM reviews WHERE id=?", (item["review_id"],))
        article_id = review["article_id"]
        doc, row = draft_service.get_doc(article_id)
        draft_service.check_revision(doc, body.expected_revision)
        from ..services.workflow import review_matches
        if not review_matches(review, doc):
            raise HTTPException(409, "审稿意见属于旧版本或迟到审稿，请重新审稿")
        if body.action in ("dismiss", "accept"):
            status = "dismissed" if body.action == "dismiss" else "accepted"
            dao.set_review_item_status(item_id, status, body.note)
            return {"ok": True, "status": status}
    if body.action == "fix":
        if not item["auto_fixable"] or not item["block_id"]:
            raise HTTPException(400, "该条目不支持 AI 修复")
        if not any(b.id == item["block_id"] for b in doc.blocks):
            raise HTTPException(409, "该意见对应的段落已删除，请重新审稿")
        from ..agents.creator import CreatorAgent
        agent = CreatorAgent()
        if not agent.llm_available():
            raise HTTPException(503, "未配置 LLM 渠道")
        new = doc.model_copy(deep=True)
        instruction = f"根据审稿意见修改：{item['message']}；建议：{item['suggestion']}"
        try:
            new = agent.regenerate_blocks(article_id, new, [item["block_id"]], instruction)
        except Exception as e:
            raise HTTPException(502, f"AI 修复失败: {e}")
        with db.transaction():
            saved = draft_service.save_new_version(new, origin="auto_fix")
            dao.set_review_item_status(item_id, "fixed", f"v{saved.version}", resolved_by="ai")
        return {"ok": True, "status": "fixed", "new_version": saved.version}
    raise HTTPException(400, "action 必须是 accept/dismiss/fix")


# ---------- 发布（导出） ----------

class Publish(BaseModel):
    platforms: list[str]


class RetryPublish(BaseModel):
    platform: str | None = None


@router.post("/articles/{aid}/publish/retry")
def retry_publish(aid: str, body: RetryPublish) -> dict:
    """Retry failed platforms against their original approved/configured snapshot."""
    from ..storage import db
    with db.transaction():
        failed = None
        seen = set()
        for job in dao.list_jobs(aid, limit=200):
            if job["type"] != "publish":
                continue
            payload = json.loads(job["payload_json"])
            requested = payload.get("platforms") or []
            # A later successful or in-flight attempt supersedes older failures.
            available = [p for p in requested if p not in seen]
            seen.update(requested)
            if body.platform in available and job["status"] in ("pending", "running"):
                return {"job_id": job["id"], "platforms": requested,
                        "snapshot_id": payload.get("snapshot_id")}
            if job["status"] == "failed":
                result = json.loads(job.get("result_json") or "{}")
                platforms = [p for p in result.get("failed_platforms", []) if p in available]
                if platforms and (not body.platform or body.platform in platforms):
                    failed = job, payload, platforms
                    break
        if not failed:
            raise HTTPException(404, "没有可重试的失败平台")
        job, payload, platforms = failed
        snapshot = dao.get_draft_by_id(payload.get("snapshot_id", ""))
        if not snapshot or snapshot["article_id"] != aid or snapshot["status"] != "finalized":
            raise HTTPException(409, "原定稿快照不存在")
        from ..services import human_review
        human_review.export_approval(aid, snapshot)
        payload["platforms"] = [body.platform] if body.platform else platforms
        payload["retry_of"] = job["id"]
        job_id = queue.enqueue("publish", aid, payload)
        return {"job_id": job_id, "platforms": payload["platforms"], "snapshot_id": snapshot["id"]}


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
    from ..storage import db
    from ..services import assets
    with db.transaction():
        draft = dao.latest_draft(aid)
        current = dao.get_article(aid)
        if not draft or draft["status"] != "finalized" or current["status"] not in ("FINALIZED", "DONE", "PUBLISHING"):
            raise HTTPException(409, "当前内容尚未定稿")
        doc = DraftDoc.model_validate_json(draft["doc_json"])
        from ..services import human_review
        approved_assets = human_review.export_approval(aid, draft)
        job_id = queue.enqueue("publish", aid, {"platforms": list(dict.fromkeys(platforms)),
                           "snapshot_id": draft["id"], "assets": approved_assets if approved_assets is not None else assets.manifest(doc),
                           "settings": config.all_settings()})
    return {"job_id": job_id, "platforms": platforms}


@router.get("/articles/{aid}/publish-jobs")
def publish_jobs(aid: str) -> dict:
    return {"jobs": dao.list_publish_jobs(aid)}


@router.get("/articles/{aid}/exports")
def list_exports(aid: str) -> dict:
    from ..storage import library
    root = library.exports_dir(aid)
    if not root.exists():
        return {"files": [], "lib_dir": str(library.article_dir(aid))}
    from ..services.file_access import export_directories, package_files
    files = [p.relative_to(config.data_dir().resolve()).as_posix()
             for d in export_directories(aid) for p in sorted(package_files(d))]
    return {"root": str(root), "files": files,
            "lib_dir": str(library.article_dir(aid))}


@router.post("/articles/{aid}/cards")
def gen_cards(aid: str, theme: str | None = None) -> dict:
    """单独出卡片 = 更新固定的小红书发布包。"""
    from ..services.publish.exporter import export_variants
    try:
        result = export_variants(aid, ["xhs"])
    except ValueError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(502, f"卡片渲染失败（Playwright/Chromium 缺失？）: {e}")
    if not result["ok"]:
        raise HTTPException(502, result["platforms"]["xhs"]["message"])
    cards_dir = Path(result["export_root"]) / "xhs" / "cards"
    files = sorted(cards_dir.glob("page-*.png"))
    return {"files": [str(p.relative_to(config.data_dir())) for p in files],
            "export_root": result["export_root"]}


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
            "llm_purposes": {p: llm_router.available(p) for p in config.get("llm.routing", {})},
            "searcher": get_searcher().name,
            "embedding_available": get_embedder().available}


@router.put("/settings")
def put_setting(body: SettingPut) -> dict:
    from ..core import settings_policy
    from ..storage import db
    try:
        value = settings_policy.value_for(body.key, body.value)
        with db.transaction():
            proposed = config._deep_merge(config.all_settings(), config._expand_flat({body.key: value}))
            settings_policy.validate(proposed)
            dao.set_setting(body.key, value)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    config.reload()
    from .. import logging_setup
    logging_setup.configure()
    # 日志持久化常驻（log.* 配置），dev.mode 仅控制设置页日志面板可见性，即时生效
    return {"ok": True}


# ---------- SSE / 健康 ----------

@router.post("/settings/reload-env")
def reload_env(request: Request) -> dict:
    from dataclasses import replace
    from ..core.environment import lock
    from ..services.http import close_clients, _cached_windows_proxy
    with lock:
        result = config.reload_env()
        # Retire idle pools; busy clients finish normally before closing.
        close_clients()
        _cached_windows_proxy.cache_clear()
        request.app.state.context = replace(request.app.state.context,
                                            settings=config.all_settings())
        result["services"] = get_settings()
    return result

@router.get("/sse")
def sse(request: Request):
    q = events.bus.subscribe()
    from ..services import team
    member_token = request.cookies.get("wenshu_member", "")
    team_mode = team.enabled()

    def stream():
        try:
            yield ": connected\n\n"
            while True:
                member = team.session(member_token) if team_mode else None
                if team_mode and not member:
                    return
                try:
                    msg = q.get(timeout=1 if team_mode else 15)
                    if team_mode and not (team.allowed(member, msg.get("article_id")) if msg.get("article_id") else member["role"] == "admin"):
                        continue
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                except queue_mod.Empty:
                    yield ": heartbeat\n\n"
        finally:
            events.bus.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/health")
def health() -> dict:
    return {"ok": True}


@router.get("/capabilities")
def capabilities():
    from ..services import team
    from ..services.llm import router as llm_router
    return {"team_mode": team.enabled(), "member": team.public(team.actor.get()) if team.actor.get() else None,
            "create_available": llm_router.available("create"), "review_available": llm_router.available("review")}


@router.get("/ready")
def ready(request: Request) -> dict:
    from ..storage import db
    runtime = getattr(request.app.state, "runtime", None)
    import sqlite3
    import shutil
    try:
        db.query_one("SELECT 1")
        queue_counts = db.query("SELECT status, COUNT(*) AS count FROM jobs GROUP BY status")
    except sqlite3.Error:
        raise HTTPException(503, "数据库暂不可用")
    workers_ok = not request.app.state.worker_enabled or bool(runtime and runtime.healthy())
    if not request.app.state.ready or not workers_ok:
        raise HTTPException(503, "服务未就绪")
    from ..services.readiness import storage_status
    from .. import logging_setup
    try:
        storage = storage_status({"data": config.data_dir(), "config": config.CONFIG_DIR,
                                  "logs": logging_setup.log_dir()})
    except (OSError, ValueError):
        raise HTTPException(503, "持久存储不可写或可用空间不足")
    return {"ok": True, "workers": len(runtime.threads) if runtime else 0,
            "queue": {r["status"]: r["count"] for r in queue_counts},
            "disk_free_mb": storage["data"]["free_mb"], "storage": storage,
            "event_sequence": events.bus.sequence, "event_dropped": events.bus.dropped}


# ---------- 开发者模式：日志可视化 + 成本监控 ----------

@router.get("/logs/tail")
def logs_tail(lines: int = 200) -> dict:
    from .. import logging_setup
    if not logging_setup.enabled():
        raise HTTPException(403, "开发者模式未开启（设置页 → 开发者模式）")
    return {"lines": logging_setup.tail(min(lines, 1000))}


_STAGE_GROUP = {"collector": "收集", "creator": "创作", "reviewer": "审稿"}


@router.get("/articles/{aid}/costs")
def article_costs(aid: str) -> dict:
    """API 费用监控：按环节聚合调用次数与 token（dev.mode 开启时前端展示）。"""
    from ..storage import db
    rows = db.query(
        "SELECT stage, prompt_tokens, completion_tokens, cost_est FROM llm_calls "
        "WHERE article_id=?", (aid,))
    by_stage: dict[str, dict] = {}
    for r in rows:
        stage = r["stage"] or ""
        group = next((v for k, v in _STAGE_GROUP.items() if stage.startswith(k)), "其他")
        g = by_stage.setdefault(group, {"calls": 0, "prompt_tokens": 0,
                                        "completion_tokens": 0, "cost_est": 0.0})
        g["calls"] += 1
        g["prompt_tokens"] += r["prompt_tokens"]
        g["completion_tokens"] += r["completion_tokens"]
        g["cost_est"] += r["cost_est"] or 0.0
        g["unknown_cost_calls"] = g.get("unknown_cost_calls", 0) + int(r["cost_est"] is None)
    for g in by_stage.values():
        g["cost_est"] = round(g["cost_est"], 6)
    total = {"calls": len(rows),
             "prompt_tokens": sum(r["prompt_tokens"] for r in rows),
             "completion_tokens": sum(r["completion_tokens"] for r in rows),
             "cost_est": round(sum(r["cost_est"] or 0.0 for r in rows), 6)}
    total["unknown_cost_calls"] = sum(r["cost_est"] is None for r in rows)
    return {"by_stage": by_stage, "total": total}
