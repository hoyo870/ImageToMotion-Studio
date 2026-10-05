@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\bootstrap.ps1" %*
set "RESULT=%ERRORLEVEL%"
if not "%IMT_NONINTERACTIVE%"=="1" pause
exit /b %RESULT%
