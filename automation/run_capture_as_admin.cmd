@echo off
setlocal
title TX7316 + HSDC Batch Capture Launcher

echo ================================================================
echo Before continuing, confirm ALL of the following:
echo   1. TX7316 GUI is already running AS ADMINISTRATOR and CONNECTED.
echo   2. HSDC Pro is already running AS ADMINISTRATOR and CONNECTED.
echo   3. AFE GUI has initialized LMK and AFE; ADC is not clipping.
echo   4. Gel/probe/wiring/power rails are ready; CW mode is OFF.
echo   5. This is a gel/phantom test, not a human test.
echo ================================================================
echo.
set /p CONFIRM=Type CAPTURE and press Enter to start:
if /I not "%CONFIRM%"=="CAPTURE" (
    echo Cancelled. No hardware was changed.
    pause
    exit /b 1
)

rem Start a new elevated command window. The Python script independently checks
rem that it is really running with Administrator privileges and is 32-bit.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$python='C:\Python27\python.exe'; $script='%~dp0tx7316_hsdc_batch_capture.py'; $p=Start-Process -Verb RunAs -Wait -PassThru -FilePath $python -WorkingDirectory '%~dp0' -ArgumentList @($script, '--capture', '--enable-internal-bf'); exit $p.ExitCode"

set CAPTURE_EXIT=%ERRORLEVEL%

echo.
if "%CAPTURE_EXIT%"=="0" (
    echo ================================================================
    echo SUCCESS: batch capture completed without a reported error.
    echo Confirm capture_manifest.json says "status": "complete".
    echo ================================================================
) else (
    echo ================================================================
    echo FAILED: capture script returned exit code %CAPTURE_EXIT%.
    echo Check the newest auto_runs\capture_*\run.log and manifest error field.
    echo Do not start another high-voltage capture until the error is understood.
    echo ================================================================
)
pause
exit /b %CAPTURE_EXIT%
