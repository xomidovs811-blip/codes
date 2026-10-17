@echo off
rem Creates a daily Task Scheduler job at 09:00 (change /ST if needed).
rem Run this once as the Windows user who has access to \\192.168.1.101 and has Excel.
schtasks /Create /TN "Skidki Telegram Report" /TR "\"%~dp0run_report.bat\"" /SC DAILY /ST 09:00 /RL HIGHEST /F
pause
