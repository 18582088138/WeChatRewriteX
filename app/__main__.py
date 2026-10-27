"""启动入口：python -m app [--host 127.0.0.1] [--port 8000]（冻结态：文枢.exe 同参）"""
from __future__ import annotations

import argparse
import sys

from . import APP_FULL_NAME, APP_ID, APP_VERSION


def main() -> None:
    parser = argparse.ArgumentParser(prog=APP_ID, description=APP_FULL_NAME)
    parser.add_argument("--host", default="127.0.0.1",
                        help="0.0.0.0 允许局域网/手机访问（建议同时配置 APP_ACCESS_TOKEN）")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="开发模式（仅源码运行可用）")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument("--install-browser", action="store_true",
                        help="安装小红书卡片渲染所需的 Chromium（首次使用卡片功能前执行一次）")
    args = parser.parse_args()

    if args.install_browser:
        _install_browser()
        return

    import uvicorn
    print(f"{APP_FULL_NAME} v{APP_VERSION}  →  http://{args.host}:{args.port}")
    if not args.no_browser and not args.reload:
        _open_browser_later(args.host, args.port)
    if args.reload:                      # reload 需要字符串形式导入，仅开发态
        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=True)
    else:
        from app.main import app as asgi_app   # 对象形式：冻结/pip 态均可运行
        uvicorn.run(asgi_app, host=args.host, port=args.port)


def _install_browser() -> None:
    """调用内置 Playwright 驱动安装 Chromium（幂等，已装则秒过）。"""
    from playwright.__main__ import main as pw_main
    sys.argv = ["playwright", "install", "chromium"]
    pw_main()
    print("Chromium 安装完成，小红书卡片渲染可用。")


def _open_browser_later(host: str, port: int) -> None:
    import threading
    import webbrowser
    url = f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}"
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()


if __name__ == "__main__":
    main()
