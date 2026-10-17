@echo off
chcp 65001 >nul
pushd "%~dp0"
python refresh_report.py %*
set RC=%ERRORLEVEL%
popd
exit /b %RC%
