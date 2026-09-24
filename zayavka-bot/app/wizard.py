"""
The step-by-step "Zayavka berish" chat wizard for the header fields (object,
date, from whom, payment type). Item rows are filled in one go via a
Telegram Mini App form (webapp/items.html) opened from a Web App button.
The wizard's job ends once that button is shown - the Mini App itself saves
directly to the API (see app/api.py + app/notify.py) rather than sending
data back through this bot process, since Telegram's WebApp.sendData() only
works for Mini Apps launched via a Reply Keyboard button, not the inline
"Web App" button used here.

Obyekt and Kimdan (От кого) both offer an "➕ Yangi ... qo'shish" button so a
user isn't stuck if the person/object they need isn't in the list yet -
whatever they type is saved (NameOption table) and shows up as a regular
button for everyone from then on, same growable-list idea as the Мини Апп
form's Инспектор/Кассир/Техданзор combos.
"""
import logging
from typing import Optional
from datetime import datetime, date
from urllib.parse import urlencode

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)

from app.access import access_for_user, Access
from app.config import OBJECTS, FROM_WHOM, PAYMENT_TYPES, WEBAPP_URL, ADMIN_IDS
from app.db import SessionLocal
from app.models import NameOption

logger = logging.getLogger("zayavka-wizard")

router = Router()


class Wizard(StatesGroup):
    object = State()
    object_new = State()
    date = State()
    from_whom = State()
    from_new = State()
    payment = State()
    items_webapp = State()


def _chunk_buttons(labels, prefix, per_row=1):
    rows = []
    row = []
    for idx, label in enumerate(labels):
        row.append(InlineKeyboardButton(text=label, callback_data=f"{prefix}:{idx}"))
        if len(row) == per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def _cancel_row():
    return [InlineKeyboardButton(text="🚫 Bekor qilish", callback_data="wiz:cancel_ask")]


def _kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows + [_cancel_row()])


def _get_option_list(db, category: str, base_list: list) -> list:
    """Static config list + any user-added NameOption names for this category."""
    extra = (
        db.query(NameOption)
        .filter(NameOption.category == category)
        .order_by(NameOption.name)
        .all()
    )
    merged = list(base_list)
    for opt in extra:
        if opt.name not in merged:
            merged.append(opt.name)
    return merged


def _save_new_option(db, category: str, name: str) -> None:
    exists = (
        db.query(NameOption)
        .filter(NameOption.category == category, NameOption.name == name)
        .first()
    )
    if not exists:
        db.add(NameOption(category=category, name=name))
        db.commit()


async def _access_of(bot, user) -> Access:
    return await access_for_user(bot, user.id, user.full_name, user.username)


async def start_wizard(message: Message, state: FSMContext, persons: Optional[list] = None, user=None):
    """
    `persons`: when the wizard was opened from a person's own chat (the button
    in that chat's menu), the "От кого" is already decided by that chat - the
    step is skipped, so the form is filed as that person and its Excel goes to
    that chat. Without it (the plain menu) the user picks the person as before.
    """
    await state.clear()
    # `user`: who is asking (a callback's message was sent by the bot, so its from_user is the bot).
    access = await _access_of(message.bot, user or message.from_user)
    if not access.active:
        await message.answer(
            "⛔ Sizga ruxsat berilmagan.\n\n"
            "Zayavka berish uchun administrator sizni tasdiqlashi kerak. Administratorga murojaat qiling."
        )
        return
    if not access.can_create:
        await message.answer("⛔ Sizga zayavka to'ldirish huquqi berilmagan. Administratorga murojaat qiling.")
        return

    await state.set_state(Wizard.object)
    if persons:
        await state.update_data(preset_persons=persons)

    db = SessionLocal()
    try:
        objects = _get_option_list(db, "object", OBJECTS)
    finally:
        db.close()
    # Someone limited to certain building projects is only offered those.
    objects = access.allowed_objects(objects)
    if not objects:
        await state.clear()
        await message.answer("⛔ Sizga hech qanday qurilish obyekti biriktirilmagan. Administratorga murojaat qiling.")
        return
    await state.update_data(object_options=objects)

    rows = _chunk_buttons(objects, "obj", per_row=2)
    if access.is_admin or access.can_view_all_objects:
        rows += [[InlineKeyboardButton(text="➕ Yangi obyekt qo'shish", callback_data="obj_add_new")]]
    kb = _kb(rows)
    await message.answer(
        "<b>📝 Zayavka berish</b>\n\nQaysi obyekt bo'yicha?",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.message(Command("bekor"))
@router.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext):
    if await state.get_state() is None:
        return
    await state.clear()
    await message.answer("Bekor qilindi.")


@router.callback_query(F.data == "wiz:cancel_ask")
async def cancel_ask_cb(callback: CallbackQuery, state: FSMContext):
    if await state.get_state() is None:
        await callback.answer()
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Ha, bekor qilish", callback_data="wiz:cancel_yes")],
        [InlineKeyboardButton(text="◀️ Yo'q, davom etish", callback_data="wiz:cancel_no")],
    ])
    await callback.message.answer(
        "⚠️ <b>Rostdan ham bekor qilmoqchimisiz?</b>\n\n"
        "Hozirgacha kiritilgan barcha ma'lumotlar (obyekt, sana, kimdan va h.k.) "
        "yo'qoladi va siz \"Zayavka berish\"ni boshidan boshlashingiz kerak bo'ladi.",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "wiz:cancel_yes")
async def cancel_yes_cb(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("✅ Bekor qilindi.")
    await callback.answer()


@router.callback_query(F.data == "wiz:cancel_no")
async def cancel_no_cb(callback: CallbackQuery, state: FSMContext):
    if await state.get_state() is None:
        await callback.message.edit_text("Amal allaqachon tugagan.")
    else:
        await callback.message.edit_text("👍 Davom etamiz, yuqoridagi bosqichni to'ldiring.")
    await callback.answer()


# --- step 1: object ---
async def _proceed_after_object(target, state: FSMContext, object_name: str, saved_new: bool = False):
    await state.update_data(object_name=object_name)
    await state.set_state(Wizard.date)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Bugun", callback_data="date:today")],
        _cancel_row(),
    ])
    note = " ✅ (yangi obyekt sifatida saqlandi)" if saved_new else ""
    text = (
        f"Obyekt: <b>{object_name}</b>{note}\n\n"
        f"Sana? Bugungi kun uchun tugmani bosing, yoki sanani <code>KUN.OY.YIL</code> "
        f"formatida yozing (masalan: 20.09.2026)."
    )
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(StateFilter(Wizard.object), F.data.startswith("obj:"))
async def pick_object(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[1])
    data = await state.get_data()
    options = data.get("object_options", OBJECTS)
    object_name = options[idx]
    await _proceed_after_object(callback, state, object_name)


@router.callback_query(StateFilter(Wizard.object), F.data == "obj_add_new")
async def object_add_new_cb(callback: CallbackQuery, state: FSMContext):
    access = await _access_of(callback.bot, callback.from_user)
    if not (access.is_admin or (access.active and access.can_view_all_objects)):
        await callback.answer("Yangi obyekt qo'shishga ruxsat yo'q", show_alert=True)
        return
    await state.set_state(Wizard.object_new)
    await callback.message.edit_text(
        "🏢 Yangi obyekt nomini yozing:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_cancel_row()]),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(StateFilter(Wizard.object_new))
async def object_new_input(message: Message, state: FSMContext):
    access = await _access_of(message.bot, message.from_user)
    if not (access.is_admin or (access.active and access.can_view_all_objects)):
        await state.clear()
        await message.answer("⛔ Yangi obyekt qo'shishga ruxsat yo'q.")
        return
    name = (message.text or "").strip()
    if not name:
        await message.answer("Obyekt nomini yozing.")
        return
    db = SessionLocal()
    try:
        _save_new_option(db, "object", name)
    finally:
        db.close()
    await _proceed_after_object(message, state, name, saved_new=True)


@router.message(StateFilter(Wizard.object))
async def object_needs_button(message: Message):
    await message.answer("Iltimos, yuqoridagi tugmalardan birini tanlang.")


# --- step 2: date ---
async def _proceed_after_date(target, state: FSMContext, chosen_date: date):
    await state.update_data(zayavka_date=chosen_date.isoformat())

    preset = (await state.get_data()).get("preset_persons")
    if preset and len(preset) == 1:
        # Opened from this person's own chat: no need to ask who it's from.
        await _proceed_after_from(target, state, preset[0])
        return

    await state.set_state(Wizard.from_whom)

    db = SessionLocal()
    try:
        all_options = _get_option_list(db, "from_whom", FROM_WHOM)
    finally:
        db.close()

    # A user may only file as a person whose channel they belong to (admins:
    # anyone). The API enforces the same rule when saving; this just avoids
    # offering choices that would be refused.
    access = await _access_of(target.bot, target.from_user)
    is_admin = access.is_admin
    if preset:
        options = list(preset)
        is_admin = False  # no "add a new person" when the chat already decides who it's from
    elif is_admin:
        options = all_options
    else:
        allowed = access.persons
        options = [p for p in all_options if p in allowed] + [
            p for p in sorted(allowed) if p not in all_options
        ]
    await state.update_data(from_whom_options=options)

    text = f"Sana: <b>{chosen_date.strftime('%d.%m.%Y')}</b>\n\nKimdan (От кого)?"
    if not options:
        await state.clear()
        text = (
            "⛔ Sizga ruxsat berilmagan.\n\n"
            "Zayavka berish uchun administrator sizni tasdiqlashi kerak "
            "(yoki shaxsning kanaliga a'zo bo'ling). Administratorga murojaat qiling."
        )
        kb = None
    else:
        rows = _chunk_buttons(options, "from", per_row=2)
        if is_admin:
            rows += [[InlineKeyboardButton(text="➕ Yangi kishi qo'shish", callback_data="from_add_new")]]
        kb = _kb(rows)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(StateFilter(Wizard.date), F.data == "date:today")
async def date_today(callback: CallbackQuery, state: FSMContext):
    await _proceed_after_date(callback, state, date.today())


@router.message(StateFilter(Wizard.date))
async def date_custom(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    parsed = None
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%d-%m-%Y"):
        try:
            parsed = datetime.strptime(text, fmt).date()
            break
        except ValueError:
            continue
    if not parsed:
        await message.answer(
            "Sana noto'g'ri formatda. Iltimos <code>KUN.OY.YIL</code> ko'rinishida yozing "
            "(masalan: 20.09.2026) yoki \"📅 Bugun\" tugmasini bosing.",
            parse_mode="HTML",
        )
        return
    await _proceed_after_date(message, state, parsed)


# --- step 3: from_whom ---
async def _proceed_after_from(target, state: FSMContext, from_whom: str, saved_new: bool = False):
    await state.update_data(from_whom=from_whom)
    await state.set_state(Wizard.payment)
    kb = _kb(_chunk_buttons(PAYMENT_TYPES, "pay"))
    note = " ✅ (yangi kishi sifatida saqlandi)" if saved_new else ""
    text = f"От кого: <b>{from_whom}</b>{note}\n\nВид оплаты?"
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(StateFilter(Wizard.from_whom), F.data.startswith("from:"))
async def pick_from(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[1])
    data = await state.get_data()
    options = data.get("from_whom_options", FROM_WHOM)
    from_whom = options[idx]
    await _proceed_after_from(callback, state, from_whom)


@router.callback_query(StateFilter(Wizard.from_whom), F.data == "from_add_new")
async def from_add_new_cb(callback: CallbackQuery, state: FSMContext):
    if not (await _access_of(callback.bot, callback.from_user)).is_admin:
        await callback.answer("Yangi kishini faqat administrator qo'sha oladi", show_alert=True)
        return
    await state.set_state(Wizard.from_new)
    await callback.message.edit_text(
        "👤 Yangi kishi ismini yozing:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_cancel_row()]),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(StateFilter(Wizard.from_new))
async def from_new_input(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name:
        await message.answer("Ism kiriting.")
        return
    db = SessionLocal()
    try:
        _save_new_option(db, "from_whom", name)
    finally:
        db.close()
    await _proceed_after_from(message, state, name, saved_new=True)


@router.message(StateFilter(Wizard.from_whom))
async def from_needs_button(message: Message):
    await message.answer("Iltimos, yuqoridagi tugmalardan birini tanlang.")


# --- step 4: payment -> open the items Mini App form ---
@router.callback_query(StateFilter(Wizard.payment), F.data.startswith("pay:"))
async def pick_payment(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[1])
    payment_type = PAYMENT_TYPES[idx]
    await state.update_data(payment_type=payment_type)
    await state.set_state(Wizard.items_webapp)

    data = await state.get_data()
    params = urlencode({
        "object": data["object_name"],
        "date": data["zayavka_date"],
        "from": data["from_whom"],
        "payment": payment_type,
    })
    items_url = f"{WEBAPP_URL}/items.html?{params}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧾 Tovar / Xizmatlar ro'yxati", web_app=WebAppInfo(url=items_url))],
        _cancel_row(),
    ])
    # Obyekt/Sana/Kimdan were already confirmed in the previous steps, and
    # Nomer/Summa zayavki only exist once items are filled in - showing all
    # five again here just duplicates the final "✅ Zayavka yuborildi!"
    # confirmation that follows after saving, so keep this to the prompt.
    await callback.message.edit_text(
        "Endi pastdagi tugma orqali tovarlar/ishlar ro'yxatini bitta formada to'ldiring.",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(StateFilter(Wizard.payment))
async def payment_needs_button(message: Message):
    await message.answer("Iltimos, yuqoridagi tugmalardan birini tanlang.")


# --- step 5: the Mini App form itself saves (POSTs to /api/zayavka) and
# sends the finished Excel over Telegram - see app/notify.py for why this
# isn't handled here via web_app_data/sendData(). The wizard's job ends once
# the button below is shown; this state just catches stray text messages
# while the Mini App is open.
@router.message(StateFilter(Wizard.items_webapp))
async def items_webapp_needs_button(message: Message):
    await message.answer("Iltimos, yuqoridagi \"🧾 Tovar / Xizmatlar ro'yxati\" tugmasini bosing.")
