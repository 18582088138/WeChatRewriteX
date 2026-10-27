"""任务队列：后台线程 + jobs 表持久化。重启后 pending/running 任务自动恢复。"""
from __future__ import annotations

import threading
import time

from ..core import events
from ..core.models import ArticleStatus
from ..storage import dao
from . import orchestrator

_handlers: dict[str, callable] = {}
_stop = threading.Event()
_worker_threads: list[threading.Thread] = []

MAX_ATTEMPTS = 2

# 双泳道（反馈 2：抓取与创作并行互不阻塞）：
# lane A = 抓取类（collect/ingest/deepsearch），lane B = 创作类（create/review/publish）
LANE_A = ("collect", "ingest", "deepsearch")
LANE_B = ("create", "review", "publish")


def register_defaults(llm=None) -> None:
    _handlers.update({
        "collect": lambda aid, payload: orchestrator.run_stage("collect", aid, llm),
        "create": lambda aid, payload: orchestrator.run_stage("create", aid, llm, payload),
        "review": lambda aid, payload: orchestrator.run_stage("review", aid, llm),
        "publish": _run_publish,
        "ingest": _run_ingest,
        "deepsearch": _run_deepsearch,
    })


def _run_deepsearch(article_id: str, payload: dict) -> dict:
    """深度搜索：基于已提取主题的新一轮检索，仅增量补充 reference（不改状态）。"""
    from ..agents.collector import CollectorAgent
    return CollectorAgent().deep_search(article_id)


def _run_ingest(article_id: str | None, payload: dict) -> dict:
    """批量链接抓取（单链接失败不阻断，逐个记录结果）。"""
    from ..services import ingest as ingest_svc
    urls = payload.get("urls", [])
    results = []
    for i, url in enumerate(urls, 1):
        events.bus.publish(events.STAGE_PROGRESS, article_id, stage="ingest",
                           message=f"抓取链接 {i}/{len(urls)}：{url[:60]}")
        try:
            r = ingest_svc.ingest_url(article_id, url, payload.get("ref_type"))
            results.append({"url": url, "ok": True, "title": r.get("title"),
                            "material_id": r["material_id"]})
        except Exception as e:
            results.append({"url": url, "ok": False, "error": str(e)[:200]})
    if article_id and results:
        events.bus.publish(events.MATERIAL_INGESTED, article_id, count=len(results))
    return {"results": results}


def _run_publish(article_id: str, payload: dict) -> dict:
    from ..core.models import ArticleStatus
    from ..services.publish.exporter import export_variants
    platforms = payload.get("platforms") or ["wechat_mp", "xhs", "weibo", "x"]
    art = dao.get_article(article_id)
    if art and ArticleStatus(art["status"]) == ArticleStatus.FINALIZED:
        orchestrator._set_status(article_id, ArticleStatus.PUBLISHING)
    result = export_variants(article_id, platforms)
    art = dao.get_article(article_id)
    if art and ArticleStatus(art["status"]) == ArticleStatus.PUBLISHING:
        orchestrator._set_status(article_id, ArticleStatus.DONE)
    events.bus.publish(events.PUBLISH_FINISHED, article_id, platforms=platforms)
    return result


def enqueue(job_type: str, article_id: str | None = None, payload: dict | None = None) -> str:
    jid = dao.enqueue_job(job_type, article_id, payload)
    events.bus.publish("job.enqueued", article_id, job_id=jid, job_type=job_type)
    return jid


def _loop(lane_types: tuple[str, ...]) -> None:
    while not _stop.is_set():
        job = None
        try:
            job = dao.claim_job(lane_types)
        except Exception:
            time.sleep(1)
            continue
        if job is None:
            time.sleep(0.5)
            continue
        handler = _handlers.get(job["type"])
        if not handler:
            dao.fail_job(job["id"], f"无处理器: {job['type']}")
            continue
        from .. import logging_setup
        logging_setup.log("info", "任务开始 %s (article=%s)", job["type"], job["article_id"])
        try:
            import json
            payload = json.loads(job.get("payload_json") or "{}")
            result = handler(job["article_id"], payload)
            dao.finish_job(job["id"], result)
            logging_setup.log("info", "任务完成 %s (article=%s)", job["type"], job["article_id"])
        except Exception as e:
            requeue = job["attempts"] < MAX_ATTEMPTS
            dao.fail_job(job["id"], str(e)[:500], requeue=requeue)
            logging_setup.log("error", "任务失败 %s (article=%s): %s",
                              job["type"], job["article_id"], str(e)[:300],
                              exc_info=True)
            if not requeue:
                orchestrator.mark_failed(job["article_id"], str(e))


def recover_interrupted() -> None:
    """启动时把 running 态任务重置回 pending（进程崩溃恢复）。"""
    from ..storage import db
    db.execute("UPDATE jobs SET status='pending' WHERE status='running'")


def start(llm=None) -> None:
    register_defaults(llm)
    recover_interrupted()
    if any(t.is_alive() for t in _worker_threads):
        return
    _stop.clear()
    _worker_threads.clear()
    for name, lane in (("lane-fetch", LANE_A), ("lane-create", LANE_B)):
        t = threading.Thread(target=_loop, args=(lane,), name=f"pipeline-{name}", daemon=True)
        _worker_threads.append(t)
        t.start()


def stop() -> None:
    _stop.set()


def progress(article_id: str) -> dict:
    """文章当前进度快照（列表页用）：运行中/排队的阶段 + 最近结果。"""
    jobs = dao.list_jobs(article_id, limit=10)
    running = [j["type"] for j in jobs if j["status"] == "running"]
    pending = [j["type"] for j in jobs if j["status"] == "pending"]
    last_done = next((j for j in jobs if j["status"] == "done"), None)
    return {"running": running, "pending": pending,
            "last_done": last_done["type"] if last_done else None}
