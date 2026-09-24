import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "").rstrip("/")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./zayavka.db")

# "Кому" stays fixed (per your original spec) - not a dropdown.
FIXED_KOMU = os.getenv("FIXED_KOMU", "Далеров А.Д")

# Short names of the Mini Apps registered with @BotFather (via /newapp),
# used to build direct links (t.me/<bot_username>/<short_name>) that open a
# Mini App straight from a GROUP or CHANNEL, with no private-chat detour.
# Only Zayavkalar jadvali / Zayavkani qidirish still use the Mini App - the
# Zayavka berish flow is now the chat wizard in bot.py.
MINIAPP_JADVAL = os.getenv("MINIAPP_JADVAL", "jadval")
MINIAPP_QIDIRISH = os.getenv("MINIAPP_QIDIRISH", "qidirish")

# Optional: restrict the group-chat menu to specific group(s) only.
# Comma-separated chat ids, e.g. "-1004293323432". Leave empty to allow any group.
_allowed = os.getenv("ALLOWED_GROUP_IDS", "").strip()
ALLOWED_GROUP_IDS = [int(x) for x in _allowed.split(",") if x.strip()] if _allowed else []

# The broadcast-only channel this bot posts its "open the bot" button into.
# Regular channel members can't type /start there directly (channels are
# broadcast-only), so an admin uses /post_channel_menu to publish a button
# that deep-links each subscriber into a private chat with the bot.
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0")) or None

# Telegram user ids allowed to run admin-only commands (e.g. /post_channel_menu).
_admins = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS = [int(x) for x in _admins.split(",") if x.strip()] if _admins else []

# Per-person routing: when "От кого" equals one of these names, the finished
# zayavka file goes ONLY to that person's own chat id instead of the normal
# ALLOWED_GROUP_IDS/CHANNEL_ID. Format: "Name1:chatid1,Name2:chatid2".
# Example: PERSON_ROUTES=Курбонов Равшан:-1001234567890
_person_routes = os.getenv("PERSON_ROUTES", "").strip()
PERSON_ROUTES = {}
if _person_routes:
    for pair in _person_routes.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        name, chat_id = pair.rsplit(":", 1)
        name = name.strip()
        chat_id = chat_id.strip()
        if name and chat_id.lstrip("-").isdigit():
            PERSON_ROUTES[name] = int(chat_id)

# A person with no channel of their own (no PERSON_ROUTES entry): should their
# form ALSO be posted to the shared ALLOWED_GROUP_IDS chat(s)? Off by default -
# forms must not appear in a channel that isn't the applier's. Set
# POST_UNROUTED_TO_DEFAULT=1 to restore the old fallback.
POST_UNROUTED_TO_DEFAULT = os.getenv("POST_UNROUTED_TO_DEFAULT", "0").strip() == "1"

# --- Reference lists, taken from the "справочник" sheet of your real
# working template (15.09.2026-2.xlsx) - this is the source of truth now. ---

OBJECTS = [
    "Хавли",
    "Техникум",
    "Атлас-дом",
    "Гагарин дом",
    "Хаваси",
    "ОАЗИС гарден",
    "Зармед Университет",
    "Тумар",
    "Янги Шодиёна",
    "Янги Кампус",
    "Клиника Карши",
    "Исаева 38",
    "Гор больница",
]

FROM_WHOM = [
    "Фахриев Азим",
    "Асадов Сухроб",
    "Курбонов Равшан",
    "Рахимов Мухаммад",
    "Игамбердиев Далер",
    "Нарзикулов Суръат",
]

# Вид оплаты is a dropdown, not fixed (spelled exactly as in your file).
PAYMENT_TYPES = [
    "Накт",
    "Перечесление",
]

# "Выполняемая работа (сметная группа)" - the starting list. It's seeded into
# the database (NameOption category "work_type") the first time the API runs;
# after that the list is managed in the Mini App (add by typing, delete via
# the manage button), and this constant is also what fills the Excel's hidden
# справочник sheet dropdown.
WORK_TYPES = [
    "Ер ва пойдевор ишлари (котлован, кавлаш, кайта тулдириш, зичлаш, опалубка, арматура, бетон, гидроизоляция)",
    "Девор ва каркас ишлари (корказ, арматура, бетон, гишт, блок в/б)",
    "Ташки ишлар (дренаж, ташки тармоклар: сув, канализация, электр, газ в/б)",
    "Ички ишлар (электр, пардоз, штукатурка, шпатлёвка, гипсокартон, шифт в/б)",
    "Фасад (штукатурка, утепление, облицовка, буёк в/б)",
    "Техника ва ускуна ижараси( кран, экскаватор в/б)",
    "Курилиш материаллари",
    "Доставка (курилиш материаллари)",
    "Доставка (Мусор)",
    "Ишчи кучи ва транспорт (ишчилар, мутахасислар, менежемент, такси в/б)",
    "Озик овкат таъминоти",
    "Ёқилғи харажатлари",
    "Бошкалар",
    "Аванс",
    "Тайёрлов ишлари (геодезия, рухсатнома, майдонни тозалаш)",
    "Ораёпма ва зинапоя ишлари (плита, монолит, зина, парапет)",
    "Том ва томёпма ишлари (стропила, утепление, водосток)",
    "Дераза, эшик ва витраж ишлари (материал ва урнатиш)",
    "Пол ва қоплама ишлари (стяжка, плитка, ламинат)",
    "Сантехника ва сув таъминоти (водопровод, канализация)",
    "Иситиш ва кондиционер ишлари (отопление, котёл, радиатор, HVAC)",
    "Газ таъминоти ишлари (ички газ жихозлари)",
    "Ободонлаштириш (асфальт, бордюр, йулак, туссик, кукаламзорлаштириш)",
    "Ёнгин хавфсизлиги ва сигнализация",
    "Лифт ва махсус ускуналар урнатиш",
    "Якуний ишлар (тозалаш, топшириш, кафолат таъмири)",
    "Отделка материаллари (буёк, плитка, шпатлёвка, гипсокартон)",
    "Электр ва сантехника материаллари",
    "Асбоб-ускуна ва инвентарь харид килиш (бурги, кийим, каска)",
    "Лойиха ва техназорат хизматлари",
]

# Quick-pick unit options in the chat wizard (users can still type a custom one).
UNIT_OPTIONS = ["шт", "кв.м", "метр", "кг", "литр", "дона"]

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")
