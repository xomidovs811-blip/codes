"""Daily discount report ("Скидки отчёт") -> Telegram.

Step 1: open the monthly workbook in Excel, set the report date to yesterday,
        "Refresh All" (Power Query), wait until it finishes, save, close.
Step 2: send the updated workbook + the text from the hidden "Telegram" sheet
        to the Telegram group.

The report is always for YESTERDAY (all of yesterday's transactions are closed
by the time it runs). Every month gets its own file "Скидки отчёт YYYY-MM.xlsx";
when yesterday falls into a new month, the file is created from the previous
month's file and its Power Query date filter is moved to the new month.

Runs on Windows with Microsoft Excel installed (uses COM via pywin32).

Usage:
    python skidki_report.py                     # normal daily run
    python skidki_report.py --date 2026-10-15   # rebuild/resend a specific day
    python skidki_report.py --no-send           # only refresh the workbook
    python skidki_report.py --send-only         # only send (no Excel refresh)
    python skidki_report.py --force             # send even if already sent
"""

import argparse
import configparser
import datetime as dt
import glob
import json
import logging
import os
import re
import shutil
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "config.ini")
TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024
EXCEL_EPOCH = dt.date(1899, 12, 30)

log = logging.getLogger("skidki_report")


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def load_config(path):
    if not os.path.exists(path):
        sys.exit(f"Config not found: {path}\nCopy config.example.ini to config.ini and fill it in.")
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(path, encoding="utf-8")
    cfg = {
        "bot_token": os.environ.get("TELEGRAM_BOT_TOKEN") or cp.get("telegram", "bot_token", fallback=""),
        "chat_id": cp.get("telegram", "chat_id"),
        "admin_chat_id": cp.get("telegram", "admin_chat_id", fallback="").strip(),
        "send_text": cp.getboolean("telegram", "send_text", fallback=True),
        "report_folder": cp.get("excel", "report_folder"),
        "file_base_name": cp.get("excel", "file_base_name", fallback="Скидки отчёт"),
        "template_file": cp.get("excel", "template_file", fallback="").strip(),
        "report_sheet": cp.get("excel", "report_sheet", fallback="Отчёт"),
        "report_date_cell": cp.get("excel", "report_date_cell", fallback="C4"),
        "telegram_text_range": cp.get("excel", "telegram_text_range", fallback="Telegram_текст"),
        "query_name": cp.get("excel", "query_name", fallback="База_продаж"),
        "refresh_timeout_min": cp.getint("excel", "refresh_timeout_min", fallback=30),
        "state_file": cp.get("general", "state_file", fallback=os.path.join(HERE, "sent_state.json")),
        "log_file": cp.get("general", "log_file", fallback=os.path.join(HERE, "logs", "skidki_report.log")),
    }
    if not cfg["bot_token"] or "PASTE" in cfg["bot_token"]:
        sys.exit("Telegram bot token is not set (config.ini [telegram] bot_token or env TELEGRAM_BOT_TOKEN).")
    return cfg


def setup_logging(log_file):
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    log.setLevel(logging.INFO)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)


# --------------------------------------------------------------------------
# Dates / file names (pure logic, unit-tested)
# --------------------------------------------------------------------------

def report_date_for(today):
    """Report is sent today for yesterday."""
    return today - dt.timedelta(days=1)


def month_key(d):
    return f"{d.year:04d}-{d.month:02d}"


def month_bounds(d):
    first = d.replace(day=1)
    nxt = (first + dt.timedelta(days=32)).replace(day=1)
    return first, nxt


def monthly_file_path(folder, base_name, d):
    return os.path.join(folder, f"{base_name} {month_key(d)}.xlsx")


def find_previous_monthly_file(folder, base_name, d):
    """Latest existing "<base> YYYY-MM.xlsx" for a month before d's month."""
    current = month_key(d)
    pattern = re.compile(re.escape(base_name) + r" (\d{4}-\d{2})\.xlsx$", re.IGNORECASE)
    candidates = []
    for p in glob.glob(os.path.join(folder, "*.xlsx")):
        m = pattern.search(os.path.basename(p))
        if m and m.group(1) < current:
            candidates.append((m.group(1), p))
    return max(candidates)[1] if candidates else None


# Matches the date-filter step of the "База_продаж" query, e.g.
#   Table.SelectRows(#"Измененный тип", each [Дата2] > #date(2026, 9, 30)),
DATE_FILTER_RE = re.compile(
    r'(Table\.SelectRows\(#"Измененный тип", each )(\[Дата2\][^\r\n]*?)(\),[ \t]*\r?\n)'
)


def set_month_filter(formula, d):
    """Return the M formula with the [Дата2] filter limited to d's month."""
    first, nxt = month_bounds(d)
    condition = (
        f"[Дата2] >= #date({first.year}, {first.month}, 1) and "
        f"[Дата2] < #date({nxt.year}, {nxt.month}, 1)"
    )
    new, n = DATE_FILTER_RE.subn(lambda m: m.group(1) + condition + m.group(3), formula, count=1)
    if n == 0:
        raise RuntimeError("Could not find the [Дата2] date filter step in the Power Query formula")
    return new


def to_excel_serial(d):
    return (d - EXCEL_EPOCH).days


def range_values_to_text(values):
    """Excel range .Value (tuple of 1-tuples) -> message text; trailing blanks dropped."""
    if values is None:
        return ""
    if not isinstance(values, (tuple, list)):
        values = ((values,),)
    lines = []
    for row in values:
        v = row[0] if isinstance(row, (tuple, list)) else row
        lines.append("" if v is None else str(v).replace("¶", "").rstrip())
    while lines and not lines[-1]:
        lines.pop()
    while lines and not lines[0]:
        lines.pop(0)
    return "\n".join(lines)


def split_message(text, limit=TELEGRAM_TEXT_LIMIT):
    """Split on line boundaries into chunks <= limit."""
    chunks, current = [], ""
    for line in text.split("\n"):
        while len(line) > limit:  # a single huge line
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = line if not current else current + "\n" + line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current.strip():
        chunks.append(current)
    return chunks


# --------------------------------------------------------------------------
# Step 1: Excel
# --------------------------------------------------------------------------

def ensure_monthly_file(cfg, report_date):
    target = monthly_file_path(cfg["report_folder"], cfg["file_base_name"], report_date)
    if os.path.exists(target):
        return target, False
    source = find_previous_monthly_file(cfg["report_folder"], cfg["file_base_name"], report_date)
    if not source:
        source = cfg["template_file"]
    if not source or not os.path.exists(source):
        raise FileNotFoundError(
            f"No file for {month_key(report_date)} and no previous month / template file to copy from "
            f"(template_file = {cfg['template_file']!r})"
        )
    log.info("New month %s: creating %s from %s", month_key(report_date), target, source)
    shutil.copy2(source, target)
    return target, True


def refresh_workbook(cfg, path, report_date):
    """Open, enable editing, set date, Refresh All, wait, save, close.

    Returns the Telegram text read from the refreshed workbook.
    """
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    excel = win32com.client.DispatchEx("Excel.Application")  # own Excel instance
    excel.Visible = False
    excel.DisplayAlerts = False
    excel.AskToUpdateLinks = False
    wb = None
    try:
        log.info("Opening %s", path)
        wb = excel.Workbooks.Open(path, UpdateLinks=0, ReadOnly=False)
        # "Enable Editing": if the file came up in Protected View, switch to edit mode.
        if excel.ProtectedViewWindows.Count > 0:
            wb = excel.ProtectedViewWindows(1).Edit()
        if wb.ReadOnly:
            raise RuntimeError(f"{path} is opened read-only (probably open by another user) - cannot save")

        # Make sure the Power Query covers exactly this month.
        query = wb.Queries(cfg["query_name"])
        new_formula = set_month_filter(query.Formula, report_date)
        if new_formula != query.Formula:
            log.info("Setting Power Query '%s' filter to %s", cfg["query_name"], month_key(report_date))
            query.Formula = new_formula

        # Report date = yesterday.
        wb.Worksheets(cfg["report_sheet"]).Range(cfg["report_date_cell"]).Value2 = to_excel_serial(report_date)

        # Synchronous refresh: turn off background refresh so RefreshAll blocks.
        for conn in wb.Connections:
            try:
                conn.OLEDBConnection.BackgroundQuery = False
            except Exception:
                pass

        log.info("Refresh All ...")
        started = time.time()
        wb.RefreshAll()
        excel.CalculateUntilAsyncQueriesDone()
        timeout = cfg["refresh_timeout_min"] * 60
        while _any_refreshing(wb):
            if time.time() - started > timeout:
                raise TimeoutError(f"Refresh did not finish in {cfg['refresh_timeout_min']} min")
            time.sleep(2)
        excel.CalculateFull()
        log.info("Refresh finished in %.0f s", time.time() - started)

        text = range_values_to_text(wb.Names(cfg["telegram_text_range"]).RefersToRange.Value)

        wb.Save()
        log.info("Saved %s", path)
        return text
    finally:
        if wb is not None:
            try:
                wb.Close(SaveChanges=False)
            except Exception:
                pass
        excel.Quit()
        del excel
        pythoncom.CoUninitialize()


def _any_refreshing(wb):
    for conn in wb.Connections:
        try:
            if conn.OLEDBConnection.Refreshing:
                return True
        except Exception:
            pass
    return False


def read_telegram_text(cfg, path):
    """Read the Telegram text without refreshing (used by --send-only)."""
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Open(path, UpdateLinks=0, ReadOnly=True)
        try:
            return range_values_to_text(wb.Names(cfg["telegram_text_range"]).RefersToRange.Value)
        finally:
            wb.Close(SaveChanges=False)
    finally:
        excel.Quit()
        pythoncom.CoUninitialize()


# --------------------------------------------------------------------------
# Step 2: Telegram
# --------------------------------------------------------------------------

class Telegram:
    def __init__(self, token):
        self.base = f"https://api.telegram.org/bot{token}"

    def _call(self, method, retries=4, **kwargs):
        for attempt in range(retries):
            try:
                r = requests.post(f"{self.base}/{method}", timeout=120, **kwargs)
                data = r.json()
                if data.get("ok"):
                    return data["result"]
                if r.status_code == 429:  # flood control
                    time.sleep(data.get("parameters", {}).get("retry_after", 5))
                    continue
                raise RuntimeError(f"Telegram {method} failed: {data.get('description')}")
            except (requests.ConnectionError, requests.Timeout) as e:
                if attempt == retries - 1:
                    raise
                wait = 2 ** (attempt + 1)
                log.warning("Telegram %s network error (%s), retry in %ss", method, e, wait)
                time.sleep(wait)
        raise RuntimeError(f"Telegram {method} failed after {retries} attempts")

    def send_message(self, chat_id, text):
        return self._call("sendMessage", data={"chat_id": chat_id, "text": text})

    def send_document(self, chat_id, path, caption=""):
        with open(path, "rb") as f:
            files = {"document": (os.path.basename(path), f)}
            return self._call("sendDocument", data={"chat_id": chat_id, "caption": caption[:TELEGRAM_CAPTION_LIMIT]}, files=files)


def send_report(cfg, path, report_date, text):
    tg = Telegram(cfg["bot_token"])
    caption = f"📊 {cfg['file_base_name']} за {report_date:%d.%m.%Y}"
    log.info("Sending %s to chat %s", os.path.basename(path), cfg["chat_id"])
    tg.send_document(cfg["chat_id"], path, caption)
    if cfg["send_text"] and text:
        for chunk in split_message(text):
            tg.send_message(cfg["chat_id"], chunk)
    log.info("Sent")


def notify_admin(cfg, message):
    if not cfg.get("admin_chat_id"):
        return
    try:
        Telegram(cfg["bot_token"]).send_message(cfg["admin_chat_id"], message[:TELEGRAM_TEXT_LIMIT])
    except Exception:
        log.exception("Could not notify admin")


# --------------------------------------------------------------------------
# Sent-state (avoid double sending when the task is re-run)
# --------------------------------------------------------------------------

def already_sent(state_file, report_date):
    try:
        with open(state_file, encoding="utf-8") as f:
            return report_date.isoformat() in json.load(f).get("sent", [])
    except (FileNotFoundError, ValueError):
        return False


def mark_sent(state_file, report_date):
    try:
        with open(state_file, encoding="utf-8") as f:
            state = json.load(f)
    except (FileNotFoundError, ValueError):
        state = {}
    sent = set(state.get("sent", []))
    sent.add(report_date.isoformat())
    state["sent"] = sorted(sent)[-120:]
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--date", help="report date YYYY-MM-DD (default: yesterday)")
    ap.add_argument("--no-send", action="store_true", help="refresh only, do not send")
    ap.add_argument("--send-only", action="store_true", help="send only, skip Excel refresh")
    ap.add_argument("--force", action="store_true", help="send even if this date was already sent")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    setup_logging(cfg["log_file"])

    report_date = dt.date.fromisoformat(args.date) if args.date else report_date_for(dt.date.today())
    log.info("=== Report date %s (file month %s) ===", report_date, month_key(report_date))

    if not args.no_send and not args.force and already_sent(cfg["state_file"], report_date):
        log.info("Report for %s was already sent - nothing to do (use --force to resend)", report_date)
        return 0

    try:
        path, created = ensure_monthly_file(cfg, report_date)
        if args.send_only:
            text = read_telegram_text(cfg, path)
        else:
            text = refresh_workbook(cfg, path, report_date)
        if not args.no_send:
            send_report(cfg, path, report_date, text)
            mark_sent(cfg["state_file"], report_date)
        return 0
    except Exception as e:
        log.exception("FAILED")
        notify_admin(cfg, f"⚠ Скидки отчёт за {report_date:%d.%m.%Y} не отправлен: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
