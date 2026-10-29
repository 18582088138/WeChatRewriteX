"""PyInstaller 入口跳板：冻结态入口脚本不能以相对导入直接执行 app/__main__.py，
经此脚本以绝对导入进入主入口（python -m app 的冻结等价物）。"""
import sys

# Frozen Python may ignore PYTHONIOENCODING and choose cp1252 for redirected pipes.
# Keep Chinese startup/version/log output usable in launchers and build checks.
for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from app.__main__ import main

if __name__ == "__main__":
    main()
