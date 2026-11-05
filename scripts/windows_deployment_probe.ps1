# Read-only host evidence. Does not install services, change power plans or open the DB.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$RuntimeDirectory,
    [Parameter(Mandatory)][string]$OutputFile,
    [string]$TaskName='Wenshu-SingleInstance',
    [ValidateRange(1024,65535)][int]$Port=8000
)
$ErrorActionPreference='Stop'
$runtimeResolved=[System.IO.Path]::GetFullPath($RuntimeDirectory)
$outputResolved=[System.IO.Path]::GetFullPath($OutputFile)
if (Test-Path -LiteralPath $outputResolved) { throw 'Report already exists; use a new output file.' }
if (-not (Test-Path -LiteralPath (Split-Path -Parent $outputResolved) -PathType Container)) {
    throw 'Create the report parent directory before running this probe.'
}
$system=Get-CimInstance Win32_ComputerSystem
$os=Get-CimInstance Win32_OperatingSystem
$cpu=Get-CimInstance Win32_Processor | Select-Object -First 1
$drive=[System.IO.Path]::GetPathRoot($runtimeResolved).TrimEnd('\')
$disk=Get-CimInstance Win32_LogicalDisk | Where-Object { $_.DeviceID -eq $drive } | Select-Object -First 1
$task=Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$taskInfo=if ($task) { Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue } else { $null }
$http=@{}
foreach ($path in @('/api/health','/api/auth/status')) {
    try {
        $response=Invoke-RestMethod -Uri "http://127.0.0.1:$Port$path" -TimeoutSec 5
        $http[$path]=@{reachable=$true; response=$response}
    } catch { $http[$path]=@{reachable=$false; error=$_.Exception.Message} }
}
$adapters=@(Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Up' } | ForEach-Object {
    @{interface_description=$_.InterfaceDescription; link_speed=$_.LinkSpeed}
})
$power=@(& powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 2>&1 | ForEach-Object { "$_" })
$dbFile=Join-Path $runtimeResolved 'resource\app.db'
$dbInfo=Get-Item -LiteralPath $dbFile -ErrorAction SilentlyContinue
$report=[ordered]@{
    recorded_at_utc=[DateTime]::UtcNow.ToString('o')
    scope='Read-only local host snapshot; not a load test, service restart test or remote acceptance.'
    machine=@{model=$system.Model; os=$os.Caption; version=$os.Version; cpu=$cpu.Name; logical_processors=$cpu.NumberOfLogicalProcessors;
        cpu_load_percent=$cpu.LoadPercentage; memory_total_bytes=[long]$system.TotalPhysicalMemory; memory_free_bytes=[long]$os.FreePhysicalMemory*1024}
    storage=@{runtime=$runtimeResolved; runtime_exists=(Test-Path -LiteralPath $runtimeResolved -PathType Container);
        drive=$drive; capacity_bytes=$disk.Size; free_bytes=$disk.FreeSpace; database_exists=[bool]$dbInfo; database_main_file_bytes=$dbInfo.Length}
    scheduled_task=@{name=$TaskName; exists=[bool]$task; state=if ($task) { "$($task.State)" } else { $null };
        last_result=if ($taskInfo) { $taskInfo.LastTaskResult } else { $null }; last_run=if ($taskInfo) { "$($taskInfo.LastRunTime)" } else { $null };
        logon_type=if ($task) { "$($task.Principal.LogonType)" } else { $null }}
    active_network_adapters=$adapters
    ac_sleep_powercfg_output=$power
    local_http=$http
    not_checked=@('Authenticated readiness','CPU/RAM/I/O peaks under sustained load','Real model latency','HTTPS/mesh network','Phone and remote members','Reboot and AC power restoration','Backup integrity and other-device copies')
}
$report | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $outputResolved -Encoding UTF8
Write-Output "Local evidence saved to $outputResolved. Missing checks remain unverified."
