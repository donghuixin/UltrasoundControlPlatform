param([switch]$Elevated)

$ErrorActionPreference = 'Stop'
$scriptRoot = 'E:\Users\dxhui\Desktop\TI_AFE58jd48\UltrasoundImagingData_Capture'
$pythonExe = 'C:\Python27\python.exe'
$captureScript = Join-Path $scriptRoot 'automation\overnight_multifrequency_capture.py'
$statusLog = Join-Path $scriptRoot 'auto_runs\New2039\overnight_launcher_status.log'

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

$Host.UI.RawUI.WindowTitle = 'TX7316 Overnight 15-Group Capture'
$timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
"[$timestamp] Elevated launcher entered; PID=$PID" | Out-File -LiteralPath $statusLog -Encoding utf8 -Append
Write-Host 'Administrator: yes' -ForegroundColor Green
Write-Host ('Launcher status log: ' + $statusLog)
Write-Host 'Starting strict serial 15-group acquisition...' -ForegroundColor Cyan

Set-Location -LiteralPath $scriptRoot
& $pythonExe $captureScript
$captureExit = $LASTEXITCODE
$timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
"[$timestamp] Acquisition process exited with code $captureExit" | Out-File -LiteralPath $statusLog -Encoding utf8 -Append

Write-Host ''
if ($captureExit -eq 0) {
    Write-Host 'ALL GROUPS VERIFIED COMPLETE. This window may be closed.' -ForegroundColor Green
} else {
    Write-Host ("CAPTURE STOPPED WITH ERROR {0}." -f $captureExit) -ForegroundColor Red
    Write-Host 'Check auto_runs\New2039\overnight_batch_report.json and the newest run.log.'
}
Read-Host 'Press Enter to close this window'
exit $captureExit
