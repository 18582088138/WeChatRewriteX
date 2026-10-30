"""启动入口：python -m app [--host 127.0.0.1] [--port 8000]（冻结态：文枢.exe 同参）"""
from __future__ import annotations

import argparse
import sys

from . import APP_FULL_NAME, APP_ID, APP_VERSION


def main() -> None:
    # Scheduled/background Windows processes may use an ASCII/cp1252 pipe.
    # Startup/version/maintenance diagnostics must not crash on Chinese text.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog=APP_ID, description=APP_FULL_NAME)
    parser.add_argument("--version", action="version", version=f"{APP_FULL_NAME} {APP_VERSION}")
    parser.add_argument("--build-info", action="store_true", help="显示内嵌构建溯源信息后退出")
    parser.add_argument("--host", default="127.0.0.1",
                        help="0.0.0.0 允许局域网/手机访问（建议同时配置 APP_ACCESS_TOKEN）")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="开发模式（仅源码运行可用）")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument("--runtime-dir", help="独立持久运行目录（配置、.env、数据、日志），不随程序升级替换")
    parser.add_argument("--data-dir", help="显式数据根，优先于持久 .env 和 settings.yaml")
    parser.add_argument("--log-dir", help="显式日志目录，优先于持久 .env 和 settings.yaml")
    maintenance = parser.add_mutually_exclusive_group()
    maintenance.add_argument("--backup", metavar="DESTINATION", help="停服务后完整备份数据、配置与 .env 到全新外部目录")
    maintenance.add_argument("--restore", metavar="BACKUP", help="校验并恢复完整备份，--runtime-dir 必须为全新目录")
    maintenance.add_argument("--init-admin", metavar="LOGIN", help="停服务后初始化团队管理员（密码交互输入，不写命令行）")
    parser.add_argument("--install-browser", action="store_true",
                        help="安装小红书卡片渲染所需的 Chromium（首次使用卡片功能前执行一次）")
    args = parser.parse_args()

    if args.build_info:
        import json
        from pathlib import Path
        assets = Path(getattr(sys, "_MEIPASS")) / "wenshu_assets" if hasattr(sys, "_MEIPASS") else Path(__file__).parent / "_assets"
        manifest = assets / "build_manifest.json"
        print(manifest.read_text(encoding="utf-8") if manifest.exists() else json.dumps({"version": APP_VERSION}))
        return

    import os
    from pathlib import Path
    if args.runtime_dir:
        os.environ["WENSHU_RUNTIME_DIR"] = str(Path(args.runtime_dir).expanduser().resolve())
    if args.data_dir:
        os.environ["WENSHU_DATA_DIR"] = str(Path(args.data_dir).expanduser().resolve())
    if args.log_dir:
        os.environ["WENSHU_LOG_DIR"] = str(Path(args.log_dir).expanduser().resolve())
    if args.restore:
        from .services.instance_backup import restore_instance
        target = args.runtime_dir or os.environ.get("WENSHU_RUNTIME_DIR")
        if not target:
            parser.error("恢复必须明确指定 --runtime-dir 或 WENSHU_RUNTIME_DIR，且目标目录不得已存在")
        restore_instance(Path(args.restore), Path(target))
        return

    if args.install_browser:
        from .core import config  # Configure the bundled browser path as on normal startup.
        _install_browser()
        return

    from .core import config
    if args.init_admin:
        import getpass
        from .services import team
        from .pipeline.runtime_lock import RuntimeLock
        from .storage import db
        os.environ["WENSHU_TEAM_MODE"] = "1"
        guard = RuntimeLock(config.data_dir()).acquire()
        try:
            db.init_db()
            team.initialize_admin(args.init_admin, args.init_admin, getpass.getpass("管理员密码（至少10字符）："))
            print("管理员初始化完成；请启动服务并使用成员账号登录")
        finally:
            guard.close()
        return
    if args.backup:
        from .services.instance_backup import backup_instance
        backup_instance(config.RUNTIME_ROOT, config.data_dir(), Path(args.backup))
        return
    import ipaddress
    try:
        loopback = ipaddress.ip_address(args.host).is_loopback
    except ValueError:
        loopback = args.host == "localhost"
    from .services import team
    if not loopback and not config.get_env("APP_ACCESS_TOKEN") and not team.enabled():
        parser.error("远程绑定必须设置 APP_ACCESS_TOKEN")
    config.environment.require_token = not loopback and not team.enabled()
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
