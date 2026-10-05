@echo off
setlocal
"%~dp0runtime\bootstrap\python.exe" -u "%~dp0installer\launch.py" menu
if not "%IMT_NONINTERACTIVE%"=="1" pause
