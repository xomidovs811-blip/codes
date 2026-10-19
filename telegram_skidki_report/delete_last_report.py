"""
Delete the last report the bot sent to the Telegram group
(the file + the text messages). Run it by hand when a report was wrong.

Run:  python delete_last_report.py              (the last sent report)
      python delete_last_report.py 2026-10-16   (the report for a specific day)
      python delete_last_report.py 11 12 13     (specific message ids)

After deleting, the day counts as "not sent", so you can fix the data and run
    python refresh_report.py 2026-10-16
    python send_telegram.py 2026-10-16

Telegram rule: the bot can delete its messages only within 48 hours of sending.
Bot token: Windows environment variable TELEGRAM_BOT_TOKEN.
"""

import glob
import json
import logging
import os
import re
import sys

import requests

# ============================ SETTINGS ============================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = "-1004431975944"
# ==================================================================

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HERE, "state")
LOG_FILE = os.path.join(HERE, "logs", "delete.log")
API = "https://api.telegram.org/bot{}/{}"

log = logging.getLogger("delete")


def setup_logging():
    if log.handlers:
        return
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()):
        h.setFormatter(fmt)
        log.addHandler(h)


def delete_message(message_id):
    r = requests.post(API.format(BOT_TOKEN, "deleteMessage"),
                      data={"chat_id": CHAT_ID, "message_id": message_id}, timeout=60)
    result = r.json()
    if not result.get("ok"):
        raise RuntimeError(result.get("description"))


def last_report_day():
    """Date (YYYY-MM-DD) of the newest state/messages_*.json, or None."""
    days = [re.search(r"messages_(\d{4}-\d{2}-\d{2})\.json$", p).group(1)
            for p in glob.glob(os.path.join(STATE_DIR, "messages_*.json"))]
    return max(days) if days else None


def main():
    setup_logging()
    args = sys.argv[1:]
    if not BOT_TOKEN:
        log.error("Bot token not set (environment variable TELEGRAM_BOT_TOKEN)")
        return 1

    day = None
    if args and all(a.isdigit() for a in args):
        ids = [int(a) for a in args]
    else:
        day = args[0] if args else last_report_day()
        if not day:
            log.error("No sent report found in %s", STATE_DIR)
            return 1
        try:
            with open(os.path.join(STATE_DIR, f"messages_{day}.json"), encoding="utf-8") as f:
                ids = json.load(f)
        except FileNotFoundError:
            log.error("No sent messages recorded for %s", day)
            return 1

    log.info("=== DELETE report %s: messages %s ===", day or "-", ids)
    failed = []
    for message_id in ids:
        try:
            delete_message(message_id)
            log.info("Deleted message %s", message_id)
        except Exception as e:
            log.error("Could not delete message %s: %s", message_id, e)
            failed.append(message_id)

    if day:
        if failed:
            with open(os.path.join(STATE_DIR, f"messages_{day}.json"), "w", encoding="utf-8") as f:
                json.dump(failed, f)
        else:
            os.remove(os.path.join(STATE_DIR, f"messages_{day}.json"))
        sent = os.path.join(STATE_DIR, f"sent_{day}.txt")
        if os.path.exists(sent):
            os.remove(sent)  # the day can be sent again
        log.info("Report %s is marked as not sent", day)

    if failed:
        log.error("NOT deleted: %s (older than 48 h, or bot is not admin with 'Delete messages' right)", failed)
        return 1
    log.info("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
