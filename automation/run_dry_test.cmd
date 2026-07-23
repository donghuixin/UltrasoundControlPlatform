@echo off
setlocal
title TX7316 + HSDC Dry Run

"C:\Python27\python.exe" "%~dp0tx7316_hsdc_batch_capture.py" --dry-run

echo.
echo Dry Run finished. No hardware was changed.
pause
