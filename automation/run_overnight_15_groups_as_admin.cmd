@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "E:\Users\dxhui\Desktop\TI_AFE58jd48\UltrasoundImagingData_Capture\automation\launch_overnight_capture.ps1"
exit /b %errorlevel%
