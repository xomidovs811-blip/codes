# Zayavka Telegram Bot

A Telegram bot for entering, listing and searching "Zayavka" (request)
records, matching your real working template (`15.09.2026-2.xlsx`):

- **Zayavka berish** — a step-by-step chat wizard (the bot asks one question
  at a time: object → date → from → payment → each item row) and finishes by
  generating and sending back a **.xlsx file** built to match your template
  exactly, formulas included.
- **Zayavkalar jadvali** — a Mini App page listing/filtering all submitted
  zayavkas.
- **Zayavkani qidirish** — a Mini App page for free-text search.

Everything is also stored in a real database (SQLite by default,
Postgres-ready), which is what powers jadval/qidirish.

## What changed from the first version

Based on your uploaded example file and follow-up messages:

- **Zayavka berish is now a chat wizard**, not a web form. It's a private
  conversation with the bot — see "Using it inside a group or channel" below
  for how that's reached from a group/channel.
- **Reference lists now come from your real `справочник` sheet**: 13
  objects, 6 people for От кого, Вид оплаты as a dropdown (Накт /
  Перечесление, not fixed), and a 17-option Выполняемая работа (сметная
  группа) dropdown. All in `app/config.py`.
- **Номер заявки now matches your real formula exactly**:
  `DAY-MONTH-(first 2 digits of row 1's Общая сумма)-(object letter)-(from letter)`,
  no year — e.g. `15-9-14-Я-К` for your example row (6 × 2,400,000, object
  Янги Шодиёна, from Курбонов Равшан). Verified against your file's cached
  value.
- **Output is now a real .xlsx**, built to match your template's layout,
  labels and formulas (Общая сумма, Остатка, Итого, Сумма заявки, and even
  the Заявитель/Директор auto-fill) — see `app/excel_gen.py`.

## Project structure

```
zayavka-bot/
├── app/
│   ├── bot.py           Telegram bot (aiogram) — menu, commands, channel post
│   ├── wizard.py         The step-by-step "Zayavka berish" chat wizard (FSM)
│   ├── excel_gen.py       Builds the .xlsx matching your template
│   ├── services.py        Shared "save a zayavka" logic (used by wizard + API)
│   ├── api.py             FastAPI app — REST API + serves the 2 Mini App pages
│   ├── models.py          SQLAlchemy models (Zayavka, ZayavkaItem)
│   ├── code_gen.py       Номер заявки generator (matches your real formula)
│   ├── tg_auth.py         Validates Telegram Mini App initData (security)
│   └── config.py          Env vars + all dropdown/reference lists
├── webapp/
│   ├── table.html          "Zayavkalar jadvali" (Mini App)
│   ├── search.html         "Zayavkani qidirish" (Mini App)
│   └── js/ css/            frontend logic & styling
├── run_api.py / run_bot.py    separate entrypoints (for 2-process hosting)
├── Procfile                for platforms like Railway/Render
└── requirements.txt
```

## Editing the reference lists

Open `app/config.py`:

```python
OBJECTS = [...]        # 13 objects from your справочник sheet
FROM_WHOM = [...]      # 6 people
PAYMENT_TYPES = [...]  # Накт, Перечесление
WORK_TYPES = [...]     # 17 Выполняемая работа options
UNIT_OPTIONS = [...]   # quick-pick units in the wizard (шт, кв.м, ...)
```

Restart the bot process after editing (the wizard reads these at import time).

## Running it locally (to test before deploying)

```bash
cd zayavka-bot
pip install -r requirements.txt --break-system-packages   # or use a venv
cp .env.example .env   # already pre-filled with your bot token for convenience
```

Run the API and the bot (two terminals):

```bash
python run_api.py     # serves the mini app + API on http://localhost:8000
python run_bot.py      # starts the Telegram bot polling loop
```

**Important:** the Mini App pages (jadval/qidirish) still need a real
**https://** URL — `http://localhost:8000` won't open inside Telegram. Use
`ngrok`/`cloudflared` for local testing, point `WEBAPP_URL` at that. The
chat wizard itself (Zayavka berish) doesn't need `WEBAPP_URL` at all — it's
plain bot messages.

I tested every piece I could without live Telegram access: the Excel
generator (verified with LibreOffice's formula engine — all totals,
Остатка, Итого and the Номер заявки formula compute correctly and match
your file's cached values), the full wizard conversation logic (simulated
end-to-end, including saving to the database and generating the file), and
the jadval/qidirish Mini App pages. A sample generated .xlsx is attached so
you can open it yourself. I could **not** test the live Telegram connection
itself from this sandbox (its network is locked to package registries, not
`api.telegram.org`) — please test `/zayavka` for real once you run this on
your machine or deploy it.

## Deploying (Railway recommended)

1. Push this project to a GitHub repo (`.gitignore` already excludes `.env`
   and the local database).
2. On [railway.app](https://railway.app), create a new project from that repo.
3. Add a Postgres plugin (optional but recommended; otherwise SQLite resets
   on redeploy).
4. Set environment variables (Settings → Variables):
   `BOT_TOKEN`, `WEBAPP_URL` (fill after step 6), `DATABASE_URL` (if using
   Postgres — remember to add `psycopg2-binary` to `requirements.txt`),
   `ALLOWED_GROUP_IDS`, `CHANNEL_ID`, `ADMIN_IDS`.
5. Railway detects the `Procfile` → two services: `web` (API + mini app) and
   `worker` (the bot). Deploy both.
6. Copy the `web` service's public domain, set it as `WEBAPP_URL`, redeploy
   `worker`.
7. Message your bot with `/zayavka` to confirm the wizard starts.

## Using it inside a group or channel

**Zayavka berish** is a conversation, so it can only run in a private chat
with the bot — a group or channel can't hold a per-user back-and-forth.
Whenever `/zayavka` (or the "📝 Zayavka berish" button) is used in a group or
channel, it deep-links each person into a private chat with the bot
(`t.me/<bot>?start=zayavka`), where the wizard starts immediately.

**Zayavkalar jadvali / Zayavkani qidirish** stay Mini App pages, and use
"Direct Link Mini Apps" (`t.me/<bot>/<short_name>`) so they open straight
from a group or channel post too. One-time setup — register these two with
**@BotFather**:

1. Message **@BotFather**, send `/newapp`, choose your bot.
2. Title (e.g. "Zayavkalar jadvali"), short description, a 640×360 photo
   (any placeholder works).
3. Web App URL: your real deployed `WEBAPP_URL/table.html`.
4. Short name: `jadval` (must match `MINIAPP_JADVAL` in `.env`).
5. Repeat once more: short name `qidirish` → Web App URL `WEBAPP_URL/search.html`.

Do this after deploying (or after starting an ngrok/cloudflared tunnel),
since `WEBAPP_URL` needs to already be a real https address.

### Your group (`-1004293323432`)

Add the bot as a normal member. Anyone can send `/zayavka` there; the bot
replies with buttons. `ALLOWED_GROUP_IDS=-1004293323432` is already set in
your `.env`, so it only responds in this group (ignoring any other group it
might get added to).

### Your channel (`-1004383641060`)

Channels are broadcast-only — regular subscribers can't type `/start` there
directly, so the flow is: an admin publishes one post with the button, and
subscribers tap it.

1. Add the bot to the channel as an **admin**, with at least "Post Messages"
   permission.
2. `CHANNEL_ID=-1004383641060` is already set in your `.env`.
3. Open a **private chat** with the bot yourself and send `/post_channel_menu`.
   The bot posts the Zayavka menu into the channel. Pin that post if you want
   it always visible.
4. Any subscriber taps "📝 Zayavka berish" → gets deep-linked into their own
   private chat with the bot → wizard starts. Tapping "📋 Zayavkalar jadvali"
   / "🔎 Zayavkani qidirish" opens those Mini App pages directly from the
   channel.

`/post_channel_menu` is admin-only. `ADMIN_IDS` in `.env` is currently empty,
meaning **anyone** who messages the bot privately can run it — fine for now,
but set it to your own Telegram user id (comma-separated if more than one
person should be able to) once other people start using the bot, so random
users can't spam your channel.

## Security note

You shared the bot token in our chat. It's stored only in `.env` (git-ignored)
and used only to talk to the Telegram API. Since it appeared in plain text in
this conversation, it's worth regenerating via **@BotFather → /mybots → your
bot → API Token → Revoke** once you're done testing.

## What's not built yet

- Editing/updating an already-submitted zayavka
- Role-based access (who can see all zayavkas vs. just their own)
- Notifications to a group/channel when a new zayavka is submitted
- Recreating the "ИТОГО <supplier>" subtotal break rows your example file
  had between different suppliers/workers — I treated those as a manual
  office step done after the fact, not something the wizard should
  auto-insert. Say the word if you actually want that automated.

Happy to add any of these next — just say which.
