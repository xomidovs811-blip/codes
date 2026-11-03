@echo off
rem Button: save a new Telegram bot token for the report scripts.
chcp 65001 >nul
set "PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not exist "%PY%" (echo Python not found: %PY% & pause & exit /b 1)
echo Paste the NEW bot token from @BotFather and press Enter:
set "TOKEN="
set /p "TOKEN="
cls
if not defined TOKEN (echo Nothing entered - token not changed. & pause & exit /b 1)
echo Checking the token with Telegram ...
"%PY%" -c "import sys,requests; r=requests.get('https://api.telegram.org/bot'+sys.argv[1].strip()+'/getMe',timeout=30).json(); print('Token OK - bot @'+r['result']['username'] if r.get('ok') else 'WRONG TOKEN: '+str(r.get('description'))); sys.exit(0 if r.get('ok') else 1)" "%TOKEN%"
if errorlevel 1 (echo Token NOT saved - copy it again from @BotFather. & pause & exit /b 1)
setx TELEGRAM_BOT_TOKEN "%TOKEN%" >nul
set "TOKEN="
echo Saved. The report button and scheduled tasks use the new token from now on.
pause
