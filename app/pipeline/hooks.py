"""用户 hooks：settings.yaml `hooks:` 下按事件名注册 shell 命令，支持 {article_id} 占位。"""
from __future__ import annotations

import shlex
import subprocess
import threading

from ..core import config, events

_registered = False


def register_hooks() -> None:
    global _registered
    if _registered:
        return
    _registered = True
    hooks: dict = config.get("hooks", {}) or {}
    for event, commands in hooks.items():
        for cmd in (commands or []):
            events.bus.on(event, _make_runner(cmd))


def _make_runner(cmd: str):
    def _run(msg: dict) -> None:
        real = cmd.format(article_id=msg.get("article_id") or "", **{
            k: v for k, v in msg.items() if isinstance(v, (str, int))})
        threading.Thread(target=_exec, args=(real,), daemon=True).start()

    def _exec(real_cmd: str) -> None:
        try:
            subprocess.run(shlex.split(real_cmd), timeout=300, check=False)
        except Exception:
            pass
    return _run
