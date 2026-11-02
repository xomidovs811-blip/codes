@echo off
rem Button: refresh the report, then send it to Telegram.
chcp 65001 >nul
pushd "%~dp0"
set "PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not exist "%PY%" (echo Python not found: %PY% & popd & pause & exit /b 1)
for /f "tokens=2,*" %%a in ('reg query HKCU\Environment /v TELEGRAM_BOT_TOKEN 2^>nul ^| find "REG_SZ"') do set "TELEGRAM_BOT_TOKEN=%%b"
echo === 1. Refreshing the Excel report ...
"%PY%" refresh_report.py
if errorlevel 1 (echo. & echo REFRESH FAILED - nothing was sent. See the message above. & popd & pause & exit /b 1)
echo.
echo === 2. Sending to Telegram ...
"%PY%" send_telegram.py
echo.
popd
pause
