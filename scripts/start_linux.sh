#!/usr/bin/env bash
# ============================================================
#  文枢 - 自媒体 Studio  一键启动脚本（仅适配 Linux）
#  执行 ./start_linux.sh 即可拉起程序；无需 Python 环境。
#  说明见 docs/release/DEPLOY.md
# ============================================================
set -uo pipefail
cd "$(dirname "$0")"

APP_BIN="./文枢"
LOG_DIR="log"
START_LOG="$LOG_DIR/start.log"

# ---- 目录自检：缺失自动创建 ----
mkdir -p "$LOG_DIR" resource config

log() { echo "[$(date '+%F %T')] $*" | tee -a "$START_LOG"; }

log "==== 文枢启动 ===="

# ---- 主程序存在性/可执行权限检查 ----
if [ ! -f "$APP_BIN" ]; then
    log "错误：未找到 $APP_BIN —— 请确认本脚本与主程序在同一目录（发布包根目录）。"
    exit 1
fi
if [ ! -x "$APP_BIN" ]; then
    chmod +x "$APP_BIN" && log "已补可执行权限：$APP_BIN"
fi

# ---- 首次运行：卡片渲染组件 Chromium（仅需一次；不用小红书卡片可跳过）----
if [ ! -d "$HOME/.cache/ms-playwright" ]; then
    log "首次运行：安装小红书卡片渲染组件 Chromium（仅一次，需联网）..."
    if ! "$APP_BIN" --install-browser >> "$START_LOG" 2>&1; then
        log "提示：Chromium 安装失败，仅影响小红书卡片导出，其余功能可用。"
    fi
fi

log "正在启动 文枢 - 自媒体 Studio ... 访问 http://127.0.0.1:8000"
"$APP_BIN" --no-browser >> "$START_LOG" 2>&1
code=$?
if [ "$code" -ne 0 ]; then
    log "错误：启动失败（exit $code）。排查：1) 8000 端口被占用 2) 权限 3) 详见 $START_LOG"
    exit 1
fi
