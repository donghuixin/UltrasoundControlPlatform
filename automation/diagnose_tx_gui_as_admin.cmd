@echo off
setlocal
title TX7316 GUI Read-Only Diagnostic

echo This diagnostic performs register READS only.
echo It does not change TX settings and does not start HSDC capture.
echo TX7316 GUI must already be running AS ADMINISTRATOR.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$python='C:\Python27\python.exe'; $script='%~dp0diagnose_tx7316_gui.py'; $p=Start-Process -Verb RunAs -Wait -PassThru -FilePath $python -WorkingDirectory '%~dp0' -ArgumentList @($script); exit $p.ExitCode"

set DIAG_EXIT=%ERRORLEVEL%
echo.
if "%DIAG_EXIT%"=="0" (
    echo SUCCESS: a readable TX7316 GUI register-tree combination was found.
) else (
    echo NO MATCH: no register was written. Check tx_gui_diagnostic.log.
)
echo Log: %~dp0tx_gui_diagnostic.log
pause
exit /b %DIAG_EXIT%
