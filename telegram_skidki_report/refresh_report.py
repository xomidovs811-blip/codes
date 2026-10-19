"""
STEP 1 - refresh the discount report in Excel.

    open file -> enable editing -> Refresh All (Power Query) -> wait until
    finished -> save -> exit Excel

* Report is for YESTERDAY. Catch-up: if some days were missed, every day after
  the last sent one up to yesterday is prepared separately (own date, own text,
  own copy of the file in state/files/) so send_telegram.py can send each day.
* One file per month: "Скидки отчёт 2026-10.xlsx". When yesterday is in a new
  month, the file is created from the previous month's file and the Power
  Query date filter is moved to the new month.
* After a successful refresh it writes  state/refreshed_YYYY-MM-DD.txt
  (the Telegram text). send_telegram.py sends only if this file exists.

Run:  python refresh_report.py            (all missed days up to yesterday)
      python refresh_report.py 2026-10-15 (a specific day)

Needs: Windows + Microsoft Excel, pip install pywin32
"""

import datetime as dt
import glob
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time

# ============================ SETTINGS ============================
REPORT_FOLDER = r"\\192.168.1.101\Auditor\AUDIT\Скидки\Скидки отчёт"
FILE_BASE_NAME = "Скидки отчёт"                     # -> "Скидки отчёт 2026-10.xlsx"
TEMPLATE_FILE = REPORT_FOLDER + r"\Скидки отчёт.xlsx"  # used only if no monthly file exists yet
REPORT_SHEET = "Отчёт"
REPORT_DATE_CELL = "C4"
TELEGRAM_TEXT_RANGE = "Telegram_текст"
QUERY_NAME = "База_продаж"
REFRESH_TIMEOUT_MIN = 15  # Excel is killed if one run takes longer than this
MAX_CATCHUP_DAYS = 31  # never go further back than this
# ==================================================================

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HERE, "state")
LOG_FILE = os.path.join(HERE, "logs", "refresh.log")
EXCEL_EPOCH = dt.date(1899, 12, 30)

log = logging.getLogger("refresh")


def setup_logging():
    if log.handlers:
        return
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()):
        h.setFormatter(fmt)
        log.addHandler(h)


def month_key(d):
    return f"{d.year:04d}-{d.month:02d}"


def monthly_file(d):
    return os.path.join(REPORT_FOLDER, f"{FILE_BASE_NAME} {month_key(d)}.xlsx")


def previous_monthly_file(d):
    """Latest "<base> YYYY-MM.xlsx" from an earlier month, or None."""
    pattern = re.compile(re.escape(FILE_BASE_NAME) + r" (\d{4}-\d{2})\.xlsx$", re.IGNORECASE)
    found = []
    for p in glob.glob(os.path.join(REPORT_FOLDER, "*.xlsx")):
        m = pattern.search(os.path.basename(p))
        if m and m.group(1) < month_key(d):
            found.append((m.group(1), p))
    return max(found)[1] if found else None


def month_filter(formula, d):
    """Set the [Дата2] filter step of the Power Query to d's month."""
    first = d.replace(day=1)
    nxt = (first + dt.timedelta(days=32)).replace(day=1)
    condition = (f"[Дата2] >= #date({first.year}, {first.month}, 1) and "
                 f"[Дата2] < #date({nxt.year}, {nxt.month}, 1)")
    new, n = re.subn(
        r'(Table\.SelectRows\(#"Измененный тип", each )(\[Дата2\][^\r\n]*?)(\),[ \t]*\r?\n)',
        lambda m: m.group(1) + condition + m.group(3), formula, count=1)
    if n == 0:
        raise RuntimeError("Power Query date filter step ([Дата2]) not found")
    return new


def range_to_text(values):
    """Excel range values -> text (blank lines at start/end removed)."""
    if not isinstance(values, (tuple, list)):
        values = ((values,),)
    lines = ["" if r[0] is None else str(r[0]).replace("¶", "").rstrip() for r in values]
    return "\n".join(lines).strip("\n")


def get_month_file(d):
    path = monthly_file(d)
    if os.path.exists(path):
        return path
    source = previous_monthly_file(d) or TEMPLATE_FILE
    if not os.path.exists(source):
        raise FileNotFoundError(f"No file to create {path} from (looked for {source})")
    log.info("New month: creating %s from %s", path, source)
    shutil.copy2(source, path)
    return path


def lock_owner(path):
    """Who has the workbook open, from Excel's "~$name" lock file (best effort)."""
    try:
        with open(os.path.join(os.path.dirname(path), "~$" + os.path.basename(path)), "rb") as f:
            data = f.read()
    except OSError:
        return "unknown (maybe a hidden Excel on this PC - end EXCEL.EXE in Task Manager)"
    name = data[55:].decode("utf-16-le", "ignore").split("\x00")[0].strip() if len(data) > 55 else ""
    if not name and data:
        name = data[1:1 + data[0]].decode("cp1251", "ignore").strip()
    return name or "unknown"


def excel_running(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FI", "IMAGENAME eq EXCEL.EXE"],
                         capture_output=True, text=True).stdout
    return "EXCEL.EXE" in out.upper()


def kill_excel(pid):
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)


def kill_leftover_excel():
    """Kill the hidden Excel of an earlier run that got stuck (only that one)."""
    pid_file = os.path.join(STATE_DIR, "excel.pid")
    try:
        with open(pid_file) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return
    if excel_running(pid):
        log.warning("Killing stuck Excel from an earlier run (PID %s)", pid)
        kill_excel(pid)
        time.sleep(3)
    os.remove(pid_file)


def single_run_lock():
    """Return True if no other refresh is running (stale locks are taken over)."""
    lock = os.path.join(STATE_DIR, "refresh.lock")
    if os.path.exists(lock) and time.time() - os.path.getmtime(lock) > (REFRESH_TIMEOUT_MIN + 10) * 60:
        os.remove(lock)
    try:
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL))
        return True
    except FileExistsError:
        return False


def refresh(path, days):
    """Refresh the month file once, then prepare every day in `days` (same month)."""
    import pythoncom
    import win32com.client

    import win32process

    pythoncom.CoInitialize()
    excel = win32com.client.DispatchEx("Excel.Application")  # separate, invisible Excel
    pid = win32process.GetWindowThreadProcessId(excel.Hwnd)[1]
    with open(os.path.join(STATE_DIR, "excel.pid"), "w") as f:
        f.write(str(pid))
    excel.Visible = False
    excel.DisplayAlerts = False
    excel.AskToUpdateLinks = False

    # Watchdog: if Excel hangs (e.g. a source file is busy), kill it after the timeout.
    timed_out = threading.Event()
    watchdog = threading.Timer(REFRESH_TIMEOUT_MIN * 60, lambda: (timed_out.set(), kill_excel(pid)))
    watchdog.daemon = True
    watchdog.start()
    wb = None
    try:
        # 1. open
        log.info("Opening %s", path)
        wb = excel.Workbooks.Open(path, UpdateLinks=0, ReadOnly=False)
        # 2. enable editing
        if excel.ProtectedViewWindows.Count > 0:
            wb = excel.ProtectedViewWindows(1).Edit()
        if wb.ReadOnly:
            raise RuntimeError(f"File is already open by: {lock_owner(path)} - close it and run again")

        query = wb.Queries(QUERY_NAME)
        new_formula = month_filter(query.Formula, days[0])
        if new_formula != query.Formula:
            query.Formula = new_formula
            log.info("Power Query filter set to %s", month_key(days[0]))
        date_cell = wb.Worksheets(REPORT_SHEET).Range(REPORT_DATE_CELL)
        date_cell.Value2 = (days[-1] - EXCEL_EPOCH).days

        # 3. refresh all and wait until finished
        for conn in wb.Connections:
            try:
                conn.OLEDBConnection.BackgroundQuery = False  # makes RefreshAll wait
            except Exception:
                pass
        log.info("Refresh All ...")
        started = time.time()
        wb.RefreshAll()
        excel.CalculateUntilAsyncQueriesDone()
        while any(_refreshing(c) for c in wb.Connections):
            if time.time() - started > REFRESH_TIMEOUT_MIN * 60:
                raise TimeoutError("Refresh did not finish in time")
            time.sleep(2)
        excel.CalculateFull()
        log.info("Refresh finished in %.0f s", time.time() - started)

        # one report per day: set the date, recalculate, keep its text and a copy of the file
        os.makedirs(os.path.join(STATE_DIR, "files"), exist_ok=True)
        for day in days:
            date_cell.Value2 = (day - EXCEL_EPOCH).days
            excel.CalculateFull()
            text = range_to_text(wb.Names(TELEGRAM_TEXT_RANGE).RefersToRange.Value)
            snapshot = os.path.join(STATE_DIR, "files", f"{FILE_BASE_NAME} {day}.xlsx")
            if len(days) > 1:
                wb.SaveCopyAs(snapshot)
            elif os.path.exists(snapshot):
                os.remove(snapshot)  # the monthly file itself is now the right one
            with open(os.path.join(STATE_DIR, f"refreshed_{day}.txt"), "w", encoding="utf-8") as f:
                f.write(text)
            log.info("Prepared report for %s", day)

        # 4. save (the file stays on the latest day)
        wb.Save()
        log.info("Saved")
    except Exception:
        if timed_out.is_set():
            raise TimeoutError(f"Excel did not finish in {REFRESH_TIMEOUT_MIN} min and was killed "
                               "(a source file may have been busy) - run again later")
        raise
    finally:
        # 5. exit
        watchdog.cancel()
        for close in (lambda: wb.Close(SaveChanges=False) if wb is not None else None, excel.Quit):
            try:
                close()
            except Exception:
                pass
        pythoncom.CoUninitialize()
        time.sleep(2)
        if excel_running(pid):  # Excel did not quit by itself
            kill_excel(pid)
        os.remove(os.path.join(STATE_DIR, "excel.pid"))
        log.info("Excel closed")


def _refreshing(conn):
    try:
        return conn.OLEDBConnection.Refreshing
    except Exception:
        return False


def pending_days(today):
    """Days after the last sent report up to yesterday that are not sent yet."""
    yesterday = today - dt.timedelta(days=1)
    sent = [dt.date.fromisoformat(os.path.basename(p)[5:15])
            for p in glob.glob(os.path.join(STATE_DIR, "sent_????-??-??.txt"))]
    start = max(sent) + dt.timedelta(days=1) if sent else yesterday
    start = max(start, yesterday - dt.timedelta(days=MAX_CATCHUP_DAYS - 1))
    days = []
    while start <= yesterday:
        days.append(start)
        start += dt.timedelta(days=1)
    return days


def main():
    setup_logging()
    days = [dt.date.fromisoformat(sys.argv[1])] if len(sys.argv) > 1 else pending_days(dt.date.today())
    log.info("=== REFRESH: %s ===", ", ".join(map(str, days)) or "nothing to do")
    os.makedirs(STATE_DIR, exist_ok=True)
    if not days:
        return 0
    if not single_run_lock():
        log.error("Another refresh is still running - this run is skipped")
        return 1
    try:
        kill_leftover_excel()
        for month in sorted({month_key(d) for d in days}):  # one Excel run per month file
            month_days = [d for d in days if month_key(d) == month]
            refresh(get_month_file(month_days[0]), month_days)
        log.info("DONE")
        return 0
    except Exception:
        log.exception("REFRESH FAILED")
        return 1
    finally:
        os.remove(os.path.join(STATE_DIR, "refresh.lock"))


if __name__ == "__main__":
    sys.exit(main())
