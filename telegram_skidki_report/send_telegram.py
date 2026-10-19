"""
STEP 2 - send the refreshed report to the Telegram group.

* Sends yesterday's report: the monthly file "Скидки отчёт YYYY-MM.xlsx" + text.
* Catch-up: if some days were missed (PC off, error, ...), every day after the
  last sent one up to yesterday is sent separately, oldest first.
* Sends ONLY if refresh_report.py finished successfully for that day
  (state/refreshed_YYYY-MM-DD.txt exists) - an old file is never sent.
* Never sends the same day twice (state/sent_YYYY-MM-DD.txt).
* Remembers the ids of the sent messages (state/messages_YYYY-MM-DD.json)
  so delete_last_report.py can remove them if the report was wrong.

Run:  python send_telegram.py                    (all missed days up to yesterday)
      python send_telegram.py 2026-10-15         (a specific day)
      python send_telegram.py 2026-10-15 --force (send again / without refresh)

Needs: pip install requests
Bot token: Windows environment variable TELEGRAM_BOT_TOKEN (already set),
           or put it in BOT_TOKEN below.
"""

import datetime as dt
import glob
import json
import logging
import os
import sys
import time

import requests

# ============================ SETTINGS ============================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = "-1004431975944"
REPORT_FOLDER = r"\\192.168.1.101\Auditor\AUDIT\Скидки\Скидки отчёт"
FILE_BASE_NAME = "Скидки отчёт"
SEND_TEXT = True  # also send the text from the "Telegram" sheet
MAX_CATCHUP_DAYS = 31  # never go further back than this
# ==================================================================

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HERE, "state")
LOG_FILE = os.path.join(HERE, "logs", "send.log")
API = "https://api.telegram.org/bot{}/{}"

log = logging.getLogger("send")


def setup_logging():
    if log.handlers:
        return
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()):
        h.setFormatter(fmt)
        log.addHandler(h)


def telegram(method, data, files=None):
    """Call the Telegram API, retrying on network errors and flood limits."""
    for attempt in range(5):
        for f in (files or {}).values():  # rewind the file for a retry
            f[1].seek(0)
        try:
            r = requests.post(API.format(BOT_TOKEN, method), data=data, files=files, timeout=120)
            result = r.json()
            if result.get("ok"):
                return result["result"]
            if r.status_code == 429:
                time.sleep(result.get("parameters", {}).get("retry_after", 5))
                continue
            raise RuntimeError(f"Telegram {method}: {result.get('description')}")
        except (requests.ConnectionError, requests.Timeout) as e:
            log.warning("Network error (%s), retrying ...", e)
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"Telegram {method}: failed after retries")


def remember_message(report_date, message):
    """Append a sent message id to state/messages_YYYY-MM-DD.json."""
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, f"messages_{report_date}.json")
    try:
        with open(path, encoding="utf-8") as f:
            ids = json.load(f)
    except (FileNotFoundError, ValueError):
        ids = []
    ids.append(message["message_id"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ids, f)


def split_text(text, limit=4096):
    """Split into Telegram-sized messages on line boundaries."""
    parts, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(line[:limit])
            line = line[limit:]
        if cur and len(cur) + 1 + len(line) > limit:
            parts.append(cur)
            cur = line
        else:
            cur = line if not cur else cur + "\n" + line
    if cur.strip():
        parts.append(cur)
    return parts


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


def send_day(day, force=False):
    """Send one day's report. Returns True if sent (or already sent)."""
    refreshed = os.path.join(STATE_DIR, f"refreshed_{day}.txt")
    sent = os.path.join(STATE_DIR, f"sent_{day}.txt")
    monthly = os.path.join(REPORT_FOLDER, f"{FILE_BASE_NAME} {day:%Y-%m}.xlsx")
    snapshot = os.path.join(STATE_DIR, "files", f"{FILE_BASE_NAME} {day}.xlsx")  # copy made for that day
    if os.path.exists(sent) and not force:
        log.info("%s: already sent", day)
        return True
    if not os.path.exists(refreshed) and not force:
        raise RuntimeError(f"File was not refreshed for {day} - run refresh_report.py first")
    path = snapshot if os.path.exists(snapshot) else monthly
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    with open(path, "rb") as f:
        msg = telegram("sendDocument",
                       {"chat_id": CHAT_ID, "caption": f"📊 {FILE_BASE_NAME} за {day:%d.%m.%Y}"},
                       files={"document": (os.path.basename(monthly), f)})
    remember_message(day, msg)
    log.info("%s: file sent", day)

    if SEND_TEXT and os.path.exists(refreshed):
        with open(refreshed, encoding="utf-8") as f:
            for part in split_text(f.read()):
                remember_message(day, telegram("sendMessage", {"chat_id": CHAT_ID, "text": part}))
        log.info("%s: text sent", day)

    with open(sent, "w", encoding="utf-8") as f:
        f.write(dt.datetime.now().isoformat())
    if path == snapshot:
        os.remove(snapshot)
    return True


def main():
    setup_logging()
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    days = [dt.date.fromisoformat(args[0])] if args else pending_days(dt.date.today())
    log.info("=== SEND: %s ===", ", ".join(map(str, days)) or "nothing to send")
    try:
        if not BOT_TOKEN:
            raise RuntimeError("Bot token not set (environment variable TELEGRAM_BOT_TOKEN)")
        os.makedirs(STATE_DIR, exist_ok=True)
        for i, day in enumerate(days):
            if i:
                time.sleep(3)  # stay well inside Telegram's group rate limit
            send_day(day, force)  # stops at the first failing day so the order is kept
        log.info("DONE")
        return 0
    except Exception:
        log.exception("SEND FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
