"""
STEP 1 - refresh the discount report in Excel.

    open file -> enable editing -> Refresh All (Power Query) -> wait until
    finished -> save -> exit Excel

* Report is always for YESTERDAY (today's run updates yesterday's data).
* One file per month: "Скидки отчёт 2026-10.xlsx". When yesterday is in a new
  month, the file is created from the previous month's file and the Power
  Query date filter is moved to the new month.
* After a successful refresh it writes  state/refreshed_YYYY-MM-DD.txt
  (the Telegram text). send_telegram.py sends only if this file exists.

Run:  python refresh_report.py            (yesterday)
      python refresh_report.py 2026-10-15 (a specific day)

Needs: Windows + Microsoft Excel, pip install pywin32
"""

import datetime as dt
import glob
import logging
import os
import re
import shutil
import sys
import time

# ============================ SETTINGS ============================
REPORT_FOLDER = r"\\192.168.1.101\Auditor\AUDIT\Скидки\Скидки отчёт"
FILE_BASE_NAME = "Скидки отчёт"                     # -> "Скидки отчёт 2026-10.xlsx"
TEMPLATE_FILE = REPORT_FOLDER + r"\Скидки отчёт.xlsx"  # used only if no monthly file exists yet
REPORT_SHEET = "Отчёт"
REPORT_DATE_CELL = "C4"
TELEGRAM_TEXT_RANGE = "Telegram_текст"
QUERY_NAME = "База_продаж"
REFRESH_TIMEOUT_MIN = 30
# ==================================================================

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HERE, "state")
LOG_FILE = os.path.join(HERE, "logs", "refresh.log")
EXCEL_EPOCH = dt.date(1899, 12, 30)

log = logging.getLogger("refresh")


def setup_logging():
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


def refresh(path, report_date):
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    excel = win32com.client.DispatchEx("Excel.Application")  # separate, invisible Excel
    excel.Visible = False
    excel.DisplayAlerts = False
    excel.AskToUpdateLinks = False
    wb = None
    try:
        # 1. open
        log.info("Opening %s", path)
        wb = excel.Workbooks.Open(path, UpdateLinks=0, ReadOnly=False)
        # 2. enable editing
        if excel.ProtectedViewWindows.Count > 0:
            wb = excel.ProtectedViewWindows(1).Edit()
        if wb.ReadOnly:
            raise RuntimeError("File is already open by someone (read-only) - close it and run again")

        query = wb.Queries(QUERY_NAME)
        new_formula = month_filter(query.Formula, report_date)
        if new_formula != query.Formula:
            query.Formula = new_formula
            log.info("Power Query filter set to %s", month_key(report_date))
        wb.Worksheets(REPORT_SHEET).Range(REPORT_DATE_CELL).Value2 = (report_date - EXCEL_EPOCH).days
        log.info("Report date set to %s", report_date)

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

        text = range_to_text(wb.Names(TELEGRAM_TEXT_RANGE).RefersToRange.Value)

        # 4. save
        wb.Save()
        log.info("Saved")
        return text
    finally:
        # 5. exit
        if wb is not None:
            try:
                wb.Close(SaveChanges=False)
            except Exception:
                pass
        excel.Quit()
        pythoncom.CoUninitialize()
        log.info("Excel closed")


def _refreshing(conn):
    try:
        return conn.OLEDBConnection.Refreshing
    except Exception:
        return False


def main():
    setup_logging()
    report_date = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.date.today() - dt.timedelta(days=1)
    log.info("=== REFRESH for %s ===", report_date)
    try:
        path = get_month_file(report_date)
        text = refresh(path, report_date)
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(os.path.join(STATE_DIR, f"refreshed_{report_date}.txt"), "w", encoding="utf-8") as f:
            f.write(text)
        log.info("DONE")
        return 0
    except Exception:
        log.exception("REFRESH FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
