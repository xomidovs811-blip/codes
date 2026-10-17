# Скидки отчёт → Telegram

Two independent Python scripts. Schedule each one yourself in Windows Task Scheduler.

| Script | What it does |
|---|---|
| `refresh_report.py` | Opens `Скидки отчёт YYYY-MM.xlsx` and enables editing. Sets yesterday's date in `Отчёт!C4`, then runs **Refresh All** and waits until it finishes. Saves the file and closes Excel. |
| `delete_last_report.py` | Run by hand only. Deletes the last report the bot sent (the file and the text), so a wrong report can be removed and sent again. |
| `send_telegram.py` | Sends the file and the text from the **Telegram** sheet to the group. It sends only if the refresh for that day succeeded, and never sends the same day twice. |

- The report is always for **yesterday**.
- There is one file per month. A new month's file is created automatically from the previous month's file, and its Power Query date filter is moved to the new month.
- Settings are at the top of each script.
- The bot token is read from the Windows environment variable `TELEGRAM_BOT_TOKEN`.

```
pip install -r requirements.txt
python refresh_report.py            # or: python refresh_report.py 2026-10-15
python send_telegram.py             # or: python send_telegram.py 2026-10-15 --force
```

Logs: `logs\refresh.log` and `logs\send.log`. Markers: `state\`.

Task Scheduler: keep **"Run only when user is logged on"**, because Excel needs a logged-in user. Schedule the send task after the refresh task has finished.
