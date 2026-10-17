@echo off
rem Daily run - used by Windows Task Scheduler.
chcp 65001 >nul
cd /d "%~dp0"
python skidki_report.py %*
exit /b %ERRORLEVEL%
