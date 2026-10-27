@echo off
rem ============================================================
rem  Wenshu Studio - one-click launcher (Windows only)
rem  ASCII-only + CRLF on purpose: cmd parses bat with the OEM codepage;
rem  non-ASCII or LF breaks parsing. See docs/DEPLOY.md.
rem ============================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "LOG_DIR=log"
set "START_LOG=%LOG_DIR%\start.log"

rem ---- self-check: create runtime dirs if missing ----
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
if not exist "resource" mkdir "resource"
if not exist "config" mkdir "config"

echo [%date% %time%] ==== Wenshu start ==== >> "%START_LOG%"

rem ---- locate the main exe (single .exe in package root; wildcard avoids CJK bytes) ----
set "APP_EXE="
for %%F in (*.exe) do set "APP_EXE=%%F"
if not defined APP_EXE (
    echo [ERROR] No .exe found next to this script. Unpack the release zip first.
    echo [%date% %time%] ERROR: exe missing >> "%START_LOG%"
    pause
    exit /b 1
)

rem ---- port check: first free port in 8000-8005 ----
set "PORT="
for %%P in (8000 8001 8002 8003 8004 8005) do (
    if not defined PORT (
        netstat -ano | findstr "LISTENING" | findstr /C:":%%P " >nul 2>&1
        if errorlevel 1 set "PORT=%%P"
    )
)
if not defined PORT (
    echo [ERROR] Ports 8000-8005 are all busy. Close extra instances and retry.
    echo [%date% %time%] ERROR: no free port >> "%START_LOG%"
    pause
    exit /b 1
)

rem ---- Chromium for XHS cards: bundled in package (playwright-browsers/) ----
rem ---- only install when neither bundled nor user-profile copy exists ----
if not exist "playwright-browsers" if not exist "%LOCALAPPDATA%\ms-playwright" (
    echo First run: installing Chromium component for card rendering ...
    echo [%date% %time%] first run: install chromium >> "%START_LOG%"
    "%APP_EXE%" --install-browser >> "%START_LOG%" 2>&1
    if errorlevel 1 (
        echo [WARN] Chromium install failed - only XHS card export is affected.
        echo [%date% %time%] chromium install failed >> "%START_LOG%"
    )
)

rem ---- launch (log to file) ----
echo Starting Wenshu Studio on port %PORT% ... browser opens automatically.
echo Close this window to stop the app.
echo [%date% %time%] launch %APP_EXE% port=%PORT% >> "%START_LOG%"
"%APP_EXE%" --port %PORT% >> "%START_LOG%" 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Start failed. Check antivirus/SmartScreen, port conflict, or %START_LOG%
    echo [%date% %time%] ERROR: nonzero exit code >> "%START_LOG%"
    pause
    exit /b 1
)
endlocal
