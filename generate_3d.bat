@echo off
setlocal DisableDelayedExpansion
"%~dp0runtime\bootstrap\python.exe" -u "%~dp0installer\launch.py" 3d %*
set "RESULT=%ERRORLEVEL%"
if not "%IMT_NONINTERACTIVE%"=="1" pause
exit /b %RESULT%
