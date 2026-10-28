"""任务队列：后台线程 + jobs 表持久化。重启后 pending/running 任务自动恢复。"""
from __future__ import annotations

import threading
import time

from ..core import events
from ..core.models import ArticleStatus
from ..storage import dao
from . import orchestrator

_handlers: dict[str, callable] = {}
_lifecycle_lock = threading.RLock()
_runtime = None
_users = 0


class WorkerRuntime:
    def __init__(self, llm=None):
        from ..core.config import data_dir
        from .runtime_lock import RuntimeLock
        self.guard = RuntimeLock(data_dir()).acquire()
        self.stop_event = threading.Event()
        self.threads = []
        try:
            from ..storage import db
            from ..core import config
            db.init_db()
            config.set_db_overlay(dao.db_settings)
            register_defaults(llm)
            self.handlers = dict(_handlers)
            recover_interrupted()
        except BaseException:
            self.guard.close()
            raise

    def healthy(self):
        return not self.stop_event.is_set() and len(self.threads) == 2 and all(t.is_alive() for t in self.threads)


MAX_ATTEMPTS = 2

# 双泳道（反馈 2：抓取与创作并行互不阻塞）：
# lane A = 抓取类（collect/ingest），lane B = 创作类（create/review/publish）
# V1.12：deepsearch（扩搜/深度搜索）已下线
LANE_A = ("collect", "ingest")
LANE_B = ("create", "review", "publish")


def register_defaults(llm=None) -> None:
    _handlers.update({
        "collect": lambda aid, payload: orchestrator.run_stage("collect", aid, llm),
        "create": lambda aid, payload: orchestrator.run_stage("create", aid, llm, payload),
        "review": lambda aid, payload: orchestrator.run_stage("review", aid, llm, payload),
        "publish": _run_publish,
        "ingest": _run_ingest,
    })


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
    from ..storage import db
    with db.transaction():
        art = dao.get_article(article_id)
        head = dao.latest_draft(article_id)
        if art and head and art["status"] in ("FINALIZED", "DONE") and (not payload.get("snapshot_id") or head["id"] == payload["snapshot_id"]):
            dao.set_article_status(article_id, ArticleStatus.PUBLISHING)
    from ..core import config
    try:
        with config.using_snapshot(payload.get("settings") or config.all_settings()):
            result = export_variants(article_id, platforms, payload.get("snapshot_id"),
                                     payload.get("assets"))
    except BaseException:
        with db.transaction():
            art = dao.get_article(article_id)
            if art and art["status"] == "PUBLISHING":
                dao.set_article_status(article_id, ArticleStatus.FINALIZED)
        raise
    from ..storage import db
    with db.transaction():
        art = dao.get_article(article_id)
        head = dao.latest_draft(article_id)
        if art and head and art["status"] == "PUBLISHING" and head["id"] == result["snapshot_id"]:
            # Export failure does not revoke content approval.
            dao.set_article_status(article_id, ArticleStatus.DONE if result["ok"] else ArticleStatus.FINALIZED)
    events.bus.publish(events.PUBLISH_FINISHED, article_id, platforms=platforms,
                       status=result["status"], failed_platforms=result["failed_platforms"])
    return result


def enqueue(job_type: str, article_id: str | None = None, payload: dict | None = None) -> str:
    jid = dao.enqueue_job(job_type, article_id, payload)
    from ..storage import db
    db.after_commit(lambda: events.bus.publish("job.enqueued", article_id, job_id=jid, job_type=job_type))
    return jid


def _loop(runtime: WorkerRuntime, lane_types: tuple[str, ...]) -> None:
    while not runtime.stop_event.is_set():
        job = None
        try:
            job = dao.claim_job(lane_types)
        except Exception:
            from .. import logging_setup
            logging_setup.log("error", "Queue claim failed", exc_info=True)
            runtime.stop_event.wait(1)
            continue
        if job is None:
            runtime.stop_event.wait(0.5)
            continue
        handler = runtime.handlers.get(job["type"])
        if not handler:
            dao.fail_job(job["id"], f"无处理器: {job['type']}")
            continue
        from .. import logging_setup
        logging_setup.log("info", "任务开始 %s (article=%s)", job["type"], job["article_id"])
        from ..core.execution import context
        ctx_token = context.set({"job_id": job["id"], "article_id": job["article_id"],
                                 "attempt": job["attempts"], "stage": job["type"]})
        try:
            import json
            payload = json.loads(job.get("payload_json") or "{}")
            payload["_job_id"] = job["id"]
            result = handler(job["article_id"], payload)
            if isinstance(result, dict) and result.get("status") in ("FAILED", "PARTIAL_FAILED"):
                from ..storage import db
                with db.transaction():
                    dao.fail_job(job["id"], "导出失败平台: " + ", ".join(result["failed_platforms"]))
                    db.execute("UPDATE jobs SET result_json=? WHERE id=?", (json.dumps(result, ensure_ascii=False), job["id"]))
            else:
                dao.finish_job(job["id"], result)
            logging_setup.log("error" if isinstance(result, dict) and result.get("ok") is False else "info",
                              "任务执行结束 %s (article=%s, result=%s)", job["type"], job["article_id"],
                              result.get("status", "done") if isinstance(result, dict) else "done")
        except Exception as e:
            from ..services.draft_service import VersionConflict
            from ..core.statemachine import InvalidTransition
            requeue = job["attempts"] < MAX_ATTEMPTS and not isinstance(e, (ValueError, VersionConflict, InvalidTransition))
            dao.fail_job(job["id"], str(e)[:500], requeue=requeue)
            logging_setup.log("error", "任务失败 %s (article=%s): %s",
                              job["type"], job["article_id"], str(e)[:300],
                              exc_info=True)
            if not requeue:
                if job["type"] != "publish":
                    orchestrator.mark_failed(job["article_id"], str(e))
        finally:
            context.reset(ctx_token)


def recover_interrupted() -> None:
    """启动时把 running 态任务重置回 pending（进程崩溃恢复）。"""
    from ..storage import db
    db.execute("UPDATE jobs SET status='pending' WHERE status='running'")


def start(llm=None) -> WorkerRuntime:
    global _runtime, _users
    with _lifecycle_lock:
        if _runtime and _runtime.healthy():
            _users += 1
            return _runtime
        if _runtime and any(t.is_alive() for t in _runtime.threads):
            raise RuntimeError("后台任务仍在停止中，不能重新启动")
        if _runtime:
            _runtime.guard.close()
        runtime = WorkerRuntime(llm)
        _runtime, _users = runtime, 1
        try:
            for name, lane in (("lane-fetch", LANE_A), ("lane-create", LANE_B)):
                thread = threading.Thread(target=_loop, args=(runtime, lane),
                                          name=f"pipeline-{name}", daemon=True)
                runtime.threads.append(thread)
                thread.start()
        except BaseException:
            runtime.stop_event.set()
            for thread in runtime.threads:
                thread.join(timeout=2)
            runtime.guard.close()
            _runtime, _users = None, 0
            raise
        return runtime


def stop(timeout: float = 10) -> None:
    global _runtime, _users
    with _lifecycle_lock:
        if not _runtime:
            return
        _users = max(0, _users - 1)
        if _users:
            return
        runtime = _runtime
        runtime.stop_event.set()
        deadline = time.monotonic() + timeout
        for thread in runtime.threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        if any(t.is_alive() for t in runtime.threads):
            from .. import logging_setup
            logging_setup.log("error", "Shutdown deadline exceeded; retaining ownership until process exits")
        else:
            runtime.guard.close()
            _runtime = None


def progress(article_id: str) -> dict:
    """文章当前进度快照（列表页用）：运行中/排队的阶段 + 最近结果。"""
    jobs = dao.list_jobs(article_id, limit=10)
    running = [j["type"] for j in jobs if j["status"] == "running"]
    pending = [j["type"] for j in jobs if j["status"] == "pending"]
    last_done = next((j for j in jobs if j["status"] == "done"), None)
    return {"running": running, "pending": pending,
            "last_done": last_done["type"] if last_done else None}


def progress_many(article_ids: list[str]) -> dict:
    from ..storage import db
    if not article_ids:
        return {}
    marks = ",".join("?" for _ in article_ids)
    rows = db.query("SELECT * FROM (SELECT type, status, article_id, "
                    "ROW_NUMBER() OVER(PARTITION BY article_id ORDER BY created_at DESC, rowid DESC) AS rank "
                    f"FROM jobs WHERE article_id IN ({marks})) WHERE rank<=10 ORDER BY article_id, rank",
                    tuple(article_ids))
    out = {aid: {"running": [], "pending": [], "last_done": None} for aid in article_ids}
    for row in rows:
        snapshot = out[row["article_id"]]
        if row["status"] in ("running", "pending"):
            snapshot[row["status"]].append(row["type"])
        elif row["status"] == "done" and snapshot["last_done"] is None:
            snapshot["last_done"] = row["type"]
    return out
