"""任务队列：后台线程 + jobs 表持久化。重启后 pending/running 任务自动恢复。"""
from __future__ import annotations

import threading
import time

from ..core import events
from ..core.models import ArticleStatus
from ..storage import dao
from . import orchestrator

_handlers: dict[str, callable] = {}
_worker_thread: threading.Thread | None = None
_stop = threading.Event()

MAX_ATTEMPTS = 2


def register_defaults(llm=None) -> None:
    _handlers.update({
        "collect": lambda aid, payload: orchestrator.run_stage("collect", aid, llm),
        "rewrite": lambda aid, payload: orchestrator.run_stage("rewrite", aid, llm),
        "review": lambda aid, payload: orchestrator.run_stage("review", aid, llm),
        "publish": _run_publish,
    })


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


def _loop() -> None:
    while not _stop.is_set():
        job = None
        try:
            job = dao.claim_job()
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
        try:
            import json
            payload = json.loads(job.get("payload_json") or "{}")
            result = handler(job["article_id"], payload)
            dao.finish_job(job["id"], result)
        except Exception as e:
            requeue = job["attempts"] < MAX_ATTEMPTS
            dao.fail_job(job["id"], str(e)[:500], requeue=requeue)
            if not requeue:
                orchestrator.mark_failed(job["article_id"], str(e))


def recover_interrupted() -> None:
    """启动时把 running 态任务重置回 pending（进程崩溃恢复）。"""
    from ..storage import db
    db.execute("UPDATE jobs SET status='pending' WHERE status='running'")


def start(llm=None) -> None:
    global _worker_thread
    register_defaults(llm)
    recover_interrupted()
    if _worker_thread and _worker_thread.is_alive():
        return
    _stop.clear()
    _worker_thread = threading.Thread(target=_loop, name="pipeline-worker", daemon=True)
    _worker_thread.start()


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
