[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PythonPath,
    [Parameter(Mandatory)][string]$RuntimeDirectory,
    [Parameter(Mandatory)][string]$BackupDirectory,
    [string]$TaskName='Wenshu-SingleInstance'
)
$ErrorActionPreference='Stop'
$pythonResolved=(Resolve-Path -LiteralPath $PythonPath).ProviderPath
$runtimeResolved=(Resolve-Path -LiteralPath $RuntimeDirectory).ProviderPath
$backupResolved=[System.IO.Path]::GetFullPath($BackupDirectory)
if (Test-Path -LiteralPath $backupResolved) { throw 'Backup target must be new.' }
$task=Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$wasRunning=$task.State -eq 'Running'
if ($wasRunning) { Stop-ScheduledTask -TaskName $TaskName }
try {
    # The CLI acquires the data-root OS lock and refuses if a process still owns it.
    & $pythonResolved -m app --runtime-dir $runtimeResolved --data-dir (Join-Path $runtimeResolved 'resource') --backup $backupResolved
    if ($LASTEXITCODE -ne 0) { throw 'Backup failed. Check logs; do not mark this run successful.' }
} finally {
    if ($wasRunning) { Start-ScheduledTask -TaskName $TaskName }
}
Write-Output "Offline backup verified at $backupResolved. Copy it to another device when available."
