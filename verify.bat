@echo off
setlocal
call "%~dp0setup.bat" -VerifyOnly
exit /b %ERRORLEVEL%
