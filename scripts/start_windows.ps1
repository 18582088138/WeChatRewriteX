# Wenshu Studio - one-click launcher (Windows PowerShell)
# ASCII-only on purpose: PS 5.1 misreads non-ASCII script files without BOM.
# Usage: powershell -ExecutionPolicy Bypass -File .\start_windows.ps1
# See docs/DEPLOY.md (Chinese) for details.
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$logDir = "log"
$startLog = Join-Path $logDir "start.log"
foreach ($d in @($logDir, "resource", "config")) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null }
}

function Write-Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $startLog -Value $line -Encoding ASCII
    Write-Host $line
}

Write-Log "==== Wenshu start (powershell) ===="

# ---- locate the main exe (single .exe in package root) ----
$exe = Get-ChildItem -Path . -Filter *.exe -File | Select-Object -First 1
if (-not $exe) {
    Write-Log "ERROR: no .exe found next to this script. Unpack the release zip first."
    Read-Host "Press Enter to exit"
    exit 1
}

# ---- port check: first free port in 8000-8005 ----
$port = 0
foreach ($p in 8000..8005) {
    $busy = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue
    if (-not $busy) { $port = $p; break }
}
if ($port -eq 0) {
    Write-Log "ERROR: ports 8000-8005 are all busy. Close extra instances and retry."
    Read-Host "Press Enter to exit"
    exit 1
}

# ---- first run: install Chromium for XHS card rendering (one-time, online) ----
# bundled playwright-browsers/ in the package makes this unnecessary
if (-not (Test-Path "playwright-browsers") -and
    -not (Test-Path "$env:LOCALAPPDATA\ms-playwright")) {
    Write-Log "First run: installing Chromium component for card rendering ..."
    & $exe.FullName --install-browser 2>&1 | Out-File -Append -Encoding ASCII $startLog
    if ($LASTEXITCODE -ne 0) {
        Write-Log "WARN: Chromium install failed - only XHS card export is affected."
    }
}

# ---- launch (tee output to log) ----
Write-Log "Starting Wenshu Studio on port $port ... browser opens automatically."
Write-Host "Close this window to stop the app."
& $exe.FullName --port $port 2>&1 | Tee-Object -FilePath $startLog -Append
if ($LASTEXITCODE -ne 0) {
    Write-Log "ERROR: start failed with exit code $LASTEXITCODE. See $startLog"
    Read-Host "Press Enter to exit"
    exit 1
}
