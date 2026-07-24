param([switch]$Elevated)

$ErrorActionPreference = 'Stop'
$scriptRoot = 'E:\Users\dxhui\Desktop\TI_AFE58jd48\UltrasoundImagingData_Capture'
$pythonExe = 'C:\Python27\python.exe'
$captureScript = Join-Path $scriptRoot 'automation\comparison_four_frequency_capture.py'
$statusLog = Join-Path $scriptRoot 'auto_runs\New2039\frequency_comparison_launcher.log'

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

$Host.UI.RawUI.WindowTitle = 'TX7316 Four-Frequency Calibration Capture'
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Elevated launcher entered; PID=$PID" |
    Out-File -LiteralPath $statusLog -Encoding utf8 -Append
Write-Host 'Administrator: yes' -ForegroundColor Green
Write-Host 'Plan: one verified 21-angle group at 1.0, 1.5, 2.0, then 2.5 MHz.' -ForegroundColor Cyan
Write-Host 'Each frequency starts only after the previous 21 BIN files pass QA.' -ForegroundColor Cyan

Set-Location -LiteralPath $scriptRoot
& $pythonExe $captureScript
$captureExit = $LASTEXITCODE
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Acquisition exited code $captureExit" |
    Out-File -LiteralPath $statusLog -Encoding utf8 -Append

if ($captureExit -eq 0) {
    Write-Host 'ALL FOUR FREQUENCIES VERIFIED COMPLETE.' -ForegroundColor Green
} else {
    Write-Host ("CAPTURE STOPPED WITH ERROR {0}; later frequencies were not started." -f $captureExit) -ForegroundColor Red
}
Read-Host 'Press Enter to close this window'
exit $captureExit
