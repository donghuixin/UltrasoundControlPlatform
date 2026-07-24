param([switch]$Elevated)

$ErrorActionPreference = 'Stop'
$scriptRoot = 'E:\Users\dxhui\Desktop\TI_AFE58jd48\UltrasoundImagingData_Capture'
$pythonExe = 'C:\Python27\python.exe'
$captureScript = Join-Path $scriptRoot 'automation\overnight_multifrequency_capture.py'
$outputRoot = Join-Path $scriptRoot 'auto_runs\New2039'
$statusLog = Join-Path $outputRoot 'frequency_compare_launcher_status.log'
$reportName = 'frequency_compare_1500_2000_2500_report.json'

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator)) {
    $arguments = @(
        '-NoExit',
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', ('"{0}"' -f $PSCommandPath),
        '-Elevated'
    )
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $arguments
    exit 0
}

$Host.UI.RawUI.WindowTitle = 'TX7316 Frequency Comparison - 1.5 / 2.0 / 2.5 MHz'
$timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
"[$timestamp] Elevated launcher entered; PID=$PID" | Out-File -LiteralPath $statusLog -Encoding utf8 -Append

Write-Host 'Administrator: yes' -ForegroundColor Green
Write-Host 'Plan: one verified 21-angle group at 1.5, 2.0 and 2.5 MHz.' -ForegroundColor Cyan
Write-Host 'Only frequency changes; geometry, angles, samples and HSDC settings remain fixed.'
Write-Host ('Status log: ' + $statusLog)
Write-Host ('Final report: ' + (Join-Path $outputRoot $reportName))
Write-Host ''

Set-Location -LiteralPath $scriptRoot
& $pythonExe $captureScript `
    --frequencies-mhz '1.5,2.0,2.5' `
    --groups-per-frequency 1 `
    --report-name $reportName
$captureExit = $LASTEXITCODE

$timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
"[$timestamp] Comparison acquisition exited with code $captureExit" | Out-File -LiteralPath $statusLog -Encoding utf8 -Append

Write-Host ''
if ($captureExit -eq 0) {
    Write-Host 'ALL THREE FREQUENCIES VERIFIED COMPLETE.' -ForegroundColor Green
} else {
    Write-Host ("CAPTURE STOPPED WITH ERROR {0}. No later frequency was started." -f $captureExit) -ForegroundColor Red
    Write-Host ('Inspect: ' + (Join-Path $outputRoot $reportName))
}
Read-Host 'Press Enter to close this window'
exit $captureExit
