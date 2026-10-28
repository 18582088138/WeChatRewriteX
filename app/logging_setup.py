"""运行日志：常驻持久化，落地 <运行根>/log（默认，配置 `log.path` 可改）。

- 级别仅 INFO / ERROR 两档，配置 `log.level` 切换（默认 INFO）；
- 按日期拆分（TimedRotatingFileHandler，午夜轮转，保留 `log.keep_days` 天）；
- 格式统一：`时间 级别 [模块] 内容`；ERROR 自动带异常堆栈；
- 开发者模式（`dev.mode`）只控制设置页的日志面板可见性，不再控制是否写文件。
"""
from __future__ import annotations

import logging
import sys
import threading
from collections import deque
from .core.execution import context
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from .core.config import RUNTIME_ROOT

_HANDLER_NAME = "wenshu-file"
_logger = logging.getLogger("wenshu")


def log_dir() -> Path:
    from .core import config
    p = Path(str(config.get("log.path", "log")))
    return p if p.is_absolute() else RUNTIME_ROOT / p


def _level() -> int:
    from .core import config
    lv = str(config.get("log.level", "INFO")).upper()
    return logging.ERROR if lv == "ERROR" else logging.INFO   # 只保留 INFO/ERROR 两档


def configure(*_args, **_kwargs) -> None:
    """挂载日期轮转文件 handler（幂等；参数忽略，兼容旧调用签名）。"""
    existing = [h for h in _logger.handlers if h.name == _HANDLER_NAME]
    if existing:
        _logger.setLevel(_level())
        for handler in existing:
            handler.backupCount = int(_keep_days())
        return
    d = log_dir()
    d.mkdir(parents=True, exist_ok=True)
    h = TimedRotatingFileHandler(d / "wenshu.log", when="midnight", interval=1,
                                 backupCount=int(_keep_days()), encoding="utf-8")
    h.name = _HANDLER_NAME
    class ContextFilter(logging.Filter):
        def filter(self, record):
            values = context.get()
            record.execution = " ".join(f"{k}={v}" for k, v in values.items() if v is not None)
            return True
    h.addFilter(ContextFilter())
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(execution)s %(message)s"))
    _logger.addHandler(h)
    _logger.setLevel(_level())
    _logger.propagate = False
    _install_excepthooks()
    _logger.info("日志持久化已启用 → %s（级别 %s，按日期拆分）", d,
                 logging.getLevelName(_level()))


def _keep_days() -> int:
    try:
        from .core import config
        return int(config.get("log.keep_days", 14))
    except Exception:
        return 14


def _install_excepthooks() -> None:
    """未捕获异常（主线程 + 工作线程）一律落 ERROR 日志带堆栈。"""
    def _sys_hook(exc_type, exc, tb):
        _logger.error("未捕获异常", exc_info=(exc_type, exc, tb))
    def _thread_hook(args):
        _logger.error("线程 %s 未捕获异常", args.thread.name if args.thread else "?",
                      exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    sys.excepthook = _sys_hook
    threading.excepthook = _thread_hook


def enabled() -> bool:
    """日志面板（开发者模式）是否可见——与文件持久化无关。"""
    from .core import config
    return bool(config.get("dev.mode", False))


def log(level: str, msg: str, *args, exc_info: bool = False) -> None:
    """业务打点入口：级别映射到 INFO/ERROR 两档，error 可带堆栈。"""
    lv = logging.ERROR if level.lower() == "error" else logging.INFO
    _logger.log(lv, msg, *args, exc_info=exc_info or None)


def tail(lines: int = 200) -> list[str]:
    f = log_dir() / "wenshu.log"
    if not f.exists():
        return []
    with f.open(encoding="utf-8", errors="replace") as stream:
        return [line.rstrip("\n") for line in deque(stream, maxlen=max(1, lines))]
