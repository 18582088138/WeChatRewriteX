"""开发者模式日志：开启后写 <项目根>/log/app.log（gitignore），供调试排查。

- 默认关闭；设置页打开后即时生效（无需重启）。
- 日志内容：任务队列事件、阶段进度、LLM 调用、失败堆栈。
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .core.config import PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / "log"
_HANDLER_NAME = "wra-file"
_logger = logging.getLogger("wra")


def log_dir() -> Path:
    return LOG_DIR


def configure(enabled: bool) -> None:
    """按开发者模式开关挂/卸文件 handler（幂等）。"""
    existing = [h for h in _logger.handlers if h.name == _HANDLER_NAME]
    if enabled and not existing:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        h = RotatingFileHandler(LOG_DIR / "app.log", maxBytes=2_000_000,
                                backupCount=3, encoding="utf-8")
        h.name = _HANDLER_NAME
        h.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        _logger.addHandler(h)
        _logger.setLevel(logging.INFO)
        _logger.info("开发者模式：日志持久化已开启 → %s", LOG_DIR)
    elif not enabled and existing:
        for h in existing:
            _logger.removeHandler(h)
            h.close()


def enabled() -> bool:
    from .core import config
    return bool(config.get("dev.mode", False))


def log(level: str, msg: str, *args) -> None:
    """业务侧打点入口（未开启时静默）。"""
    if enabled():
        _logger.log(getattr(logging, level.upper(), logging.INFO), msg, *args)


def tail(lines: int = 200) -> list[str]:
    f = LOG_DIR / "app.log"
    if not f.exists():
        return []
    data = f.read_text(encoding="utf-8", errors="replace").splitlines()
    return data[-lines:]
