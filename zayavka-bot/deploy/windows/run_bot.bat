@echo off
rem Keeps the Telegram bot running; restarts it 5 s after any crash.
cd /d "%~dp0..\.."
if not exist logs mkdir logs
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
rem Give the API a moment to come up after a reboot.
ping -n 6 127.0.0.1 >nul
:loop
".venv\Scripts\python.exe" run_bot.py >> logs\bot.log 2>&1
ping -n 6 127.0.0.1 >nul
goto loop
