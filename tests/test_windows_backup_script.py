"""Exercise CLI selection and task restoration without touching real scheduled tasks."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


@pytest.mark.skipif(not POWERSHELL, reason="PowerShell is unavailable")
@pytest.mark.parametrize("kind", ["Python", "Executable"])
@pytest.mark.parametrize("initial_state", ["Ready", "Running"])
@pytest.mark.parametrize("cli_exit", [0, 7])
def test_backup_cli_and_task_lifecycle(tmp_path, kind, initial_state, cli_exit):
    runtime = tmp_path / "runtime with spaces"
    runtime.mkdir()
    fake = tmp_path / "fake-cli.ps1"
    fake.write_text("ConvertTo-Json -InputObject @($args) -Compress | Set-Content -LiteralPath $env:WENSHU_TEST_ARGS\nexit ([int]$env:WENSHU_TEST_EXIT)\n", encoding="utf-8")
    harness = tmp_path / "harness.ps1"
    harness.write_text("""
$global:events=[System.Collections.Generic.List[string]]::new()
$global:phase=0; $global:polls=0
function Get-ScheduledTask {
    param($TaskName,$ErrorAction)
    if ($global:phase -eq 1) {
        $global:polls++
        if ($global:polls -ge 2) { $global:phase=2 }
    }
    $state=if ($global:phase -eq 0) { $env:WENSHU_TEST_STATE } elseif ($global:phase -eq 1) { 'Running' } else { 'Ready' }
    [pscustomobject]@{State=$state}
}
function Stop-ScheduledTask { param($TaskName); $global:events.Add('stop'); $global:phase=1 }
function Start-ScheduledTask { param($TaskName); $global:events.Add('start') }
function Start-Sleep { param($Milliseconds) }
$options=@{RuntimeDirectory=$env:WENSHU_TEST_RUNTIME; BackupDirectory=$env:WENSHU_TEST_BACKUP; TaskName='Mock-Wenshu'}
$options[$env:WENSHU_TEST_KIND+'Path']=$env:WENSHU_TEST_CLI
$failure=$null
try { & $env:WENSHU_TEST_SCRIPT @options } catch { $failure=$_.Exception.Message }
@{events=@($global:events.ToArray()); polls=$global:polls; failure=$failure} | ConvertTo-Json | Set-Content -LiteralPath $env:WENSHU_TEST_REPORT
""", encoding="utf-8")
    arguments, report = tmp_path / "args.json", tmp_path / "report.json"
    backup = tmp_path / "new backup"
    env = {**os.environ, "WENSHU_TEST_SCRIPT": str(ROOT / "packaging/deployment/backup_windows_task.ps1"),
           "WENSHU_TEST_CLI": str(fake), "WENSHU_TEST_KIND": kind,
           "WENSHU_TEST_STATE": initial_state, "WENSHU_TEST_EXIT": str(cli_exit),
           "WENSHU_TEST_ARGS": str(arguments), "WENSHU_TEST_REPORT": str(report),
           "WENSHU_TEST_RUNTIME": str(runtime), "WENSHU_TEST_BACKUP": str(backup)}
    result = subprocess.run([POWERSHELL, "-NoProfile", "-File", str(harness)],
                            env=env, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    details = json.loads(report.read_text(encoding="utf-8-sig"))
    expected = ["--runtime-dir", str(runtime), "--data-dir", str(runtime / "resource"), "--backup", str(backup)]
    if kind == "Python":
        expected = ["-m", "app"] + expected
    assert json.loads(arguments.read_text(encoding="utf-8-sig")) == expected
    assert details["events"] == (["stop", "start"] if initial_state == "Running" else [])
    if initial_state == "Running":
        assert details["polls"] >= 2
    assert bool(details["failure"]) == bool(cli_exit)
    assert (b"Offline backup verified" in result.stdout) == (cli_exit == 0)
