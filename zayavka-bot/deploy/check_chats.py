"""
Checks every chat the bot posts zayavka Excel files to (PERSON_ROUTES in .env):
what kind of chat it is, whether the bot may delete / edit its old messages
there (needed to remove outdated versions after an edit), how many sent
messages it remembers for that chat, and the last cleanup errors in the log.

Run from the zayavka-bot folder:
  .venv\\Scripts\\python.exe deploy\\check_chats.py
"""
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import BOT_TOKEN, PERSON_ROUTES  # noqa: E402


def call(method: str, **params) -> dict:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)
    except (urllib.error.URLError, OSError) as e:
        return {"ok": False, "description": f"network error: {e}"}


def main() -> None:
    me = call("getMe")
    if not me.get("ok"):
        desc = str(me.get("description"))
        print(("Cannot reach Telegram: " if desc.startswith("network error") else "BOT TOKEN REJECTED by Telegram: ") + desc)
        return
    bot_id = me["result"]["id"]
    print(f"Bot @{me['result']['username']}\n")

    remembered = {}
    try:
        db = sqlite3.connect("zayavka.db")
        remembered = dict(db.execute("select chat_id, count(*) from sent_documents group by chat_id").fetchall())
    except sqlite3.Error:
        pass
    log_lines = []
    try:
        with open(os.path.join("logs", "api.log"), encoding="utf-8", errors="replace") as f:
            log_lines = [ln.rstrip() for ln in f if "old zayavka message" in ln]
    except OSError:
        pass

    for person, chat_id in PERSON_ROUTES.items():
        chat = call("getChat", chat_id=chat_id)
        if not chat.get("ok"):
            print(f"{person}  ({chat_id}): CANNOT REACH CHAT - {chat.get('description')}\n")
            continue
        c = chat["result"]
        m = call("getChatMember", chat_id=chat_id, user_id=bot_id).get("result", {})
        print(f"{person}  ->  '{c.get('title')}'  ({chat_id}, {c.get('type')})")
        print(f"   bot: {m.get('status')} | delete messages: {m.get('can_delete_messages')} | "
              f"edit messages: {m.get('can_edit_messages')} | post messages: {m.get('can_post_messages')}")
        print(f"   sent messages remembered for cleanup: {remembered.get(chat_id, 0)}")
        errors = [ln for ln in log_lines if str(chat_id) in ln][-3:]
        for ln in errors:
            print("   log:", ln[:220])
        print()


if __name__ == "__main__":
    main()
