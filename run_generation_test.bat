@echo off
setlocal
set PYTHONUTF8=1
"%~dp0runtime\bootstrap\python.exe" -u "%~dp0tests\full_pipeline.py"
set "RESULT=%ERRORLEVEL%"
if not "%IMT_NONINTERACTIVE%"=="1" pause
exit /b %RESULT%
