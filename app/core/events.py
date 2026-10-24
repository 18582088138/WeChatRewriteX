"""进程内事件总线：SSE 订阅 + hooks 触发共用。事件名见 docs/design/01。"""
from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable

ARTICLE_ADDED = "article.added"
COLLECT_STARTED = "collect.started"
COLLECT_FINISHED = "collect.finished"
REWRITE_STARTED = "rewrite.started"
REWRITE_FINISHED = "rewrite.finished"
REVIEW_STARTED = "review.started"
REVIEW_FINISHED = "review.finished"
DRAFT_SAVED = "draft.saved"
DRAFT_FINALIZED = "draft.finalized"
PUBLISH_FINISHED = "publish.finished"
JOB_FAILED = "job.failed"
MATERIAL_INGESTED = "material.ingested"
STATUS_CHANGED = "status.changed"


class EventBus:
    def __init__(self) -> None:
        self._subs: list[queue.Queue] = []
        self._hooks: dict[str, list[Callable[[dict], None]]] = {}
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=200)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def on(self, event: str, fn: Callable[[dict], None]) -> None:
        self._hooks.setdefault(event, []).append(fn)

    def publish(self, event: str, article_id: str | None = None, **payload: Any) -> None:
        msg = {"type": event, "article_id": article_id, "ts": time.time(), **payload}
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass
        for fn in self._hooks.get(event, []):
            try:
                fn(msg)
            except Exception:
                pass  # hook 失败不影响主流程


bus = EventBus()
