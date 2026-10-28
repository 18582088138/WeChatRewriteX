"""OS-owned lock: single process per data root, released automatically on crash."""
from pathlib import Path
import os


class RuntimeLock:
    def __init__(self, root: Path):
        self.path = root / ".worker.lock"
        self.file = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise RuntimeError(f"数据目录已有运行实例：{self.path.parent}。请使用单个 ASGI worker。") from exc
        return self

    def close(self):
        if self.file is not None:
            self.file.close()
            self.file = None
