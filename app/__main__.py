"""启动入口：python -m app [--host 127.0.0.1] [--port 8000]"""
from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="WeChatRewritingAssistant")
    parser.add_argument("--host", default="127.0.0.1",
                        help="0.0.0.0 允许局域网/手机访问（建议同时配置 APP_ACCESS_TOKEN）")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    import uvicorn
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
