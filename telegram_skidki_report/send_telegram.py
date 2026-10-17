"""
STEP 2 - send the refreshed report to the Telegram group.

* Sends yesterday's monthly file "Скидки отчёт YYYY-MM.xlsx" + the report text.
* Sends ONLY if refresh_report.py finished successfully for that day
  (state/refreshed_YYYY-MM-DD.txt exists) - an old file is never sent.
* Never sends the same day twice (state/sent_YYYY-MM-DD.txt).

Run:  python send_telegram.py                    (yesterday)
      python send_telegram.py 2026-10-15         (a specific day)
      python send_telegram.py 2026-10-15 --force (send again / without refresh)

Needs: pip install requests
Bot token: Windows environment variable TELEGRAM_BOT_TOKEN (already set),
           or put it in BOT_TOKEN below.
"""

import datetime as dt
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
# ==================================================================

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HERE, "state")
LOG_FILE = os.path.join(HERE, "logs", "send.log")
API = "https://api.telegram.org/bot{}/{}"

log = logging.getLogger("send")


def setup_logging():
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


def main():
    setup_logging()
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    report_date = dt.date.fromisoformat(args[0]) if args else dt.date.today() - dt.timedelta(days=1)
    log.info("=== SEND for %s ===", report_date)

    refreshed = os.path.join(STATE_DIR, f"refreshed_{report_date}.txt")
    sent = os.path.join(STATE_DIR, f"sent_{report_date}.txt")
    path = os.path.join(REPORT_FOLDER, f"{FILE_BASE_NAME} {report_date:%Y-%m}.xlsx")
    try:
        if not BOT_TOKEN:
            raise RuntimeError("Bot token not set (environment variable TELEGRAM_BOT_TOKEN)")
        if os.path.exists(sent) and not force:
            log.info("Already sent for %s - nothing to do", report_date)
            return 0
        if not os.path.exists(refreshed) and not force:
            raise RuntimeError(f"File was not refreshed for {report_date} - run refresh_report.py first")
        if not os.path.exists(path):
            raise FileNotFoundError(path)

        with open(path, "rb") as f:
            telegram("sendDocument",
                     {"chat_id": CHAT_ID, "caption": f"📊 {FILE_BASE_NAME} за {report_date:%d.%m.%Y}"},
                     files={"document": (os.path.basename(path), f)})
        log.info("File sent: %s", os.path.basename(path))

        if SEND_TEXT and os.path.exists(refreshed):
            with open(refreshed, encoding="utf-8") as f:
                for part in split_text(f.read()):
                    telegram("sendMessage", {"chat_id": CHAT_ID, "text": part})
            log.info("Text sent")

        os.makedirs(STATE_DIR, exist_ok=True)
        with open(sent, "w", encoding="utf-8") as f:
            f.write(dt.datetime.now().isoformat())
        log.info("DONE")
        return 0
    except Exception:
        log.exception("SEND FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
