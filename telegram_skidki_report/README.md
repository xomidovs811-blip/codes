# Скидки отчёт → Telegram

Every day this script:

1. **Updates the workbook.** It opens this month's `Скидки отчёт YYYY-MM.xlsx` in Excel and enables editing. It puts **yesterday's date** in `Отчёт!C4` and runs **Refresh All** (Power Query). It waits until every query has finished, then saves and closes the file.
2. **Sends it.** The updated file goes to the Telegram group (`-1004431975944`). The ready-made text from the hidden **Telegram** sheet (`Telegram_текст`) goes as a message after it.

The report is always for **yesterday**, so the report sent on 17.10 covers 16.10.

## Monthly files

The month is taken from the report date (yesterday):

| Run date | Report date | File |
|---|---|---|
| 17.10.2026 | 16.10.2026 | `Скидки отчёт 2026-10.xlsx` |
| 01.11.2026 | 31.10.2026 | `Скидки отчёт 2026-10.xlsx` (last day of October) |
| 02.11.2026 | 01.11.2026 | `Скидки отчёт 2026-11.xlsx` ← **created automatically** |

If the file for the month does not exist yet, the script copies the previous month's file. On the very first run it copies `template_file` instead. The script also changes the `База_продаж` Power Query filter, which was `[Дата2] > #date(2026, 9, 30)`, to `[Дата2] >= first day of month and [Дата2] < first day of next month`. The new file then holds only that month's data. You no longer need to edit the query by hand each month.

## Setup (Windows PC with Excel)

1. Install Python 3.10+ ("Add to PATH" checked).
2. Copy the `telegram_skidki_report` folder to the PC, e.g. `C:\SkidkiReport`.
3. `pip install -r requirements.txt`
4. Copy `config.example.ini` → `config.ini` and fill in:
   - `bot_token`: from @BotFather. It is **only** stored in `config.ini`, which git ignores. Never commit it.
   - `report_folder` / `template_file`: check both paths (see the note below).
   - `admin_chat_id` (optional): your personal chat id, which receives error messages.
5. Test each step by hand:
   ```
   python refresh_report.py     # step 1: open, Refresh All, save, exit Excel
   python send_telegram.py      # step 2: send the file + text to the group
   ```
6. Create two scheduled tasks and choose the times yourself (see below).

Logs are in `logs\skidki_report.log`.

## The two steps

| File | What it does | Started by |
|---|---|---|
| `refresh_report.py` | Opens the monthly file, enables editing, sets yesterday's date, runs Refresh All, waits, saves and closes Excel | `run_refresh.bat` |
| `send_telegram.py` | Sends the file and the text from the **Telegram** sheet to the group | `run_send.bat` |

Each one is a separate scheduled task, so you can fit both around other jobs on the server. Schedule the send step **after** the refresh step finishes (a refresh takes about 2 minutes).

`send_telegram.py` refuses to send a file that was not refreshed for yesterday, so a failed refresh never sends an old report. It also never posts the same day twice.

```powershell
$dir = "\\192.168.1.101\Auditor\AUDIT\Скидки\Скидки отчёт\SkidkiReport"
Register-ScheduledTask -TaskName "Skidki 1 Refresh" -Force -Trigger (New-ScheduledTaskTrigger -Daily -At 08:30) -Action (New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$dir\run_refresh.bat`"")
Register-ScheduledTask -TaskName "Skidki 2 Send" -Force -Trigger (New-ScheduledTaskTrigger -Daily -At 08:45) -Action (New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$dir\run_send.bat`"")
```
To change a time later, open Task Scheduler and edit the task's trigger, or run the same line again with a new `-At`.

### Useful options
```
python refresh_report.py --date 2026-10-15   # refresh for a specific day
python refresh_report.py --visible           # watch Excel while it works
python send_telegram.py --date 2026-10-15    # send a specific day
python send_telegram.py --force              # resend, or send without a refresh
python skidki_report.py                      # both steps in one go
```

## Important notes

- **Excel needs a logged-in user.** Excel automation does not work from a background service. In Task Scheduler, keep "Run only when user is logged on". Use a Windows user who has Excel installed and can open `\\192.168.1.101\Auditor`.
- **Nobody may have the file open while the script runs.** If someone has it open, Excel opens it read-only and the script stops with an error instead of saving.
- **Run time.** Schedule the task after yesterday's data has reached `Sales Database.xlsx` and the `UPLOADS` folder.
- **Folder path.** The config assumes the monthly files live in the folder `\\192.168.1.101\Auditor\AUDIT\Скидки\Скидки отчёт\`. It also assumes the current workbook is `\\192.168.1.101\Auditor\AUDIT\Скидки\Скидки отчёт.xlsx`. If yours differ, change `report_folder` and `template_file`.
- The bot must be an admin in the group, which it already is.

## Tests
```
python -m unittest discover -s tests -v
```
