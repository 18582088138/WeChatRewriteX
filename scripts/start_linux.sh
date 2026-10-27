#!/usr/bin/env bash
# ============================================================
#  文枢 - 自媒体 Studio  一键启动脚本（仅适配 Linux）
#  执行 ./start_linux.sh 即可拉起程序；无需 Python 环境。
#  说明见发布包内 docs/DEPLOY.md
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

# ---- 端口自检：8000 被占用则顺延 8001~8005 ----
PORT=""
for p in 8000 8001 8002 8003 8004 8005; do
    occupied=0
    if command -v ss >/dev/null 2>&1; then
        ss -ltn 2>/dev/null | grep -q ":$p " && occupied=1
    elif command -v netstat >/dev/null 2>&1; then
        netstat -ltn 2>/dev/null | grep -q ":$p " && occupied=1
    fi
    if [ "$occupied" -eq 0 ]; then PORT=$p; break; fi
done
if [ -z "$PORT" ]; then
    log "错误：8000~8005 端口均被占用，请关闭多余实例后重试。"
    exit 1
fi

# ---- 首次运行：卡片渲染组件 Chromium（仅需一次；不用小红书卡片可跳过）----
if [ ! -d "$HOME/.cache/ms-playwright" ]; then
    log "首次运行：安装小红书卡片渲染组件 Chromium（仅一次，需联网）..."
    if ! "$APP_BIN" --install-browser >> "$START_LOG" 2>&1; then
        log "提示：Chromium 安装失败，仅影响小红书卡片导出，其余功能可用。"
    fi
fi

log "正在启动 文枢 - 自媒体 Studio（端口 $PORT）... 访问 http://127.0.0.1:$PORT"
"$APP_BIN" --no-browser --port "$PORT" >> "$START_LOG" 2>&1
code=$?
if [ "$code" -ne 0 ]; then
    log "错误：启动失败（exit $code）。排查：1) 权限 2) 端口冲突 3) 详见 $START_LOG"
    exit 1
fi
