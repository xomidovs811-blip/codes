# Running Zayavka bot on a Linux server

Two processes run permanently as systemd services (auto-start on boot, auto-restart on crash):

| Service        | What it does                                          |
|----------------|-------------------------------------------------------|
| `zayavka-api`  | FastAPI on port 8000: the Mini App pages + `/api/...` |
| `zayavka-bot`  | Telegram bot (polling)                                |

The Mini App pages (jadval / qidirish / items) must be opened over a **permanent https URL**.
The old `*.trycloudflare.com` URL was a temporary tunnel from your PC and is gone now.

## 1. Put the project on the server

Use the folder you already copied (it has your `.env` and `zayavka.db` with all saved zayavkas).
**Stop the bot on your PC first.** Two copies polling the same token make Telegram return a `Conflict` error.

## 2. Install and start

```bash
cd /path/to/zayavka-bot
sudo bash deploy/setup_server.sh 203-0-113-5.sslip.io   # replace with YOUR server IP, dots -> dashes
```

* No domain needed: `<ip-with-dashes>.sslip.io` resolves to your server's IP. Caddy then gets a free
  Let's Encrypt certificate for it. If you own a domain, point an A-record at the server and use that instead.
* Ports **80 and 443** must be open (also in your hosting provider's firewall/security group).
* The script writes `WEBAPP_URL=https://<domain>` into `.env` for you.

## 3. Update the Mini App URLs in @BotFather (one time)

`/myapps` → your bot → each app → *Edit Web App URL*:

* `jadval`   → `https://<domain>/table.html`
* `qidirish` → `https://<domain>/search.html`

The bot re-points the chat menu buttons automatically when it starts.

## Everyday commands

```bash
sudo systemctl status zayavka-bot zayavka-api
sudo systemctl restart zayavka-bot zayavka-api    # after editing .env or code
journalctl -u zayavka-bot -f                      # live logs
cp zayavka.db ~/zayavka-$(date +%F).db            # backup the database
```
