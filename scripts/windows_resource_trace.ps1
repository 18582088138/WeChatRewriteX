# System/process telemetry only; no task control, environment dump or application data.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$OutputFile,
    [ValidateRange(2,7200)][int]$DurationSeconds=60,
    [ValidateRange(1,60)][int]$IntervalSeconds=5,
    [int]$ProcessId=0,
    [ValidateSet('nuc','company','unknown')][string]$MachineRole='unknown'
)
$ErrorActionPreference='Stop'
$outputResolved=[System.IO.Path]::GetFullPath($OutputFile)
if (Test-Path -LiteralPath $outputResolved) { throw 'Trace already exists; use a new output file.' }
if (-not (Test-Path -LiteralPath (Split-Path -Parent $outputResolved) -PathType Container)) { throw 'Create the output parent directory first.' }
$deadline=[DateTime]::UtcNow.AddSeconds($DurationSeconds)
$clock=[System.Diagnostics.Stopwatch]::StartNew()
do {
    $sampleErrors=[System.Collections.Generic.List[string]]::new()
    $cpu=$null; $memory=$null; $disk=$null; $process=$null
    try { $cpu=Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'" -ErrorAction Stop } catch { $sampleErrors.Add('cpu_counter_unavailable') }
    try { $memory=Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory -ErrorAction Stop } catch { $sampleErrors.Add('memory_counter_unavailable') }
    try { $disk=Get-CimInstance Win32_PerfFormattedData_PerfDisk_PhysicalDisk -Filter "Name='_Total'" -ErrorAction Stop } catch { $sampleErrors.Add('disk_counter_unavailable') }
    if ($ProcessId -gt 0) {
        try { $process=Get-Process -Id $ProcessId -ErrorAction Stop } catch { $sampleErrors.Add('target_process_unavailable') }
    }
    [pscustomobject][ordered]@{
        at_utc=[DateTime]::UtcNow.ToString('o')
        elapsed_seconds=[Math]::Round($clock.Elapsed.TotalSeconds,3)
        machine_role=$MachineRole
        system_cpu_percent=if ($cpu) { $cpu.PercentProcessorTime } else { $null }
        available_memory_bytes=if ($memory) { $memory.AvailableBytes } else { $null }
        system_disk_queue=if ($disk) { $disk.CurrentDiskQueueLength } else { $null }
        system_disk_bytes_per_second=if ($disk) { $disk.DiskBytesPersec } else { $null }
        target_process_id=$ProcessId
        target_working_set_bytes=if ($process) { $process.WorkingSet64 } else { $null }
        target_private_bytes=if ($process) { $process.PrivateMemorySize64 } else { $null }
        target_cpu_seconds=if ($process) { $process.CPU } else { $null }
        sample_errors=($sampleErrors -join ';')
    } | Export-Csv -LiteralPath $outputResolved -Append -NoTypeInformation -Encoding UTF8
    if ([DateTime]::UtcNow -lt $deadline) { Start-Sleep -Seconds $IntervalSeconds }
} while ([DateTime]::UtcNow -lt $deadline)
Write-Output "Trace saved to $outputResolved. Missing counters are blank, not zero; this is sampled telemetry, not a pass verdict."
