@echo off
rem Keeps the API + Mini App running; restarts it 5 s after any crash.
cd /d "%~dp0..\.."
if not exist logs mkdir logs
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
:loop
".venv\Scripts\python.exe" run_api.py >> logs\api.log 2>&1
ping -n 6 127.0.0.1 >nul
goto loop
