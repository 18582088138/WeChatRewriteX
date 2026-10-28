"""Per-request/job context, without module-level mutable execution state."""
from contextvars import ContextVar

context = ContextVar("execution_context", default={})


def operation_id() -> str | None:
    return context.get().get("job_id")
