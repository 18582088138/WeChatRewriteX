"""构建前资产归集：config/、web/dist、.env.example → app/_assets/。

sdist（pip 安装态）与 PyInstaller（冻结态）共用同一份内置资产；
运行态首启时由 app.core.config.ensure_runtime_assets 播种到可写运行根。
"""
from __future__ import annotations

import shutil
import hashlib
import importlib.metadata
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "app" / "_assets"


def main() -> None:
    if ASSETS.resolve().parent != (ROOT / "app").resolve():
        raise SystemExit("资产目录解析到工作区之外")
    if ASSETS.exists():
        shutil.rmtree(ASSETS)
    ASSETS.mkdir(parents=True)
    shutil.copytree(ROOT / "config", ASSETS / "config")
    if not (ROOT / "web" / "dist" / "index.html").exists():
        raise SystemExit("web/dist 未构建：先执行 cd web && npm install && npm run build")
    shutil.copytree(ROOT / "web" / "dist", ASSETS / "web" / "dist")
    shutil.copy(ROOT / ".env.example", ASSETS / ".env.example")
    source_files = []
    for folder in (ROOT / "app", ROOT / "web" / "src", ROOT / "config"):
        source_files.extend(p for p in folder.rglob("*") if p.is_file()
                            and "__pycache__" not in p.parts and not p.is_relative_to(ASSETS))
    source_files.extend(ROOT / p for p in ("pyproject.toml", "requirements.lock", "requirements-dev.lock",
                                         "web/package.json", "web/package-lock.json", "web/vite.config.ts"))
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in source_files if p.exists()}
    def command(args):
        try:
            return subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    sys.path.insert(0, str(ROOT))
    from app import APP_VERSION
    manifest = {"version": APP_VERSION, "commit": command(["git", "rev-parse", "HEAD"]),
                "source_hash": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
                "lock_hash": hashes.get("requirements.lock"), "node_lock_hash": hashes.get("web/package-lock.json"),
                "python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version,
                "node": command(["node", "--version"]), "playwright": importlib.metadata.version("playwright")}
    (ASSETS / "build_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("资产归集完成 →", ASSETS)


if __name__ == "__main__":
    main()
