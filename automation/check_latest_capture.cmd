@echo off
setlocal
title Check Latest Ultrasound Capture

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$root='E:\Users\dxhui\Desktop\TI_AFE58jd48\UltrasoundImagingData_Capture\auto_runs'; if (-not (Test-Path -LiteralPath $root)) { Write-Host 'NO RESULT: auto_runs does not exist yet.' -ForegroundColor Yellow; exit 2 }; $run=Get-ChildItem -LiteralPath $root -Directory -Filter 'capture_*' | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if ($null -eq $run) { Write-Host 'NO RESULT: no capture_* folder exists yet.' -ForegroundColor Yellow; exit 2 }; Write-Host ('Latest run: ' + $run.FullName); $manifest=Join-Path $run.FullName 'capture_manifest.json'; if (-not (Test-Path -LiteralPath $manifest)) { Write-Host 'FAILED/INCOMPLETE: manifest is missing.' -ForegroundColor Red; exit 1 }; $m=Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json; $bins=@(Get-ChildItem -LiteralPath $run.FullName -Filter '*.bin'); $expected=@($m.array.profiles).Count * [int]$m.arguments.repeats; $expectedBytes=[int64]$m.hsdc.expected_file_bytes; $bad=@($bins | Where-Object Length -ne $expectedBytes); Write-Host ('Manifest status: ' + $m.status); Write-Host ('BIN count: ' + $bins.Count + ' / expected ' + $expected); Write-Host ('Expected bytes per BIN: ' + $expectedBytes); Write-Host ('Wrong-size BIN count: ' + $bad.Count); if ($m.status -eq 'complete' -and $bins.Count -eq $expected -and $bad.Count -eq 0) { Write-Host 'SUCCESS: manifest complete and all BIN file sizes are correct.' -ForegroundColor Green; exit 0 } else { Write-Host 'FAILED OR INCOMPLETE: inspect run.log and manifest error.' -ForegroundColor Red; if ($m.error) { Write-Host ('Error: ' + $m.error) -ForegroundColor Red }; exit 1 }"

set CHECK_EXIT=%ERRORLEVEL%
echo.
pause
exit /b %CHECK_EXIT%
