@echo off
setlocal
title HKUST Ultrosound collector platform Launcher

where python.exe >nul 2>nul
if errorlevel 1 (
    echo Python 3 was not found on PATH.
    echo Install or activate the Python environment that contains NumPy, SciPy, Matplotlib and Pillow.
    pause
    exit /b 1
)

for /f "delims=" %%P in ('where python.exe') do (
    set "PYTHON_EXE=%%P"
    goto :python_found
)

:python_found
echo Launching HKUST Ultrosound collector platform as Administrator...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$python='%PYTHON_EXE%'; $app='%~dp0app.py'; Start-Process -Verb RunAs -FilePath $python -WorkingDirectory '%~dp0' -ArgumentList @($app)"

if errorlevel 1 (
    echo Launch cancelled or failed.
    pause
    exit /b 1
)
exit /b 0
