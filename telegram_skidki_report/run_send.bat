@echo off
chcp 65001 >nul
pushd "%~dp0"
python send_telegram.py %*
set RC=%ERRORLEVEL%
popd
exit /b %RC%
