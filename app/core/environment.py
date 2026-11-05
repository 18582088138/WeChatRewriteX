"""Validated dotenv replacement; one lock protects readers and reloads.

Startup keeps shell overrides. Explicit reload makes the file authoritative;
removing a file key restores its original process value (or removes it).
"""
from __future__ import annotations

import io
import os
from pathlib import Path
import re
import threading

from dotenv.parser import parse_stream
from dotenv.variables import parse_variables

lock = threading.RLock()
RESTART_KEYS = frozenset({"WENSHU_DATA_DIR", "WRA_DATA_DIR", "WENSHU_CORS_ORIGINS",
                          "PLAYWRIGHT_BROWSERS_PATH", "WENSHU_LOG_DIR", "WENSHU_RUNTIME_DIR",
                          "WENSHU_MIN_FREE_MB", "PATH", "PYTHONPATH"})
RESTART_KEYS = RESTART_KEYS | {"WENSHU_TEAM_MODE"}


class _Scope(dict):
    def get(self, key, default=None):
        return super().get(key.upper() if os.name == "nt" else key, default)


class Environment:
    def __init__(self):
        self.baseline = dict(os.environ)
        self.keys: set[str] = set()
        self.generation = 0

    def read(self, path: Path) -> dict[str, str]:
        # No partial update and no file text / secret values in diagnostics.
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise ValueError("无法读取 .env：请检查文件是否存在、权限及 UTF-8 编码") from exc
        values: dict[str, str] = {}
        for binding in parse_stream(io.StringIO(text)):
            if binding.error or (binding.key and (binding.value is None or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", binding.key))):
                raise ValueError(f".env 第 {binding.original.line} 行格式无效（需 KEY=value）")
            if binding.key:
                if "\x00" in binding.value:
                    raise ValueError(f".env 第 {binding.original.line} 行包含无效字符")
                scope = _Scope({**self.baseline, **values})
                # os.environ is case-insensitive on Windows; use its canonical keys.
                key = binding.key.upper() if os.name == "nt" else binding.key
                values[key] = "".join(atom.resolve(scope) for atom in parse_variables(binding.value))
        return values

    def apply(self, path: Path, *, startup=False) -> dict:
        with lock:
            values = self.read(path)
            touched = self.keys | values.keys()
            target = {key: values.get(key, self.baseline.get(key)) for key in touched}
            if startup:
                target.update({key: self.baseline[key] for key in touched if key in self.baseline})
            changes = {key for key in touched if os.environ.get(key) != target[key]}
            if startup and "WENSHU_RUNTIME_DIR" in changes:
                raise ValueError("WENSHU_RUNTIME_DIR 必须通过启动参数或进程环境设置，不能从 .env 切换运行目录")
            if not startup and changes & RESTART_KEYS:
                raise ValueError("以下环境变量变更需要重启，未应用任何改动：" + ", ".join(sorted(changes & RESTART_KEYS)))
            # A remotely bound process must never lose its authentication guard.
            if not startup and getattr(self, "require_token", False) and not target.get("APP_ACCESS_TOKEN", os.environ.get("APP_ACCESS_TOKEN")):
                raise ValueError("远程绑定时 APP_ACCESS_TOKEN 不能为空，未应用任何改动")
            previous = {key: os.environ.get(key) for key in touched}
            try:
                for key, value in target.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
            except (ValueError, OSError) as exc:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
                raise ValueError("环境变量更新失败，已保留原配置") from exc
            self.keys = set(values)
            self.generation += 1
            return {"ok": True, "generation": self.generation, "changed_count": len(changes),
                    "token_changed": "APP_ACCESS_TOKEN" in changes}


environment = Environment()
