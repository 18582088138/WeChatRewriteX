# Registers only when explicitly run by the maintainer on the intended host.
# Use an elevated PowerShell for boot startup under the named existing local user.
[CmdletBinding()]
param(
    [Parameter(Mandatory,ParameterSetName='Python')][string]$PythonPath,
    [Parameter(Mandatory,ParameterSetName='Executable')][string]$ExecutablePath,
    [Parameter(Mandatory)][string]$AppDirectory,
    [Parameter(Mandatory)][string]$RuntimeDirectory,
    [string]$TaskName = 'Wenshu-SingleInstance',
    [string]$UserName = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
    [ValidateRange(1024,65535)][int]$Port = 8000
)
$ErrorActionPreference = 'Stop'
$binaryPath = if ($PSCmdlet.ParameterSetName -eq 'Python') { $PythonPath } else { $ExecutablePath }
$binaryResolved = (Resolve-Path -LiteralPath $binaryPath).ProviderPath
$appResolved = (Resolve-Path -LiteralPath $AppDirectory).ProviderPath
$runtimeResolved = [System.IO.Path]::GetFullPath($RuntimeDirectory)
foreach ($value in @($binaryResolved, $appResolved, $runtimeResolved)) {
    if ($value.Contains('"')) { throw 'Paths cannot contain a double quote.' }
}
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw 'Task already exists. Stop and remove it explicitly before registering a replacement.'
}
# Source checkout or wheel-installed interpreter; no secrets are stored in the task arguments.
$arguments = '--runtime-dir "{0}" --data-dir "{0}\resource" --log-dir "{0}\log" --host 127.0.0.1 --port {1} --no-browser' -f $runtimeResolved, $Port
if ($PSCmdlet.ParameterSetName -eq 'Python') { $arguments = '-m app ' + $arguments }
$action = New-ScheduledTaskAction -Execute $binaryResolved -Argument $arguments -WorkingDirectory $appResolved
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $UserName -LogonType S4U -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
Write-Output "Registered $TaskName. Start-ScheduledTask -TaskName '$TaskName' to start; Stop-ScheduledTask -TaskName '$TaskName' before maintenance."
