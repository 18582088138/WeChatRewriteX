"""构建前资产归集：config/、web/dist、.env.example → app/_assets/。

sdist（pip 安装态）与 PyInstaller（冻结态）共用同一份内置资产；
运行态首启时由 app.core.config.ensure_runtime_assets 播种到可写运行根。
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "app" / "_assets"


def main() -> None:
    if ASSETS.exists():
        shutil.rmtree(ASSETS)
    ASSETS.mkdir(parents=True)
    shutil.copytree(ROOT / "config", ASSETS / "config")
    if not (ROOT / "web" / "dist" / "index.html").exists():
        raise SystemExit("web/dist 未构建：先执行 cd web && npm install && npm run build")
    shutil.copytree(ROOT / "web" / "dist", ASSETS / "web" / "dist")
    shutil.copy(ROOT / ".env.example", ASSETS / ".env.example")
    print("资产归集完成 →", ASSETS)


if __name__ == "__main__":
    main()
