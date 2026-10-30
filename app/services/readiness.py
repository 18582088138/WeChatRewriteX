"""Storage readiness checks; liveness never depends on external model services."""
import os
from pathlib import Path
import shutil
import tempfile


def minimum_free_mb() -> int:
    value = int(os.environ.get("WENSHU_MIN_FREE_MB", "64"))
    if value < 1:
        raise ValueError("WENSHU_MIN_FREE_MB 必须是正整数")
    return value


def storage_status(paths: dict[str, Path]) -> dict:
    threshold = minimum_free_mb()
    result = {}
    for label, path in paths.items():
        free = shutil.disk_usage(path).free // (1024 * 1024)
        if free < threshold:
            raise OSError(f"{label} 可用空间低于 {threshold} MB")
        # os.access cannot reliably detect read-only mounts or Windows ACLs.
        with tempfile.TemporaryFile(dir=path) as probe:
            probe.write(b"ready")
            probe.flush()
        result[label] = {"writable": True, "free_mb": free}
    return result
