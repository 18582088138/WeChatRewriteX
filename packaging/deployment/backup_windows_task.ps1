[CmdletBinding()]
param(
    [Parameter(Mandatory,ParameterSetName='Python')][string]$PythonPath,
    [Parameter(Mandatory,ParameterSetName='Executable')][string]$ExecutablePath,
    [Parameter(Mandatory)][string]$RuntimeDirectory,
    [Parameter(Mandatory)][string]$BackupDirectory,
    [string]$TaskName='Wenshu-SingleInstance',
    [ValidateRange(1,300)][int]$StopTimeoutSeconds=30
)
$ErrorActionPreference='Stop'
$binaryPath=if ($PSCmdlet.ParameterSetName -eq 'Python') { $PythonPath } else { $ExecutablePath }
$binaryResolved=(Resolve-Path -LiteralPath $binaryPath).ProviderPath
$runtimeResolved=(Resolve-Path -LiteralPath $RuntimeDirectory).ProviderPath
$backupResolved=[System.IO.Path]::GetFullPath($BackupDirectory)
if (Test-Path -LiteralPath $backupResolved) { throw 'Backup target must be new.' }
$task=Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$wasRunning=$task.State -eq 'Running'
try {
    if ($wasRunning) {
        Stop-ScheduledTask -TaskName $TaskName
        $deadline=[DateTime]::UtcNow.AddSeconds($StopTimeoutSeconds)
        while ((Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop).State -eq 'Running') {
            if ([DateTime]::UtcNow -ge $deadline) { throw 'Task stop timed out; no backup was started.' }
            Start-Sleep -Milliseconds 200
        }
    }
    # The CLI acquires the data-root OS lock and refuses if a process still owns it.
    $cliArguments=@('--runtime-dir',$runtimeResolved,'--data-dir',(Join-Path $runtimeResolved 'resource'),'--backup',$backupResolved)
    if ($PSCmdlet.ParameterSetName -eq 'Python') { $cliArguments=@('-m','app')+$cliArguments }
    & $binaryResolved @cliArguments
    if ($LASTEXITCODE -ne 0) { throw 'Backup failed. Check logs; do not mark this run successful.' }
} finally {
    if ($wasRunning) { Start-ScheduledTask -TaskName $TaskName }
}
Write-Output "Offline backup verified at $backupResolved. Copy it to another device when available."
