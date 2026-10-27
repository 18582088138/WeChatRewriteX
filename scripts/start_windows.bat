@echo off
rem ============================================================
rem  文枢 - 自媒体 Studio  一键启动脚本（仅适配 Windows）
rem  双击运行即可拉起程序；无需 Python 环境、无需手动输入命令。
rem  说明见 docs/release/DEPLOY.md
rem ============================================================
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set "APP_EXE=文枢.exe"
set "LOG_DIR=log"
set "START_LOG=%LOG_DIR%\start.log"

rem ---- 目录自检：缺失自动创建 ----
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
if not exist "resource" mkdir "resource"
if not exist "config" mkdir "config"

echo [%date% %time%] ==== 文枢启动 ==== >> "%START_LOG%"

rem ---- 主程序存在性检查 ----
if not exist "%APP_EXE%" (
    echo [错误] 未找到 %APP_EXE% —— 请确认本脚本与主程序在同一目录（发布包根目录）。
    echo [%date% %time%] 错误：未找到 %APP_EXE% >> "%START_LOG%"
    pause
    exit /b 1
)

rem ---- 首次运行：卡片渲染组件 Chromium（仅需一次；不用小红书卡片可跳过）----
if not exist "%LOCALAPPDATA%\ms-playwright" (
    echo 首次运行：正在安装小红书卡片渲染组件 Chromium（仅一次，需联网）...
    echo [%date% %time%] 首次运行：安装 Chromium >> "%START_LOG%"
    "%APP_EXE%" --install-browser >> "%START_LOG%" 2>&1
    if errorlevel 1 (
        echo [提示] Chromium 安装失败，仅影响小红书卡片导出，其余功能可用。详见 %START_LOG%
        echo [%date% %time%] Chromium 安装失败 >> "%START_LOG%"
    )
)

rem ---- 启动主程序（日志同时写入文件）----
echo 正在启动 文枢 - 自媒体 Studio ... 浏览器将自动打开 http://127.0.0.1:8000
echo 关闭本窗口即停止程序。
"%APP_EXE%" >> "%START_LOG%" 2>&1
if errorlevel 1 (
    echo.
    echo [错误] 启动失败。排查：1) 8000 端口被占用 2) 杀毒软件拦截 3) 详见 %START_LOG%
    echo [%date% %time%] 启动失败，exit code 非 0 >> "%START_LOG%"
    pause
    exit /b 1
)
endlocal
