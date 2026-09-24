import asyncio
import logging

from aiogram import Bot, Dispatcher, Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
    BotCommand,
)

from app.config import (
    BOT_TOKEN,
    WEBAPP_URL,
    ALLOWED_GROUP_IDS,
    CHANNEL_ID,
    ADMIN_IDS,
    PERSON_ROUTES,
)
from app import wizard
from app.access import (
    access_for_user, flag_person_request, is_member, link_phone, normalize_phone, notify_admins, persons_for_user,
)
from app.db import SessionLocal, init_db
from app.models import BotMenuMessage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("zayavka-bot")

router = Router()

# table.html's Mini App URL never carries query params of its own (unlike
# items.html, which always has ?object=...&date=... etc. and so always
# looks "new" to Telegram). Without a cache-buster here, Telegram's WebView
# can keep serving a stale cached copy of the whole page indefinitely, even
# after the file on disk changes - bump this whenever table.html/its CSS/JS
# change in a way that needs to reach already-cached clients.
TABLE_HTML_VERSION = 21


def _table_html_url() -> str:
    return f"{WEBAPP_URL}/table.html?v={TABLE_HTML_VERSION}"


def _private_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Shown in a private chat with the bot. "Zayavka berish" starts the chat
    wizard directly (it's the same conversation, no need for a link).
    Zayavkalar jadvali stays a Mini App page, opened with a regular web_app
    button (works fine in private chats) - it already has its own filters,
    so there's no separate "qidirish" (search) entry point.
    """
    rows = [
        [InlineKeyboardButton(text="📝 Zayavka berish", callback_data="wiz:start")],
        [InlineKeyboardButton(
            text="📋 Zayavkalar jadvali",
            web_app=WebAppInfo(url=_table_html_url()),
        )],
    ]
    if CHANNEL_ID:
        rows.append([InlineKeyboardButton(
            text="📌 Kanal menyusini qayta joylash",
            callback_data="menu:repost_channel",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _remote_menu_keyboard(bot_username: str, chat_id: int = None) -> InlineKeyboardMarkup:
    """
    Shown in a GROUP or CHANNEL. Neither a chat wizard nor a Mini App
    (web_app button) can be attached to a message posted in a group/channel,
    so both buttons deep-link into a private chat with the bot
    (?start=zayavka / ?start=jadval), where the actual wizard/Mini App opens.
    This avoids Telegram's "Direct Link Mini App" (t.me/<bot>/<short_name>),
    which needs the short name pre-registered with @BotFather - skipping
    that avoids a "Bot application not found" error if it's never done.

    In a person's own chat the "Zayavka berish" link also carries that chat's
    id (?start=zayavka_<id>), so the wizard already knows the form is that
    person's and its Excel goes to that chat.
    """
    payload = "zayavka"
    if chat_id is not None and chat_id in PERSON_ROUTES.values():
        payload = f"zayavka_{abs(chat_id)}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="📝 Zayavka berish",
                url=f"https://t.me/{bot_username}?start={payload}",
            )],
            [InlineKeyboardButton(
                text="📋 Zayavkalar jadvali",
                url=f"https://t.me/{bot_username}?start=jadval",
            )],
        ]
    )


def _group_allowed(chat_id: int) -> bool:
    """
    The menu is shown in the ALLOWED_GROUP_IDS groups (any group if that list
    is empty) and in every per-person chat from PERSON_ROUTES. The person
    chats are deliberately NOT added to ALLOWED_GROUP_IDS: that list is also
    the default place everyone else's Excel files are posted.
    """
    return (
        not ALLOWED_GROUP_IDS
        or chat_id in ALLOWED_GROUP_IDS
        or chat_id in PERSON_ROUTES.values()
    )


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _jadval_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📋 Ochish",
            web_app=WebAppInfo(url=_table_html_url()),
        )],
    ])


def _keyboard_for(kind: str) -> InlineKeyboardMarkup:
    return _jadval_keyboard() if kind == "jadval" else _private_menu_keyboard()


MAX_TRACKED_PER_CHAT = 30


def _track_menu_message(sent: Message, kind: str) -> None:
    """Remember a message carrying a Mini App button so it can be re-pointed after a restart."""
    try:
        with SessionLocal() as db:
            db.add(BotMenuMessage(chat_id=sent.chat.id, message_id=sent.message_id, kind=kind))
            db.flush()
            old = (
                db.query(BotMenuMessage)
                .filter(BotMenuMessage.chat_id == sent.chat.id)
                .order_by(BotMenuMessage.id.desc())
                .offset(MAX_TRACKED_PER_CHAT)
                .all()
            )
            for row in old:
                db.delete(row)
            db.commit()
    except Exception:
        logger.exception("Could not remember menu message %s/%s", sent.chat.id, sent.message_id)


async def _heal_menu_messages(bot: Bot) -> None:
    """
    Re-points the Mini App button of every remembered menu message to the
    CURRENT address (the free Cloudflare tunnel gets a new one on every
    restart, which otherwise leaves old buttons opening a dead page). Run at
    every start. Messages that no longer exist are forgotten.
    """
    healed = gone = 0
    with SessionLocal() as db:
        rows = db.query(BotMenuMessage).order_by(BotMenuMessage.id).all()
        for row in rows:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=row.chat_id,
                    message_id=row.message_id,
                    reply_markup=_keyboard_for(row.kind),
                )
                healed += 1
            except TelegramBadRequest as e:
                text = str(e).lower()
                if "not modified" in text:
                    healed += 1  # already pointing at the current address
                else:
                    db.delete(row)  # deleted by the user / can't be edited any more
                    gone += 1
            except Exception:
                logger.exception("Could not re-point menu message %s/%s", row.chat_id, row.message_id)
            await asyncio.sleep(0.05)  # stay well inside Telegram's rate limits
        db.commit()
    logger.info("Menu buttons re-pointed: %d ok, %d forgotten", healed, gone)


async def _start_wizard_from_chat(message: Message, state: FSMContext, chat_digits: str):
    """
    The user tapped "Zayavka berish" in a person's own chat: open the wizard
    already fixed to that chat's person. Anyone can forge a start link, so the
    person is only accepted if the user is really a member of that chat (or an
    admin) - the API checks the same again when saving.
    """
    chat_id = -int(chat_digits) if chat_digits.isdigit() else None
    persons = [p for p, c in PERSON_ROUTES.items() if c == chat_id]
    if not persons:
        await wizard.start_wizard(message, state)
        return
    person = persons[0]  # PERSON_ROUTES is one chat per person, so this is unambiguous
    user_id = message.from_user.id
    name, username = message.from_user.full_name, message.from_user.username
    allowed = await persons_for_user(message.bot, user_id, name, username)
    if person in allowed:
        await wizard.start_wizard(message, state, persons=[person])
        return

    # Not granted yet - but are they REALLY a member of this exact chat right
    # now? (e.g. an already-approved user, for a different person, who just
    # joined this second channel too - access_for_user only auto-detects
    # channel membership once, the first time a Telegram id is ever seen, so
    # this wouldn't otherwise be noticed). If so, record it for the admin
    # instead of either silently blocking them or silently granting access.
    if chat_id is not None and await is_member(message.bot, chat_id, user_id):
        await flag_person_request(message.bot, user_id, name, username, person)
        await message.answer(
            f"📩 So'rovingiz qabul qilindi - <b>{person}</b> nomidan zayavka berish uchun "
            "administrator tasdiqlashi kerak.\n\nTasdiqlangach, shu tugmani qayta bosing.",
            parse_mode="HTML",
        )
        return

    await message.answer(
        "⛔ Siz bu kanal a'zosi sifatida aniqlanmadingiz.\n\n"
        "Zayavka berish uchun avval shu kanalga a'zo bo'lishingiz kerak "
        "(yoki administrator botni kanalga qayta qo'shishi kerak)."
    )


async def _send_jadval(message: Message):
    sent = await message.answer("📋 Zayavkalar jadvali", reply_markup=_jadval_keyboard())
    _track_menu_message(sent, "jadval")


def _contact_keyboard() -> ReplyKeyboardMarkup:
    """The only way to hand the bot a phone number Telegram vouches for."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamimni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def _ask_for_phone(message: Message) -> bool:
    """
    A person who isn't approved yet is asked to share their phone number: if an
    admin added that number, sharing it links this Telegram account to it.
    Returns True when the prompt was shown (the caller should stop there).
    """
    user = message.from_user
    access = await access_for_user(message.bot, user.id, user.full_name, user.username)
    if access.active:
        return False
    if access.status == "blocked":
        await message.answer("⛔ Sizning kirishingiz yopilgan. Administratorga murojaat qiling.")
        return True
    await message.answer(
        "👋 Salom! Ilovadan foydalanish uchun administrator sizni qo'shgan bo'lishi kerak.\n\n"
        "Pastdagi tugma orqali telefon raqamingizni yuboring - administrator qo'shgan raqam bilan "
        "mos kelsa, kirish darhol ochiladi.",
        reply_markup=_contact_keyboard(),
    )
    return True


@router.message(F.contact, F.chat.type == "private")
async def contact_shared(message: Message):
    """The user pressed "📱 Telefon raqamimni yuborish" (in the bot or from the Mini App)."""
    user = message.from_user
    contact = message.contact
    if contact.user_id != user.id:
        # A forwarded / picked contact card - anyone could send someone else's number.
        await message.answer(
            "Iltimos, faqat o'zingizning raqamingizni yuboring (\"📱 Telefon raqamimni yuborish\" tugmasi orqali).",
            reply_markup=_contact_keyboard(),
        )
        return
    if user.id in ADMIN_IDS:
        await message.answer("Siz bosh administratorsiz - tasdiqlash shart emas.", reply_markup=ReplyKeyboardRemove())
        return
    phone = normalize_phone(contact.phone_number)
    if not phone:
        await message.answer("Telefon raqami tushunarsiz.", reply_markup=ReplyKeyboardRemove())
        return

    result = link_phone(user.id, user.full_name, user.username, phone)
    who = f"{user.full_name}" + (f" (@{user.username})" if user.username else "")
    if result["result"] == "linked":
        await message.answer("✅ Raqamingiz tasdiqlandi - kirish ruxsati berildi!", reply_markup=ReplyKeyboardRemove())
        sent = await message.answer(
            "<b>🗂 Zayavka</b>\n\nKerakli bo'limni tanlang:",
            reply_markup=_private_menu_keyboard(),
            parse_mode="HTML",
        )
        _track_menu_message(sent, "menu")
        await notify_admins(message.bot, f"📱 <b>{who}</b> raqamini (+{phone}) tasdiqladi va ilovaga kirdi.")
    elif result["result"] == "conflict":
        await message.answer(
            "⛔ Bu raqam boshqa Telegram akkauntga bog'langan. Administratorga murojaat qiling.",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await message.answer(
            "📩 Raqamingiz qabul qilindi. Administrator sizni qo'shishi bilan kirish ochiladi.",
            reply_markup=ReplyKeyboardRemove(),
        )
        await notify_admins(
            message.bot,
            f"📱 <b>{who}</b> raqamini yubordi: <code>+{phone}</code> (ID <code>{user.id}</code>)\n"
            "Bu raqam kutilganlar ro'yxatida yo'q. Ilovada ⋮ menyu → Settings orqali tasdiqlashingiz mumkin.",
        )


@router.message(CommandStart(), F.chat.type == "private")
async def start_private(message: Message, command: CommandObject, state: FSMContext):
    if await _ask_for_phone(message):
        return
    if command.args == "zayavka":
        await wizard.start_wizard(message, state)
        return
    if command.args and command.args.startswith("zayavka_"):
        await _start_wizard_from_chat(message, state, command.args[len("zayavka_"):])
        return
    if command.args == "jadval":
        await _send_jadval(message)
        return
    sent = await message.answer(
        "<b>🗂 Zayavka</b>\n\nKerakli bo'limni tanlang:",
        reply_markup=_private_menu_keyboard(),
        parse_mode="HTML",
    )
    _track_menu_message(sent, "menu")


@router.message(Command("zayavka"), F.chat.type == "private")
async def zayavka_private(message: Message):
    if await _ask_for_phone(message):
        return
    sent = await message.answer(
        "<b>🗂 Zayavka</b>\n\nKerakli bo'limni tanlang:",
        reply_markup=_private_menu_keyboard(),
        parse_mode="HTML",
    )
    _track_menu_message(sent, "menu")


@router.callback_query(F.data == "wiz:start")
async def wiz_start_cb(callback, state: FSMContext):
    await callback.answer()
    await wizard.start_wizard(callback.message, state, user=callback.from_user)


@router.message(Command("myid"))
async def my_id(message: Message):
    """Your Telegram id - needed to be made an admin (ADMIN_IDS in .env)."""
    await message.answer(
        f"Sizning Telegram ID: <code>{message.from_user.id}</code>",
        parse_mode="HTML",
    )


async def _reply_chatid(message: Message):
    logger.info("chatid requested: chat_id=%s type=%s title=%s", message.chat.id, message.chat.type, message.chat.title)
    await message.answer(f"chat id: <code>{message.chat.id}</code>\ntype: {message.chat.type}", parse_mode="HTML")


@router.message(Command("chatid"))
async def chatid_message(message: Message):
    await _reply_chatid(message)


@router.channel_post(Command("chatid"))
async def chatid_channel(message: Message):
    await _reply_chatid(message)


@router.message(CommandStart(), F.chat.type.in_({"group", "supergroup"}))
@router.message(Command("zayavka"), F.chat.type.in_({"group", "supergroup"}))
async def start_group(message: Message, bot: Bot):
    if not _group_allowed(message.chat.id):
        return
    me = await bot.get_me()
    await message.answer(
        "<b>🗂 Zayavka</b>\n\nKerakli bo'limni tanlang:",
        reply_markup=_remote_menu_keyboard(me.username, message.chat.id),
        parse_mode="HTML",
    )


async def _post_channel_menu(bot: Bot) -> None:
    """
    Posts the Zayavka menu into the configured broadcast channel (CHANNEL_ID),
    since regular channel subscribers can't type /start there themselves -
    channels are broadcast-only. The bot must already be a channel ADMIN with
    "Post Messages" permission. Raises on failure (e.g. missing permission).
    """
    me = await bot.get_me()
    await bot.send_message(
        CHANNEL_ID,
        "<b>🗂 Zayavka</b>\n\nKerakli bo'limni tanlang:",
        reply_markup=_remote_menu_keyboard(me.username, CHANNEL_ID),
        parse_mode="HTML",
    )


@router.message(Command("post_channel_menu"), F.chat.type == "private")
async def post_channel_menu(message: Message, bot: Bot):
    if not _is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat administratorlar uchun.")
        return
    if not CHANNEL_ID:
        await message.answer("CHANNEL_ID .env faylida sozlanmagan.")
        return
    try:
        await _post_channel_menu(bot)
        await message.answer("✅ Kanalga joylandi.")
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")


@router.callback_query(F.data == "menu:repost_channel")
async def repost_channel_menu_cb(callback, bot: Bot):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Bu tugma faqat administratorlar uchun.", show_alert=True)
        return
    if not CHANNEL_ID:
        await callback.answer("CHANNEL_ID .env faylida sozlanmagan.", show_alert=True)
        return
    try:
        await _post_channel_menu(bot)
        await callback.answer("✅ Kanalga qayta joylandi.")
    except Exception as e:
        await callback.answer(f"❌ Xatolik: {e}", show_alert=True)


async def _set_commands(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="start", description="Zayavka bo'limini ochish"),
        BotCommand(command="zayavka", description="Zayavka bo'limini ochish"),
        BotCommand(command="bekor", description="Joriy amalni bekor qilish"),
    ])


async def _check_linked_chats(bot: Bot) -> None:
    """
    Logs, at every start, whether the bot can still post to / verify each
    linked chat. If someone removes the bot from a channel, that person's
    Excel files silently stop arriving and their members lose access - this
    makes it visible right away instead of being discovered later.
    """
    me = await bot.get_me()
    chats = {}
    for person, chat_id in PERSON_ROUTES.items():
        chats.setdefault(chat_id, []).append(person)
    for chat_id, persons in chats.items():
        who = ", ".join(persons)
        try:
            member = await bot.get_chat_member(chat_id, me.id)
            if member.status in ("administrator", "creator"):
                logger.info("Chat OK: %s (%s) - bot is %s", chat_id, who, member.status)
            else:
                logger.warning("Chat PROBLEM: %s (%s) - bot is only %r; it must be an administrator to post", chat_id, who, member.status)
        except Exception as e:
            logger.warning("Chat PROBLEM: %s (%s) - the bot cannot use it: %s", chat_id, who, e)


async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    dp.include_router(wizard.router)
    init_db()
    await _set_commands(bot)
    await _heal_menu_messages(bot)
    await _check_linked_chats(bot)
    logger.info("Bot polling started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
