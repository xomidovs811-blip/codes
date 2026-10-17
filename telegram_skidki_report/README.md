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
5. Test it by hand:
   ```
   python skidki_report.py --no-send      # refresh only, check the file
   python skidki_report.py                # refresh + send
   ```
6. Run `install_task.bat` once. It creates a daily Task Scheduler job at 09:00. To change the time, edit `/ST` or change it in Task Scheduler.

Logs are in `logs\skidki_report.log`.

### Useful options
```
python skidki_report.py --date 2026-10-15   # rebuild & send a specific day
python skidki_report.py --send-only         # resend without refreshing
python skidki_report.py --force             # send again even if already sent today
```
The script records which dates it has sent in `sent_state.json`. If the task runs twice, it does not post twice.

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
