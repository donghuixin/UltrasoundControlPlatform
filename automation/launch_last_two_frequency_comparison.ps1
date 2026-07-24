param([switch]$Elevated)

$ErrorActionPreference = 'Stop'
$scriptRoot = 'E:\Users\dxhui\Desktop\TI_AFE58jd48\UltrasoundImagingData_Capture'
$pythonExe = 'C:\Python27\python.exe'
$captureScript = Join-Path $scriptRoot 'automation\comparison_last_two_frequency_capture.py'
$statusLog = Join-Path $scriptRoot 'auto_runs\New2039\frequency_comparison_launcher.log'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $arguments = @(
        '-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', ('"{0}"' -f $PSCommandPath), '-Elevated'
    )
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $arguments
    exit 0
}

$Host.UI.RawUI.WindowTitle = 'TX7316 Final 2.0-2.5 MHz Capture'
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Last-two launcher entered; PID=$PID" |
    Out-File -LiteralPath $statusLog -Encoding utf8 -Append
Write-Host 'Completing comparison: 2.0 MHz, then 2.5 MHz.' -ForegroundColor Cyan
Set-Location -LiteralPath $scriptRoot
& $pythonExe $captureScript
$captureExit = $LASTEXITCODE
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Last-two acquisition exited code $captureExit" |
    Out-File -LiteralPath $statusLog -Encoding utf8 -Append
if ($captureExit -eq 0) {
    Write-Host '2.0 AND 2.5 MHz VERIFIED COMPLETE.' -ForegroundColor Green
} else {
    Write-Host ("LAST-TWO CAPTURE STOPPED WITH ERROR {0}." -f $captureExit) -ForegroundColor Red
}
Read-Host 'Press Enter to close this window'
exit $captureExit
