@echo off
rem Daily run - used by Windows Task Scheduler.
rem pushd (not cd) so it also works when this folder is on a network share (\\server\...).
chcp 65001 >nul
pushd "%~dp0"
python skidki_report.py %*
set RC=%ERRORLEVEL%
popd
exit /b %RC%
