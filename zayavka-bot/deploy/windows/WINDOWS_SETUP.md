# Running Zayavka bot on a Windows server

After setup, three background tasks start automatically when Windows boots (nobody needs to be logged in),
and each restarts itself if it crashes:

| Task            | What it does                                               |
|-----------------|------------------------------------------------------------|
| `Zayavka API`   | Mini App pages + `/api/...` on port 8000                   |
| `Zayavka Bot`   | Telegram bot                                               |
| `Zayavka Caddy` | Permanent `https://` address with a free SSL certificate   |

## 1. Stop the bot on your old PC

Close the old `python run_bot.py` / cloudflared windows on your PC. Two copies running with the same
token make Telegram return a `Conflict` error.

## 2. Put the files in place

Extract `zayavka-windows-deploy.zip` **into your zayavka-bot folder** (the one with `run_bot.py`, `.env`,
`zayavka.db`), so you get `zayavka-bot\deploy\windows\setup_windows.ps1`.

## 3. Run setup

Start menu -> right-click **Windows PowerShell** -> **Run as administrator**, then:

```powershell
cd C:\path\to\zayavka-bot
powershell -ExecutionPolicy Bypass -File deploy\windows\setup_windows.ps1 -Domain auto
```

`-Domain auto` looks up the server's public IP and uses the free address `<ip-with-dashes>.sslip.io`.
If you own a domain pointed at this server, pass it instead: `-Domain bot.example.uz`.

It installs Python if it's missing, installs the packages, opens ports 80/443 in Windows Firewall,
writes the new `WEBAPP_URL` into `.env` and starts everything. At the end, open the printed
`.../table.html` address in a browser. It should load a page.

> If your hosting provider has its own firewall or "security group" panel, open TCP **80** and **443** there too.

## 4. Update the Mini App URLs in @BotFather (one time)

`/myapps` -> your bot -> each app -> *Edit Web App URL*:

* `jadval`   -> `https://<address>/table.html`
* `qidirish` -> `https://<address>/search.html`

The bot re-points the chat menu buttons automatically on start.

## Everyday commands (PowerShell as administrator, inside the zayavka-bot folder)

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\manage.ps1 status
powershell -ExecutionPolicy Bypass -File deploy\windows\manage.ps1 restart   # after editing .env or code
powershell -ExecutionPolicy Bypass -File deploy\windows\manage.ps1 logs
```

Back up your data by copying `zayavka.db` somewhere safe from time to time.
