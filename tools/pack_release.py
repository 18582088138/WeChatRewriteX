"""一键打包：默认生成全部平台发布包，统一输出到 release/。

用法（仓库根目录，miniforge 环境）：
  python tools/pack_release.py                  # 全量：测试→资产→sdist→Windows exe→Linux(Docker)→组装→校验
  python tools/pack_release.py --skip-tests     # 跳过测试门槛
  python tools/pack_release.py --reuse-exe      # 核验 build/dist-windows/文枢/ 后复用，只重组装
  python tools/pack_release.py --skip-linux     # 不出 Linux 包

产物（release/ 目录，不入 git）：
  文枢-v<ver>-windows-x64.zip   Windows 绿色执行包（exe + 启动文枢.bat + docs）
  文枢-v<ver>-linux-x64.tar.gz  Linux 二进制包（二进制 + start_linux.sh + docs）
  wenshu-<ver>.tar.gz / *.whl    Python 源码包与安装包（同时留在 dist/）
  SHA256SUMS.txt                全部产物校验和
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import APP_VERSION                    # 版本单一来源：app/__init__.py

PY = sys.executable
RELEASE = ROOT / "release"


def _web_dist_fresh() -> bool:
    """web/dist 比 web/src 新才算新鲜；防止打过时的前端进包。"""
    dist = ROOT / "web" / "dist" / "index.html"
    if not dist.exists():
        return False
    inputs = [f for f in (ROOT / "web" / "src").rglob("*") if f.is_file()]
    inputs += [ROOT / "web" / name for name in ("package.json", "package-lock.json", "index.html")]
    inputs += list((ROOT / "web").glob("*.config.*")) + list((ROOT / "web").glob("tsconfig*.json"))
    newest_src = max((f.stat().st_mtime for f in inputs if f.exists()), default=0)
    return dist.stat().st_mtime >= newest_src


def _npm_build() -> None:
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        raise SystemExit("未找到 npm——先装 Node.js 或手动 cd web && npm run build")
    print("  $ npm run build (web/)")
    subprocess.run([npm, "run", "build"], cwd=ROOT / "web", check=True)


def run(cmd: list[str], **kw) -> None:
    print("  $", " ".join(str(c) for c in cmd))
    kw.setdefault("env", {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    subprocess.run(cmd, cwd=ROOT, check=True, **kw)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def zip_dir(src: Path, out: Path) -> None:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(src.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(src.parent))
    print("  zip →", out.name, out.stat().st_size // 1024, "KB")


def targz_dir(src: Path, out: Path) -> None:
    with tarfile.open(out, "w:gz") as t:
        t.add(src, arcname=src.name)
    print("  tar.gz →", out.name, out.stat().st_size // 1024, "KB")


def bundle_browsers(pkg_dir: Path) -> None:
    """把与当前环境 playwright 匹配的 chromium_headless_shell 打进发布包（免安装）。

    先执行 `playwright install chromium`，再按当前驱动要求的 revision 选取。
    文件 mtime 不能代表 revision；别的 Python 环境可能刚下载了另一版本。"""
    print("  按当前 playwright 版本准备浏览器（playwright install chromium）…")
    try:
        subprocess.run([PY, "-m", "playwright", "install", "chromium"],
                       capture_output=True, timeout=600)
    except Exception as e:
        print("  [warn] playwright install 失败（离线？）：", e)
    local = os.environ.get("LOCALAPPDATA")
    src_root = Path(local) / "ms-playwright" if local else None
    import playwright
    browser_config = Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
    browsers = json.loads(browser_config.read_text(encoding="utf-8"))["browsers"]
    revision = next(b["revision"] for b in browsers if b["name"] == "chromium-headless-shell")
    custom = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if custom and custom != "0":
        src_root = Path(custom)
    elif custom == "0":
        src_root = browser_config.parent / ".local-browsers"
    shell = src_root / f"chromium_headless_shell-{revision}" if src_root else None
    if not shell or not shell.is_dir():
        print("  [warn] 本机无 chromium_headless_shell 缓存，包内不带浏览器；"
              "首启脚本会引导安装（--install-browser）")
        return
    dst = pkg_dir / "playwright-browsers"
    shutil.copytree(shell, dst / shell.name)
    print(f"  浏览器已打入发布包：{shell.name}")


def copy_docs(dst: Path) -> None:
    # Preserve repository-relative links, including deployment -> architecture.
    shutil.copytree(ROOT / "docs", dst / "docs", dirs_exist_ok=True)
    for name in ("README.md", "CHANGELOG.md"):
        shutil.copy(ROOT / name, dst / name)
    # Keep the entry points used by older release packages.
    for name in ("ARTIFACTS.md", "DEPLOY.md"):
        (dst / "docs" / name).write_text(f"发布文档见 [{name}](release/{name})。\n", encoding="utf-8")


def clear_package(path: Path) -> None:
    resolved = path.resolve()
    if path.is_symlink() or resolved == RELEASE.resolve() or not resolved.is_relative_to(RELEASE.resolve()):
        raise SystemExit("拒绝清理发布目录以外的路径")
    if path.exists():
        shutil.rmtree(path)


def copy_frozen_bundle(source: Path, target: Path, executable: str) -> None:
    """Only ship compiled assets; a run from build/ may have seeded local .env/data."""
    if not (source / executable).is_file() or not (source / "_internal").is_dir():
        raise SystemExit("冻结包不完整：缺少可执行文件或 _internal")
    target.mkdir(parents=True)
    shutil.copy2(source / executable, target / executable)
    shutil.copytree(source / "_internal", target / "_internal")


def main() -> None:
    ap = argparse.ArgumentParser(description="文枢 一键打包（默认全平台）")
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--skip-sdist", action="store_true", help="跳过 Python 发布包（sdist 和 wheel）")
    ap.add_argument("--skip-windows", action="store_true")
    ap.add_argument("--skip-linux", action="store_true")
    ap.add_argument("--reuse-exe", action="store_true",
                    help="核验并复用 build/dist-windows/文枢/（不重跑 PyInstaller）")
    args = ap.parse_args()

    ver = APP_VERSION
    # 产物按版本分目录（release/v<ver>/），构建中间产物放 build/，不污染发布根
    ver_dir = RELEASE / f"v{ver}"
    ver_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[Path] = []

    # 0. 测试门槛
    if not args.skip_tests:
        print("[0] 测试门槛")
        run([PY, "-m", "pytest", "tests/", "-q"])

    # 1. 前置检查 + 资产归集（前端落后先重建，防止打旧界面包）
    print("[1] 资产归集（config + web/dist + .env.example → app/_assets）")
    if not _web_dist_fresh():
        print("  web/src 有改动未构建，先 npm run build")
        _npm_build()
    run([PY, "scripts/build_assets.py"])

    # 2. sdist 源码包
    if not args.skip_sdist:
        print("[2] Python 发布包（sdist + wheel）")
        run([PY, "-m", "build", "--sdist", "--wheel", "--no-isolation"])
        for name in (f"wenshu-{ver}.tar.gz", f"wenshu-{ver}-py3-none-any.whl"):
            artifact = ROOT / "dist" / name
            if not artifact.is_file():
                raise SystemExit(f"构建未生成预期发布包：{name}")
            shutil.copy(artifact, ver_dir / name)
            artifacts.append(ver_dir / name)

    # 3. Windows 绿色执行包
    if not args.skip_windows:
        bundle = ROOT / "build" / "dist-windows" / "文枢"
        exe = bundle / "文枢.exe"
        if bundle.is_symlink() or not bundle.resolve().is_relative_to((ROOT / "build").resolve()):
            raise SystemExit("冻结输出目录无效")
        if not (args.reuse_exe and exe.exists()):
            print("[3] Windows exe（PyInstaller，约 3~5 分钟）")
            run([PY, "-m", "PyInstaller", "packaging/wenshu.spec",
                 "--noconfirm",
                 "--distpath", str(ROOT / "build" / "dist-windows"),
                 "--workpath", str(ROOT / "build" / "pyinstaller")])
        else:
            current = json.loads((ROOT / "app" / "_assets" / "build_manifest.json").read_text(encoding="utf-8"))
            try:
                built = json.loads(subprocess.check_output([str(exe), "--build-info"], text=True,
                                                           encoding="utf-8", timeout=15))
            except (OSError, subprocess.SubprocessError, ValueError):
                raise SystemExit("旧 exe 缺少可验证构建信息，请去掉 --reuse-exe 重新构建")
            if built.get("version") != ver or built.get("source_hash") != current.get("source_hash"):
                raise SystemExit("exe 与当前版本/源码不匹配，请重新构建")
            print("[3] 复用已核验的 文枢.exe")
        win_dir = ver_dir / f"文枢-v{ver}-windows-x64"
        clear_package(win_dir)
        copy_frozen_bundle(bundle, win_dir, "文枢.exe")
        # Ship the current SPA at its runtime path so an in-place upgrade does
        # not keep serving the old seeded web/dist (including the UI bugs).
        shutil.copytree(ROOT / "web" / "dist", win_dir / "web" / "dist")
        shutil.copy(ROOT / "scripts" / "start_windows.bat", win_dir / "启动文枢.bat")
        shutil.copy(ROOT / "scripts" / "start_windows.ps1", win_dir / "启动文枢.ps1")
        copy_docs(win_dir)
        bundle_browsers(win_dir)
        zip_path = ver_dir / f"文枢-v{ver}-windows-x64.zip"
        zip_dir(win_dir, zip_path)
        artifacts.append(zip_path)

    # 4. Linux 二进制包（借 Docker；Docker 不可用则告警跳过，不算失败）
    if not args.skip_linux:
        print("[4] Linux 二进制（Docker 容器内构建）")
        docker_ok = shutil.which("docker") and subprocess.run(
            ["docker", "version"], capture_output=True).returncode == 0
        if not docker_ok:
            print("  [跳过] Docker 不可用——Linux 包未出。需要时启动 Docker 后重跑本脚本。")
        else:
            run(["bash", "packaging/build_linux_binary.sh"])
            linux_bundle = ROOT / "build" / "dist-linux" / "文枢"
            linux_bin = linux_bundle / "文枢"
            linux_dir = ver_dir / f"文枢-v{ver}-linux-x64"
            clear_package(linux_dir)
            copy_frozen_bundle(linux_bundle, linux_dir, "文枢")
            shutil.copytree(ROOT / "web" / "dist", linux_dir / "web" / "dist")
            (linux_dir / "文枢").chmod(0o755)
            shutil.copy(ROOT / "scripts" / "start_linux.sh", linux_dir / "start_linux.sh")
            (linux_dir / "start_linux.sh").chmod(0o755)
            copy_docs(linux_dir)
            tgz = ver_dir / f"文枢-v{ver}-linux-x64.tar.gz"
            targz_dir(linux_dir, tgz)
            artifacts.append(tgz)

    # 5. 校验和（写在该版本目录内）
    if artifacts:
        sums = ver_dir / "SHA256SUMS.txt"
        sums.write_text("".join(f"{sha256(p)}  {p.name}\n" for p in artifacts),
                        encoding="utf-8")
        print("[5] SHA256SUMS.txt 已更新")
    print("\n== 完成。release/v" + ver + "/ 产物：")
    for p in artifacts:
        print("  -", p.name)


if __name__ == "__main__":
    main()
