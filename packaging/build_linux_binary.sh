#!/usr/bin/env bash
# ============================================================
# 借助 Docker 构建 Linux 端单文件二进制（产出 release/linux/文枢）
# 原理：PyInstaller 不支持跨平台交叉编译，Linux 二进制必须在 Linux 环境内
#       构建——用 python:3.12 容器挂载本仓库，在容器里安装依赖并执行 spec。
# 前置：本机装有 Docker 并已启动；仓库根目录执行：bash packaging/build_linux_binary.sh
# 先在宿主机构建前端：cd web && npm ci && npm run build
# ============================================================
set -euo pipefail
cd "$(dirname "$0")/.."
test -f web/dist/index.html || { echo "先执行 cd web && npm ci && npm run build"; exit 1; }

echo "[1/2] 容器内安装依赖 + PyInstaller，执行 spec 构建（首次约 5~10 分钟）..."
SRC="$PWD"
command -v cygpath >/dev/null 2>&1 && SRC="$(cygpath -w "$PWD")"   # Git Bash → Windows 路径
MSYS_NO_PATHCONV=1 docker run --rm -v "$SRC:/src" -w /src python:3.12 bash -c '
    set -e
    python -m pip install --require-hashes -r requirements-build.lock
    python scripts/build_assets.py
    python -m PyInstaller packaging/wenshu.spec --distpath release/linux --workpath build/pyinstaller-linux
    release/linux/文枢 --version
    release/linux/文枢 --build-info
'

echo "[2/2] 校验产物..."
test -f release/linux/文枢 && echo "OK → release/linux/文枢" \
    || { echo "构建失败：未见 release/linux/文枢"; exit 1; }
