@echo off
rem Button: choose the private chat for status messages.
chcp 65001 >nul
pushd "%~dp0"
set "PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not exist "%PY%" (echo Python not found: %PY% & popd & pause & exit /b 1)
for /f "tokens=2,*" %%a in ('reg query HKCU\Environment /v TELEGRAM_BOT_TOKEN 2^>nul ^| find "REG_SZ"') do set "TELEGRAM_BOT_TOKEN=%%b"
"%PY%" set_admin_chat.py
popd
pause
