"""
Save YOUR private Telegram chat, where the scripts report whether they worked
(✅ / ❌ after every refresh and send). The group only gets the reports.

Before running: open the bot in Telegram, press Start (or send it any message),
and get your numeric ID from @userinfobot.
"""
import os
import sys

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HERE, "state")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("Bot token is not set - run «Сменить токен бота» first.")
        return 1
    chat_id = input("Paste your Telegram ID (a number from @userinfobot) and press Enter: ").strip()
    if not chat_id.lstrip("-").isdigit():
        print("That is not a number - nothing saved.")
        return 1
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30,
                      data={"chat_id": chat_id, "text": "✅ Сюда будут приходить сообщения о работе «Скидки отчёт»."}).json()
    if not r.get("ok"):
        print("Telegram refused:", r.get("description"))
        print("Open the bot in Telegram, press Start, and run this again.")
        return 1
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, "admin_chat_id.txt"), "w", encoding="utf-8") as f:
        f.write(chat_id)
    print("Saved. Check your Telegram - a test message was sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
