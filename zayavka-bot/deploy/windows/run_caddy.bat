@echo off
rem HTTPS front door: https://<domain> -> http://127.0.0.1:8010 (free Let's Encrypt certificate).
cd /d "%~dp0"
if not exist ..\..\logs mkdir ..\..\logs
:loop
caddy.exe run --config Caddyfile --adapter caddyfile >> ..\..\logs\caddy.log 2>&1
ping -n 6 127.0.0.1 >nul
goto loop
