"""一键打包：默认生成全部平台发布包，统一输出到 release/。

用法（仓库根目录，miniforge 环境）：
  python tools/pack_release.py                  # 全量：测试→资产→sdist→Windows exe→Linux(Docker)→组装→校验
  python tools/pack_release.py --skip-tests     # 跳过测试门槛
  python tools/pack_release.py --reuse-exe      # 复用已构建的 release/windows/文枢.exe，只重组装
  python tools/pack_release.py --skip-linux     # 不出 Linux 包

产物（release/ 目录，不入 git）：
  文枢-v<ver>-windows-x64.zip   Windows 绿色执行包（exe + 启动文枢.bat + docs）
  文枢-v<ver>-linux-x64.tar.gz  Linux 二进制包（二进制 + start_linux.sh + docs）
  wenshu-<ver>.tar.gz           源码包（sdist，同时留在 dist/）
  SHA256SUMS.txt                全部产物校验和
"""
from __future__ import annotations

import argparse
import hashlib
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


def run(cmd: list[str], **kw) -> None:
    print("  $", " ".join(str(c) for c in cmd))
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


def copy_docs(dst: Path) -> None:
    (dst / "docs").mkdir(parents=True, exist_ok=True)
    for name in ("ARTIFACTS.md", "DEPLOY.md"):
        shutil.copy(ROOT / "docs" / "release" / name, dst / "docs" / name)


def main() -> None:
    ap = argparse.ArgumentParser(description="文枢 一键打包（默认全平台）")
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--skip-sdist", action="store_true")
    ap.add_argument("--skip-windows", action="store_true")
    ap.add_argument("--skip-linux", action="store_true")
    ap.add_argument("--reuse-exe", action="store_true",
                    help="复用 release/windows/文枢.exe（不重跑 PyInstaller）")
    args = ap.parse_args()

    ver = APP_VERSION
    RELEASE.mkdir(exist_ok=True)
    artifacts: list[Path] = []

    # 0. 测试门槛
    if not args.skip_tests:
        print("[0] 测试门槛")
        run([PY, "-m", "pytest", "tests/", "-q"])

    # 1. 前置检查 + 资产归集
    print("[1] 资产归集（config + web/dist + .env.example → app/_assets）")
    if not (ROOT / "web" / "dist" / "index.html").exists():
        raise SystemExit("web/dist 未构建：先 cd web && npm install && npm run build")
    run([PY, "scripts/build_assets.py"])

    # 2. sdist 源码包
    if not args.skip_sdist:
        print("[2] sdist 源码包")
        run([PY, "-m", "build", "--sdist"])
        sdist = ROOT / "dist" / f"wenshu-{ver}.tar.gz"
        if sdist.exists():
            shutil.copy(sdist, RELEASE / sdist.name)
            artifacts.append(RELEASE / sdist.name)

    # 3. Windows 绿色执行包
    if not args.skip_windows:
        exe = RELEASE / "windows" / "文枢.exe"
        if not (args.reuse_exe and exe.exists()):
            print("[3] Windows exe（PyInstaller，约 3~5 分钟）")
            run([PY, "-m", "PyInstaller", "packaging/wenshu.spec",
                 "--distpath", str(RELEASE / "windows"),
                 "--workpath", str(ROOT / "build" / "pyinstaller")])
        else:
            print("[3] 复用已有 文枢.exe")
        win_dir = RELEASE / f"文枢-v{ver}-windows-x64"
        if win_dir.exists():
            shutil.rmtree(win_dir)
        win_dir.mkdir()
        shutil.copy(exe, win_dir / "文枢.exe")
        shutil.copy(ROOT / "scripts" / "start_windows.bat", win_dir / "启动文枢.bat")
        copy_docs(win_dir)
        zip_path = RELEASE / f"文枢-v{ver}-windows-x64.zip"
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
            linux_bin = RELEASE / "linux" / "文枢"
            linux_dir = RELEASE / f"文枢-v{ver}-linux-x64"
            if linux_dir.exists():
                shutil.rmtree(linux_dir)
            linux_dir.mkdir()
            shutil.copy(linux_bin, linux_dir / "文枢")
            (linux_dir / "文枢").chmod(0o755)
            shutil.copy(ROOT / "scripts" / "start_linux.sh", linux_dir / "start_linux.sh")
            (linux_dir / "start_linux.sh").chmod(0o755)
            copy_docs(linux_dir)
            tgz = RELEASE / f"文枢-v{ver}-linux-x64.tar.gz"
            targz_dir(linux_dir, tgz)
            artifacts.append(tgz)

    # 5. 校验和
    if artifacts:
        sums = RELEASE / "SHA256SUMS.txt"
        sums.write_text("".join(f"{sha256(p)}  {p.name}\n" for p in artifacts),
                        encoding="utf-8")
        print("[5] SHA256SUMS.txt 已更新")
    print("\n== 完成。release/ 产物：")
    for p in artifacts:
        print("  -", p.name)


if __name__ == "__main__":
    main()
