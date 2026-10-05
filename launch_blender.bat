@echo off
setlocal DisableDelayedExpansion
"%~dp0runtime\bootstrap\python.exe" "%~dp0installer\launch.py" blender %*
exit /b %ERRORLEVEL%
