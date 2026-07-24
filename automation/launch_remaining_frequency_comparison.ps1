$ErrorActionPreference = 'Stop'
$scriptRoot = 'E:\Users\dxhui\Desktop\TI_AFE58jd48\UltrasoundImagingData_Capture'
$pythonExe = 'C:\Python27\python.exe'
$captureScript = Join-Path $scriptRoot 'automation\comparison_remaining_frequency_capture.py'
$statusLog = Join-Path $scriptRoot 'auto_runs\New2039\frequency_comparison_launcher.log'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'This resume launcher must be run as Administrator.'
}

$Host.UI.RawUI.WindowTitle = 'TX7316 Remaining 1.5-2.0-2.5 MHz Capture'
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Remaining-frequency launcher entered; PID=$PID" |
    Out-File -LiteralPath $statusLog -Encoding utf8 -Append
Write-Host 'Resuming comparison: 1.5, 2.0, then 2.5 MHz.' -ForegroundColor Cyan
Set-Location -LiteralPath $scriptRoot
& $pythonExe $captureScript
$captureExit = $LASTEXITCODE
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Remaining acquisition exited code $captureExit" |
    Out-File -LiteralPath $statusLog -Encoding utf8 -Append
if ($captureExit -eq 0) {
    Write-Host 'ALL THREE REMAINING FREQUENCIES VERIFIED COMPLETE.' -ForegroundColor Green
} else {
    Write-Host ("RESUME STOPPED WITH ERROR {0}." -f $captureExit) -ForegroundColor Red
}
Read-Host 'Press Enter to close this window'
exit $captureExit
