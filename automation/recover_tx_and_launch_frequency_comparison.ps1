param([switch]$Elevated)

$ErrorActionPreference = 'Stop'
$scriptRoot = 'E:\Users\dxhui\Desktop\TI_AFE58jd48\UltrasoundImagingData_Capture'
$txExe = 'E:\Program Files (x86)\Texas Instruments\TX7316 EVM\TX7316 EVM.exe'
$pythonExe = 'C:\Python27\python.exe'
$captureScript = Join-Path $scriptRoot 'automation\overnight_multifrequency_capture.py'
$outputRoot = Join-Path $scriptRoot 'auto_runs\New2039'
$reportName = 'frequency_compare_1500_2000_2500_report.json'
$statusLog = Join-Path $outputRoot 'frequency_compare_recovery_status.log'

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator)) {
    $arguments = @(
        '-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', ('"{0}"' -f $PSCommandPath), '-Elevated'
    )
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $arguments
    exit 0
}

$Host.UI.RawUI.WindowTitle = 'TX7316 Recovery + Frequency Comparison'
$timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
"[$timestamp] Recovery launcher entered; PID=$PID" | Out-File -LiteralPath $statusLog -Encoding utf8 -Append

Write-Host 'The previous read-only TX probe returned FT_IO_ERROR.' -ForegroundColor Yellow
Write-Host 'Restarting only the TX7316 GUI; AFE and HSDC Pro are left untouched.'

Get-Process -Name 'TX7316 EVM' -ErrorAction SilentlyContinue | Stop-Process -Force
for ($index = 0; $index -lt 20; $index++) {
    if (-not (Get-Process -Name 'TX7316 EVM' -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 250
}
if (Get-Process -Name 'TX7316 EVM' -ErrorAction SilentlyContinue) {
    throw 'TX7316 EVM process did not exit during recovery.'
}

$txProcess = Start-Process -FilePath $txExe -PassThru
Write-Host ("TX7316 GUI restarted, PID={0}. Waiting for FTDI initialization" -f $txProcess.Id) -ForegroundColor Cyan
for ($second = 1; $second -le 12; $second++) {
    if ($txProcess.HasExited) { throw 'TX7316 GUI exited during startup.' }
    Write-Host -NoNewline '.'
    Start-Sleep -Seconds 1
}
Write-Host ''

Write-Host 'Starting one verified group at 1.5, 2.0 and 2.5 MHz.' -ForegroundColor Cyan
Set-Location -LiteralPath $scriptRoot
& $pythonExe $captureScript `
    --frequencies-mhz '1.5,2.0,2.5' `
    --groups-per-frequency 1 `
    --report-name $reportName
$captureExit = $LASTEXITCODE

$timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
"[$timestamp] Recovery comparison exited with code $captureExit" | Out-File -LiteralPath $statusLog -Encoding utf8 -Append
Write-Host ''
if ($captureExit -eq 0) {
    Write-Host 'ALL THREE FREQUENCIES VERIFIED COMPLETE.' -ForegroundColor Green
} else {
    Write-Host ("CAPTURE STOPPED WITH ERROR {0}." -f $captureExit) -ForegroundColor Red
    Write-Host ('Inspect: ' + (Join-Path $outputRoot $reportName))
}
Read-Host 'Press Enter to close this window'
exit $captureExit
