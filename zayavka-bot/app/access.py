"""
Who may see and change which zayavkas.

A zayavka belongs to a person (its "От кого" name). Access is granted per
USER (an AppUser row, managed on the admin page): an approved user works with
the persons they're linked to, and the admin switches editing, deleting and
Excel export on or off per user. Admins (ADMIN_IDS) can do everything.

How people get in:
  - an admin adds them by PHONE NUMBER (as a user or as an admin); the person
    then shares their phone with the bot (or from the Mini App) and, since
    Telegram vouches that the number is theirs, is linked and approved;
  - a person is a member of a person's Telegram chat/channel (PERSON_ROUTES)
    -> approved automatically the first time they open the app, linked to those
       persons (the admin can then change anything or block them);
  - anyone else -> a pending request, which the admin approves or rejects;
  - the admin can also add a user by hand.
Membership is asked of Telegram itself (the bot is an admin of each chat).

Identity comes only from Telegram's signed initData (sent by the Mini App in
the X-Telegram-Init-Data header) - never from anything a page merely claims.
"""
import asyncio
import hashlib
import hmac
import html
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.config import ADMIN_IDS, BOT_TOKEN, FROM_WHOM, OBJECTS, PERSON_ROUTES
from app.db import SessionLocal
from app.models import AppUser, NameOption, PERMISSION_DEFAULTS, PERMISSION_KEYS
from app.tg_auth import parse_and_validate_init_data

logger = logging.getLogger("zayavka-access")

MEMBER_STATUSES = {"creator", "administrator", "member"}
MEMBERSHIP_CACHE_SECONDS = 60
DOWNLOAD_LINK_SECONDS = 300

_membership_cache: Dict[Tuple[int, int], Tuple[float, bool]] = {}
# When each owner (ADMIN_IDS, who has no users-table row) last opened the app.
OWNER_LAST_SEEN: Dict[int, datetime] = {}
LAST_SEEN_EVERY_SECONDS = 60
_warned_chats: Set[int] = set()


def all_persons() -> List[str]:
    """Every person that can be linked to a user (the form's list plus any with a channel)."""
    return list(FROM_WHOM) + sorted(p for p in PERSON_ROUTES if p not in FROM_WHOM)


def all_objects() -> List[str]:
    """Every building project (the fixed list plus the ones added in the bot)."""
    with SessionLocal() as db:
        extra = db.query(NameOption).filter(NameOption.category == "object").order_by(NameOption.name).all()
    merged = list(OBJECTS)
    merged += [o.name for o in extra if o.name not in merged]
    return merged


# What the admin page shows for each permission (order = display order).
PERMISSION_CATALOG = [
    {"key": "can_view", "group": "view", "label": "Zayavkalarni ko'rish",
     "desc": "O'ziga bog'langan shaxs(lar)ning zayavkalarini o'qish"},
    {"key": "can_view_others", "group": "view", "label": "Boshqa arizachilar zayavkalari",
     "desc": "O'chirilgan bo'lsa - foydalanuvchi FAQAT O'ZI yuborgan zayavkalarni ko'radi (telefon/ID bo'yicha "
             "ajratilgan). Yoqilsa - boshqa foydalanuvchilar yuborgan zayavkalarni ham ko'radi va o'zgartira oladi"},
    {"key": "can_view_all_objects", "group": "view", "label": "Boshqa qurilish obyektlari",
     "desc": "Barcha obyektlarni ko'rish va to'ldirish. O'chirilsa - faqat tanlangan obyektlar"},
    {"key": "can_create", "group": "act", "label": "Zayavka to'ldirish",
     "desc": "Yangi zayavka berish"},
    {"key": "can_edit", "group": "act", "label": "Tahrirlash",
     "desc": "Yuborilgan zayavkani o'zgartirish"},
    {"key": "can_delete", "group": "act", "label": "O'chirish",
     "desc": "Zayavkani o'chirish"},
    {"key": "can_export", "group": "act", "label": "Faylni yuklab olish",
     "desc": "Zayavka Excel faylini yuklab olish va Telegramga yuborish"},
    {"key": "can_report", "group": "act", "label": "Excel hisobot yuborish",
     "desc": "Filtrlangan zayavkalar ro'yxatini kanalga Excel qilib yuborish"},
    {"key": "can_manage_lists", "group": "act", "label": "Ro'yxatlarni boshqarish",
     "desc": "Yetkazib beruvchi, birlik, ish turi va ismlar ro'yxatidan o'chirish"},
    {"key": "can_manage_users", "group": "admin", "label": "Foydalanuvchi qo'shish",
     "desc": "Foydalanuvchilarni qo'shish va ruxsat berish (faqat o'zida bor ruxsatlar doirasida)"},
]
assert [p["key"] for p in PERMISSION_CATALOG] == list(PERMISSION_KEYS)


@dataclass
class Access:
    user_id: int
    name: str
    is_admin: bool
    # The "От кого" persons this user may work with (everyone, for admins).
    persons: Set[str] = field(default_factory=set)
    status: str = "approved"          # admin | approved | pending | blocked
    # Building projects the user is limited to; None = every project.
    objects: Optional[Set[str]] = None
    is_owner: bool = False            # listed in ADMIN_IDS (can't be demoted from the page)
    can_view: bool = True
    can_view_others: bool = False
    can_view_all_objects: bool = True
    can_create: bool = True
    can_edit: bool = True
    can_delete: bool = True
    can_export: bool = True
    can_report: bool = True
    can_manage_lists: bool = True
    can_manage_users: bool = False

    @property
    def active(self) -> bool:
        return self.is_admin or self.status == "approved"

    @property
    def is_manager(self) -> bool:
        """May open the users page: admins, and users who were given "add users"."""
        return self.is_admin or (self.active and self.can_manage_users)

    def perms(self) -> Dict[str, bool]:
        return {key: bool(getattr(self, key)) for key in PERMISSION_KEYS}

    def object_ok(self, object_name: Optional[str]) -> bool:
        return (
            self.is_admin or self.can_view_all_objects
            or self.objects is None or (object_name or "") in self.objects
        )

    def allowed_objects(self, universe: List[str]) -> List[str]:
        return [o for o in universe if self.object_ok(o)]

    def can_read(
        self, from_whom: Optional[str], object_name: Optional[str],
        created_by_tg_id: Optional[int] = None,
    ) -> bool:
        """
        May this user look at this form? The privacy unit is the INDIVIDUAL
        submitter (their Telegram id/phone), not the person/channel: by
        default a user sees only what they personally submitted, even if a
        colleague files under the same person. can_view_others lifts that -
        then they see everyone's forms (still subject to can_view_all_objects).
        created_by_tg_id=None (very old records, or a not-yet-existing one)
        falls back to the old person-based rule so nothing goes invisible.
        """
        if self.is_admin:
            return True
        if not (self.active and self.can_view and self.object_ok(object_name)):
            return False
        if self.can_view_others:
            return True
        if created_by_tg_id is None:
            return (from_whom or "") in self.persons
        return created_by_tg_id == self.user_id

    def can_write(
        self, from_whom: Optional[str], object_name: Optional[str],
        created_by_tg_id: Optional[int] = None,
    ) -> bool:
        """
        May this user file / change / delete this form? Always needs the
        person+project link (filing "as" someone you're not linked to is
        never allowed). For an EXISTING form (created_by_tg_id given), it
        must also be one they may read - their own, or any if can_view_others.
        """
        if self.is_admin:
            return True
        if not (self.active and (from_whom or "") in self.persons and self.object_ok(object_name)):
            return False
        if created_by_tg_id is None:
            return True
        return self.can_view_others or created_by_tg_id == self.user_id

    def ordered_persons(self) -> List[str]:
        """This user's persons, in the form's usual order first."""
        known = [p for p in FROM_WHOM if p in self.persons]
        return known + sorted(p for p in self.persons if p not in FROM_WHOM)


def admin_access_for(user_id: int, name: str, owner: bool) -> Access:
    return Access(
        user_id=user_id, name=name, is_admin=True, persons=set(all_persons()), status="admin",
        objects=None, is_owner=owner, can_view_others=True, can_manage_users=True,
    )


def display_name(user: dict) -> str:
    return (
        " ".join(filter(None, [user.get("first_name"), user.get("last_name")]))
        or user.get("username")
        or str(user.get("id", ""))
    )


# --- Telegram membership ------------------------------------------------------

async def is_member(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Is this Telegram user in that chat? Asked of Telegram, cached for a minute."""
    key = (chat_id, user_id)
    now = time.monotonic()
    hit = _membership_cache.get(key)
    if hit and now - hit[0] < MEMBERSHIP_CACHE_SECONDS:
        return hit[1]
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        ok = member.status in MEMBER_STATUSES or (
            member.status == "restricted" and bool(getattr(member, "is_member", False))
        )
    except TelegramBadRequest:
        ok = False  # never joined / unknown user - a definite "no", safe to cache
    except TelegramForbiddenError:
        # The BOT itself was removed from that chat, so nobody can be verified
        # as a member of it - access through it is off until the bot is re-added.
        if chat_id not in _warned_chats:
            _warned_chats.add(chat_id)
            logger.warning("The bot has no access to chat %s (removed?) - its members can't be verified", chat_id)
        ok = False
    except Exception:
        logger.exception("Membership check failed for chat %s user %s", chat_id, user_id)
        return False  # deny, but don't cache a transient failure
    _membership_cache[key] = (now, ok)
    return ok


async def persons_by_membership(bot: Bot, user_id: int) -> Set[str]:
    """The persons whose Telegram chat this user is a member of."""
    routes = list(PERSON_ROUTES.items())
    if not routes:
        return set()
    results = await asyncio.gather(*(is_member(bot, chat, user_id) for _, chat in routes))
    return {name for (name, _), ok in zip(routes, results) if ok}


# --- the users table ------------------------------------------------------------

def normalize_phone(text) -> Optional[str]:
    """
    Digits only, with the country code: "+998 90 123-45-67", "998901234567",
    "90 123 45 67" and "0901234567" all become 998901234567 (numbers without a
    country code are taken as Uzbek). None if it can't be a phone number.
    """
    digits = re.sub(r"\D", "", str(text or ""))
    if len(digits) == 9:
        digits = "998" + digits
    elif len(digits) == 10 and digits.startswith("0"):
        digits = "998" + digits[1:]
    return digits if 9 <= len(digits) <= 15 else None


def _load_user(user_id: int) -> Optional[dict]:
    with SessionLocal() as db:
        row = db.query(AppUser).filter(AppUser.telegram_id == user_id).first()
        return row.to_dict() if row else None


def _touch_identity(user_id: int, name: str, username: Optional[str]) -> None:
    """Keep the stored name/@username current (people rename themselves) and note when they were last here."""
    with SessionLocal() as db:
        row = db.query(AppUser).filter(AppUser.telegram_id == user_id).first()
        if not row:
            return
        changed = False
        if name and row.name != name:
            row.name, changed = name, True
        if username and row.username != username:
            row.username, changed = username, True
        now = datetime.utcnow()
        if row.last_seen_at is None or (now - row.last_seen_at).total_seconds() > LAST_SEEN_EVERY_SECONDS:
            row.last_seen_at, changed = now, True
        if changed:
            db.commit()


def _create_user(user_id: int, name: str, username: Optional[str], status: str, source: str,
                 persons=(), approved_by: Optional[str] = None, phone: Optional[str] = None) -> bool:
    """Creates the row; returns False if someone else created it first."""
    try:
        with SessionLocal() as db:
            row = AppUser(
                telegram_id=user_id, name=name or "", username=username,
                status=status, source=source, phone=phone,
            )
            row.persons = persons
            if status == "approved":
                row.approved_at = datetime.utcnow()
                row.approved_by = approved_by
            db.add(row)
            db.commit()
        return True
    except IntegrityError:
        return False


def _approve_from_membership(user_id: int, name: str, username: Optional[str], persons: Set[str]) -> None:
    """A channel member: approved automatically (never overrides a block)."""
    with SessionLocal() as db:
        row = db.query(AppUser).filter(AppUser.telegram_id == user_id).first()
        if row is not None:
            if row.status != "blocked":
                row.status = "approved"
                row.persons = persons
                row.approved_at = datetime.utcnow()
                row.approved_by = "Telegram kanal a'zoligi"
                if name and not row.name:
                    row.name = name
                db.commit()
            return
    _create_user(user_id, name, username, "approved", "channel", persons, "Telegram kanal a'zoligi")


def link_phone(user_id: int, name: str, username: Optional[str], phone: str) -> dict:
    """
    A Telegram user has shared THEIR OWN phone number (the caller has checked the
    contact belongs to them). If an admin had added that number, the user is
    linked to it and approved with what the admin set up.

    result: "linked"   - an admin's invitation for this number was found and applied
            "saved"    - nobody invited this number; it is stored on the user's own
                         request so the admin can see it
            "conflict" - the number is already linked to a different Telegram account
    """
    with SessionLocal() as db:
        own = db.query(AppUser).filter(AppUser.telegram_id == user_id).first()
        by_phone = db.query(AppUser).filter(AppUser.phone == phone).first()

        if by_phone is not None and by_phone.telegram_id not in (None, user_id):
            return {"result": "conflict", "user": None}

        if by_phone is not None and by_phone.telegram_id is None:
            if own is not None and own.id != by_phone.id:
                db.delete(own)      # the person's own pending request is replaced by the invitation
                db.flush()
            by_phone.telegram_id = user_id
            if name and not by_phone.name:
                by_phone.name = name
            if username:
                by_phone.username = username
            if by_phone.status in ("invited", "pending"):
                by_phone.status = "approved"
                by_phone.approved_at = datetime.utcnow()
                by_phone.approved_by = by_phone.approved_by or "Telefon raqami orqali"
            db.commit()
            return {"result": "linked", "user": by_phone.to_dict()}

        if own is None:
            own = AppUser(telegram_id=user_id, name=name or "", username=username,
                          status="pending", source="request", phone=phone)
            db.add(own)
        else:
            own.phone = phone
        db.commit()
        return {"result": "saved", "user": own.to_dict()}


async def notify_admins(bot: Optional[Bot], text: str) -> None:
    if bot is None:
        return
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception:
            logger.warning("Could not notify admin %s", admin_id)


async def flag_person_request(
    bot: Optional[Bot], user_id: int, name: str, username: Optional[str], person: str,
) -> None:
    """
    A Telegram user (verified as really being a member of that person's
    chat - the caller checks that) is asking to work as `person` but isn't
    granted it yet - e.g. an already-approved user (for a different person)
    who just joined a second person's channel. Recorded for the admin to
    review and grant, exactly like a brand-new access request: it does NOT
    silently add the person to their access, and does NOT touch anything
    else about an existing user (their current status/persons/permissions
    for the person(s) they already have stay exactly as they were).
    """
    with SessionLocal() as db:
        row = db.query(AppUser).filter(AppUser.telegram_id == user_id).first()
        if row is None:
            row = AppUser(telegram_id=user_id, name=name or "", username=username, status="pending", source="request")
            db.add(row)
        else:
            if name and not row.name:
                row.name = name
            if username:
                row.username = username
        row.requested_person = person
        db.commit()

    who = html.escape(name or str(user_id)) + (f" (@{html.escape(username)})" if username else "")
    await notify_admins(
        bot,
        f"📩 <b>Yangi shaxs uchun so'rov</b>\n{who}\nTelegram ID: <code>{user_id}</code>\n"
        f"So'ralgan shaxs/kanal: <b>{html.escape(person)}</b>\n\n"
        "Tasdiqlash: ilovada ⋮ menyu → Settings.",
    )


def _access_from_row(user_id: int, name: str, row: dict) -> Access:
    """The Access of a non-owner user from their users-table row."""
    if row["role"] == "admin" and row["status"] == "approved":
        return admin_access_for(user_id, name or row["name"], owner=False)
    approved = row["status"] == "approved"
    perms = {key: bool(row[key]) for key in PERMISSION_KEYS}
    return Access(
        user_id=user_id,
        name=name or row["name"],
        is_admin=False,
        persons=set(row["persons"]) if approved else set(),
        status=row["status"],
        objects=set(row["objects"]),
        **perms,
    )


async def access_for_user(bot: Optional[Bot], user_id: int, name: str = "", username: Optional[str] = None) -> Access:
    """
    Who is this Telegram user and what may they do. Creates their record the
    first time: approved if they're already in a person's chat, otherwise a
    pending request (and the admin is told).
    """
    if user_id in ADMIN_IDS:
        OWNER_LAST_SEEN[user_id] = datetime.utcnow()
        return admin_access_for(user_id, name, owner=True)

    row = _load_user(user_id)
    if row is not None and (name or username):
        _touch_identity(user_id, name, username)

    if row is None or row["status"] == "pending":
        member_of = await persons_by_membership(bot, user_id)
        if member_of:
            _approve_from_membership(user_id, name, username, member_of)
        elif row is None and _create_user(user_id, name, username, "pending", "request"):
            who = html.escape(name or str(user_id)) + (f" (@{html.escape(username)})" if username else "")
            asyncio.ensure_future(notify_admins(
                bot,
                f"🆕 <b>Kirish so'rovi</b>\n{who}\nTelegram ID: <code>{user_id}</code>\n\n"
                "Tasdiqlash: ilovada ⋮ menyu → Settings.",
            ))
        row = _load_user(user_id)

    return _access_from_row(user_id, name, row)


async def persons_for_user(bot: Bot, user_id: int, name: str = "", username: Optional[str] = None) -> Set[str]:
    """The persons whose zayavkas this Telegram user may work with."""
    return (await access_for_user(bot, user_id, name, username)).persons


async def authenticate(bot: Bot, init_data: str) -> Access:
    """Telegram-signed initData -> who is asking and what they may do (401 otherwise)."""
    user = parse_and_validate_init_data(init_data) if init_data else None
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail="Telegram ichida oching (foydalanuvchi aniqlanmadi)")
    return await access_for_user(bot, int(user["id"]), display_name(user), user.get("username"))


# --- short-lived download links --------------------------------------------
# A browser/Telegram download can't send the identity header, so the page first
# asks the API (with its identity) for a link that carries a signed, expiring
# token bound to the user and to that exact file path.

_SECRET = hashlib.sha256(b"zayavka-download|" + BOT_TOKEN.encode()).digest()


def _sign(user_id: int, path: str, expires: int) -> str:
    return hmac.new(_SECRET, f"{user_id}:{path}:{expires}".encode(), hashlib.sha256).hexdigest()


def make_download_token(user_id: int, path: str, ttl: int = DOWNLOAD_LINK_SECONDS) -> str:
    expires = int(time.time()) + ttl
    return f"{user_id}.{expires}.{_sign(user_id, path, expires)}"


def verify_download_token(token: str, path: str) -> Optional[int]:
    """The user id the token was issued to, or None if it's forged, expired or for another file."""
    try:
        user_id_text, expires_text, signature = token.split(".")
        user_id, expires = int(user_id_text), int(expires_text)
    except (ValueError, AttributeError):
        return None
    if expires < time.time():
        return None
    if not hmac.compare_digest(signature, _sign(user_id, path, expires)):
        return None
    return user_id
