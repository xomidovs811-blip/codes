import html
import logging
import os
import shutil
import tempfile
from datetime import date as date_type, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from aiogram import Bot
from fastapi import BackgroundTasks, FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import and_, false, func, or_

from app.access import (
    Access, authenticate, access_for_user, make_download_token, verify_download_token,
    all_persons, all_objects, notify_admins, normalize_phone, PERMISSION_CATALOG, OWNER_LAST_SEEN,
)
from app.db import get_db, init_db, SessionLocal
from app.models import (
    Zayavka, ZayavkaItem, ZayavkaVersion, NameOption, AppUser, PERMISSION_DEFAULTS, PERMISSION_KEYS,
)
from app.schemas import (
    ZayavkaIn, NameOptionIn, ExportIn, AdminUserIn, AdminUserPatch, AccessRequestIn,
)
from app.services import (
    create_zayavka_record, update_zayavka_record, backfill_versions, seed_default_work_types,
)
from app.notify import (
    send_zayavka_document, send_zayavka_to_chat, send_dict_to_chat, send_report_file,
)
from app.report_gen import save_report, build_report_caption
from app.excel_gen import save_workbook
from app.config import (
    OBJECTS, FROM_WHOM, PAYMENT_TYPES, FIXED_KOMU, BOT_TOKEN, PERSON_ROUTES, ADMIN_IDS,
)

BASE_DIR = Path(__file__).resolve().parent.parent
WEBAPP_DIR = BASE_DIR / "webapp"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("zayavka-api")

# Uzbekistan has no DST, so a fixed +5h offset is exact (and avoids needing tzdata on Windows).
TASHKENT_OFFSET = timedelta(hours=5)

# The interactive API docs would publish the whole API surface to anyone with the link.
app = FastAPI(title="Zayavka Mini App API", docs_url=None, redoc_url=None, openapi_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared Bot instance so /api/zayavka can send the finished Excel straight
# from this process - the Mini App posts here directly instead of going
# through the bot's polling process (see app/notify.py for why).
bot = Bot(token=BOT_TOKEN)


@app.on_event("startup")
def on_startup():
    init_db()
    db = SessionLocal()
    try:
        backfill_versions(db)
        seed_default_work_types(db)
    finally:
        db.close()


@app.on_event("shutdown")
async def on_shutdown():
    await bot.session.close()


# --- who is asking -----------------------------------------------------------

async def current_access(request: Request) -> Access:
    """Every data route: Telegram-signed identity (X-Telegram-Init-Data) -> what this user may access."""
    return await authenticate(bot, request.headers.get("X-Telegram-Init-Data", ""))


async def download_access(request: Request, t: Optional[str] = None) -> Access:
    """
    Excel downloads: a plain browser/Telegram download can't send the identity
    header, so it may instead carry a short-lived signed link token (issued by
    the *_excel_link routes to an authenticated user, for that one file).
    """
    header = request.headers.get("X-Telegram-Init-Data", "")
    if header:
        return await authenticate(bot, header)
    user_id = verify_download_token(t, request.url.path) if t else None
    if user_id is None:
        raise HTTPException(status_code=401, detail="Havola eskirgan yoki noto'g'ri - sahifadan qayta yuklab oling")
    return await access_for_user(bot, user_id)


def _visible_zayavka(db: Session, zayavka_id: int, access: Access) -> Zayavka:
    """
    The zayavka if it exists, isn't deleted and belongs to a person this user
    may access - otherwise 404 (not 403, so the existence of other people's
    forms isn't revealed).
    """
    z = db.query(Zayavka).filter(Zayavka.id == zayavka_id, Zayavka.deleted_at.is_(None)).first()
    if z is None:
        raise HTTPException(status_code=404, detail="Not found")
    if not access.can_read(z.from_whom, z.object_name, z.created_by_tg_id):
        logger.warning(
            "Access denied: user %s (%s) tried to reach zayavka %s of %r",
            access.user_id, access.name, z.id, z.from_whom,
        )
        raise HTTPException(status_code=404, detail="Not found")
    return z


async def admin_access(access: Access = Depends(current_access)) -> Access:
    if not access.is_admin:
        raise HTTPException(status_code=403, detail="Faqat administrator uchun")
    return access


async def manager_access(access: Access = Depends(current_access)) -> Access:
    """The users page: admins, and users who were given the "add users" permission."""
    if not access.is_manager:
        raise HTTPException(status_code=403, detail="Foydalanuvchilarni boshqarish huquqi berilmagan")
    return access


def _require_active(access: Access) -> None:
    """Only approved users (and admins) may use the app's data; pending/blocked ones may not."""
    if not access.active:
        if access.status == "blocked":
            raise HTTPException(status_code=403, detail="Sizning kirishingiz bloklangan")
        raise HTTPException(status_code=403, detail="Kirish uchun administrator tasdiqlashi kerak")


def _require(access: Access, allowed: bool, what: str) -> None:
    if not allowed:
        raise HTTPException(status_code=403, detail=f"Sizga {what} huquqi berilmagan")


def _require_work_type(items: list) -> None:
    """
    Сметная группа is mandatory on every item row - the Mini App already
    blocks saving with it blank (and highlights the row), this is just the
    same rule enforced here too so a direct API call can't skip it.
    """
    missing = [str(i + 1) for i, item in enumerate(items) if not (item.get("work_type") or "").strip()]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"\"Сметная группа\" hamma qatorda to'ldirilishi shart (qator: {', '.join(missing)})",
        )


def _require_write_scope(
    access: Access, from_whom: str, object_name: str, created_by_tg_id: Optional[int] = None,
) -> None:
    """Filing / changing / deleting is only for the user's own persons and projects."""
    if access.can_write(from_whom, object_name, created_by_tg_id):
        return
    if (from_whom or "") not in access.persons:
        raise HTTPException(status_code=403, detail="Siz bu shaxs nomidan ish qila olmaysiz (unga bog'lanmagansiz)")
    if not access.object_ok(object_name):
        raise HTTPException(status_code=403, detail="Bu qurilish obyekti sizga ochiq emas")
    raise HTTPException(
        status_code=403,
        detail="Bu boshqa foydalanuvchi yuborgan zayavka - uni o'zgartirish uchun "
               "\"Boshqa arizachilar zayavkalari\" huquqi kerak",
    )


NAME_OPTION_CATEGORIES = {"inspector", "cashier", "tech_supervisor", "supplier", "unit", "work_type"}


def _names_by_category(db: Session, category: str) -> list:
    rows = (
        db.query(NameOption)
        .filter(NameOption.category == category)
        .order_by(NameOption.name)
        .all()
    )
    return [r.name for r in rows]


@app.get("/api/meta")
def get_meta(db: Session = Depends(get_db), access: Access = Depends(current_access)):
    persons = list(FROM_WHOM) if access.is_admin else access.ordered_persons()
    reads_others = access.is_admin or (access.active and access.can_view and access.can_view_others)
    if reads_others:
        view_persons = all_persons()
    elif access.active and access.can_view:
        view_persons = access.ordered_persons()
    else:
        view_persons = []
    return {
        "objects": access.allowed_objects(all_objects()),
        "from_whom": persons,   # only the persons this user may fill forms as
        "view_persons": view_persons,   # the persons whose forms this user may look at
        "to_whom": FIXED_KOMU,
        "payment_types": PAYMENT_TYPES,
        "work_types": _names_by_category(db, "work_type"),
        "inspectors": _names_by_category(db, "inspector"),
        "cashiers": _names_by_category(db, "cashier"),
        "tech_supervisors": _names_by_category(db, "tech_supervisor"),
        "suppliers": _names_by_category(db, "supplier"),
        "units": _names_by_category(db, "unit"),
        "all_persons": all_persons(),
        "me": {
            "user_id": access.user_id,
            "name": access.name,
            "is_admin": access.is_admin,
            "status": access.status,
            "persons": persons,
            "role": "admin" if access.is_admin else "user",
            "is_manager": access.is_manager,
            "objects": None if access.is_admin or access.can_view_all_objects else sorted(access.objects or []),
            **access.perms(),
        },
    }


@app.post("/api/names")
def add_name_option(
    payload: NameOptionIn, db: Session = Depends(get_db), access: Access = Depends(current_access)
):
    _require_active(access)
    _require(access, access.can_create or access.can_edit, "ro'yxatga nom qo'shish")
    category = payload.category.strip()
    name = payload.name.strip()
    if category not in NAME_OPTION_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Unknown category: {category}")
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    exists = (
        db.query(NameOption)
        .filter(NameOption.category == category, NameOption.name == name)
        .first()
    )
    if not exists:
        db.add(NameOption(category=category, name=name))
        db.commit()

    return {"names": _names_by_category(db, category)}


@app.delete("/api/names")
def delete_name_option(
    category: str, name: str, db: Session = Depends(get_db), access: Access = Depends(current_access)
):
    """
    Lets a bad entry (a stray partial word saved by mistake, e.g. from
    tabbing away mid-typing before this got a length guard) be removed from
    a growable dropdown/autocomplete list - used by the "manage" UI on
    items.html for Поставщик, but works for any NAME_OPTION_CATEGORIES.
    """
    _require_active(access)
    _require(access, access.can_manage_lists, "ro'yxatdan o'chirish")
    if category not in NAME_OPTION_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Unknown category: {category}")

    row = (
        db.query(NameOption)
        .filter(NameOption.category == category, NameOption.name == name)
        .first()
    )
    if row:
        db.delete(row)
        db.commit()

    return {"names": _names_by_category(db, category)}


@app.post("/api/zayavka")
async def create_zayavka(
    payload: ZayavkaIn, db: Session = Depends(get_db), access: Access = Depends(current_access)
):
    """
    The Mini App's save path (webapp/items.html calls this directly via
    fetch). Saves the record, then generates the .xlsx and sends it over
    Telegram itself - see app/notify.py for why this replaced sendData().
    A user may only file a zayavka as a person whose channel they belong to.
    """
    _require_active(access)
    _require(access, access.can_create, "zayavka to'ldirish")
    _require_write_scope(access, payload.from_whom, payload.object_name)

    minute_text = (payload.code_minute or "").strip()
    code_minute = int(minute_text) if minute_text.isdigit() and int(minute_text) <= 59 else None

    items = [item.dict() for item in payload.items]
    _require_work_type(items)
    zayavka = create_zayavka_record(
        db,
        object_name=payload.object_name,
        zayavka_date=payload.date,
        from_whom=payload.from_whom,
        payment_type=payload.payment_type or (PAYMENT_TYPES[0] if PAYMENT_TYPES else ""),
        items=items,
        to_whom=payload.to_whom,
        inspector=payload.inspector,
        cashier=payload.cashier,
        tech_supervisor=payload.tech_supervisor,
        tg_user_id=access.user_id,
        tg_user_name=access.name,
        code_minute=code_minute,
    )

    await send_zayavka_document(bot, zayavka, notify_chat_id=access.user_id)

    return zayavka.to_dict()


@app.put("/api/zayavka/{zayavka_id}")
async def edit_zayavka(
    zayavka_id: int,
    payload: ZayavkaIn,
    db: Session = Depends(get_db),
    access: Access = Depends(current_access),
):
    """
    Edits an already-submitted zayavka: webapp/items.html?edit_id=... loads
    the existing record, lets the user change items/от кого/вид оплаты and
    the approval fields, then PUTs here instead of POSTing a new one.
    Regenerates the .xlsx and resends it (see update_zayavka_record - the
    object/date/Номер заявки are intentionally left untouched).
    """
    z = _visible_zayavka(db, zayavka_id, access)
    _require(access, access.can_edit, "tahrirlash")
    _require_write_scope(access, z.from_whom, z.object_name, z.created_by_tg_id)  # the form as it is now
    _require_write_scope(access, payload.from_whom, z.object_name)                # ...and whom it is moved to

    items = [item.dict() for item in payload.items]
    _require_work_type(items)
    zayavka = update_zayavka_record(
        db,
        zayavka_id,
        from_whom=payload.from_whom,
        payment_type=payload.payment_type or (PAYMENT_TYPES[0] if PAYMENT_TYPES else ""),
        items=items,
        to_whom=payload.to_whom,
        inspector=payload.inspector,
        cashier=payload.cashier,
        tech_supervisor=payload.tech_supervisor,
        saved_by=access.name,
    )
    if not zayavka:
        raise HTTPException(status_code=404, detail="Not found")

    await send_zayavka_document(bot, zayavka, notify_chat_id=access.user_id, updated=True)

    return zayavka.to_dict()


def _filtered_zayavkas(
    db: Session,
    access: Access,
    object_name: Optional[str] = None,
    from_whom: Optional[str] = None,
    date_from: Optional[date_type] = None,
    date_to: Optional[date_type] = None,
    created_by: Optional[int] = None,
):
    """
    The table page's filter criteria - shared by the list and the Excel export.
    Always limited to what `access` may see and never includes deleted zayavkas.

    The privacy unit is the individual submitter (Telegram id/phone), not the
    person/channel: without can_view_others a user only sees zayavkas THEY
    personally created (created_by_tg_id), even if a colleague files under
    the same person - see Access.can_read. Records saved before this field
    existed (created_by_tg_id is NULL) fall back to the old person-based rule.
    """
    # selectinload fetches the items of ALL returned zayavkas in one extra
    # query, instead of one query per zayavka (the "N+1" problem: 200 rows
    # used to mean 203 queries).
    query = (
        db.query(Zayavka)
        .options(selectinload(Zayavka.items))
        .filter(Zayavka.deleted_at.is_(None))
    )
    if not access.is_admin:
        if not (access.active and access.can_view):
            return query.filter(false())
        if not access.can_view_others:
            query = query.filter(or_(
                Zayavka.created_by_tg_id == access.user_id,
                and_(Zayavka.created_by_tg_id.is_(None), Zayavka.from_whom.in_(sorted(access.persons))),
            ))
        if not access.can_view_all_objects:
            query = query.filter(Zayavka.object_name.in_(sorted(access.objects or [])))
    if object_name:
        query = query.filter(Zayavka.object_name == object_name)
    if from_whom:
        query = query.filter(Zayavka.from_whom == from_whom)
    if created_by:
        query = query.filter(Zayavka.created_by_tg_id == created_by)
    if date_from:
        query = query.filter(Zayavka.zayavka_date >= date_from)
    if date_to:
        query = query.filter(Zayavka.zayavka_date <= date_to)
    return query


def _version_info(db: Session, rows: list) -> dict:
    """{zayavka_id: (latest version_no, latest saved_at as naive UTC)} - one query for all rows."""
    if not rows:
        return {}
    return {
        zid: (count, saved_at)
        for zid, count, saved_at in (
            db.query(
                ZayavkaVersion.zayavka_id,
                func.max(ZayavkaVersion.version_no),
                func.max(ZayavkaVersion.created_at),
            )
            .filter(ZayavkaVersion.zayavka_id.in_([z.id for z in rows]))
            .group_by(ZayavkaVersion.zayavka_id)
            .all()
        )
    }


def _with_version_info(db: Session, rows: list) -> list:
    """FULL zayavka dicts (all items) plus version_count and last_saved_at - used by the Excel export."""
    info = _version_info(db, rows)
    items = []
    for z in rows:
        d = z.to_dict()
        count, saved_at = info.get(z.id, (1, None))
        d["version_count"] = count
        d["last_saved_at"] = saved_at.isoformat() if saved_at else None
        items.append(d)
    return items


def _list_row(z: Zayavka, count: int, saved_at) -> dict:
    """
    One LIGHT row for the table page: just what the list displays (the
    per-zayavka totals are summed here) - not every item of every zayavka,
    which made each list load ~770 KB. The full record is fetched on demand
    (GET /api/zayavka/{id}) when a row is opened.
    """
    items = z.items
    return {
        "id": z.id,
        "number": z.number,
        "object_name": z.object_name,
        "date": z.zayavka_date,
        "from_whom": z.from_whom,
        "to_whom": z.to_whom,
        "payment_type": z.payment_type,
        "created_at": z.created_at.isoformat() if z.created_at else None,
        "created_by_tg_id": z.created_by_tg_id,
        "created_by_name": z.created_by_name,
        "items_count": len(items),
        "first_product": (items[0].product_name or "") if items else "",
        "total": sum((i.total or 0) for i in items),
        "advance": sum((i.advance or 0) for i in items),
        "remainder": sum((i.remainder or 0) for i in items),
        "version_count": count,
        "last_saved_at": saved_at.isoformat() if saved_at else None,
    }


@app.post("/api/zayavka/export")
async def export_zayavkalar(
    payload: ExportIn, db: Session = Depends(get_db), access: Access = Depends(current_access)
):
    """
    Builds an Excel report of the zayavkas matching the table page's filters
    (limited to what this user may see). A normal user's report goes to their
    own person's channel - one report per person, only that person's forms.
    An admin's report (which can contain everyone's forms) goes to the admin's
    own private chat, never to a shared channel.
    """
    _require(access, access.can_report, "Excel hisobot yuborish")
    requested_by = access.name or str(access.user_id)

    filters = {
        "object_name": payload.object_name,
        "from_whom": payload.from_whom,
        "date_from": payload.date_from,
        "date_to": payload.date_to,
    }
    zayavkas = (
        _filtered_zayavkas(db, access, created_by=payload.created_by, **filters)
        .order_by(Zayavka.created_at.desc()).all()
    )
    if not access.is_admin:
        # A report goes to a person's own channel, so it holds that person's forms only,
        # even if this user may also read other appliers' forms.
        zayavkas = [z for z in zayavkas if access.can_write(z.from_whom, z.object_name, z.created_by_tg_id)]
    if not zayavkas:
        raise HTTPException(status_code=404, detail="Bu filtr bo'yicha zayavka topilmadi")

    if access.is_admin:
        destination = "own_chat"
        groups = [(filters, zayavkas, [access.user_id])]
    else:
        destination = "channels"
        groups = []
        by_person: dict = {}
        for z in zayavkas:
            by_person.setdefault(z.from_whom, []).append(z)
        for person, person_zayavkas in by_person.items():
            chat_id = PERSON_ROUTES.get(person)
            if chat_id:
                groups.append(({**filters, "from_whom": person}, person_zayavkas, [chat_id]))
        if not groups:
            raise HTTPException(status_code=400, detail="Kanal sozlanmagan - administratorga murojaat qiling")

    logger.info(
        "Report export requested by %s (tg id %s): %d zayavkas in %d report(s), filters=%s, to=%s",
        requested_by, access.user_id, len(zayavkas), len(groups), filters, destination,
    )

    generated_at = datetime.now(timezone.utc).astimezone(timezone(TASHKENT_OFFSET)).replace(tzinfo=None)
    sent_reports = 0
    for report_filters, group_zayavkas, chat_ids in groups:
        rows = _with_version_info(db, group_zayavkas)
        for row in rows:
            # stored as naive UTC; the report shows Tashkent time
            saved = row.get("last_saved_at")
            row["last_saved_at"] = (
                datetime.fromisoformat(saved) + TASHKENT_OFFSET if saved else None
            )
        tmp_dir = tempfile.mkdtemp(prefix="zayavka_report_")
        try:
            path = save_report(rows, report_filters, generated_at, requested_by, tmp_dir)
            caption = build_report_caption(rows, report_filters, generated_at, requested_by)
            sent_reports += 1 if await send_report_file(bot, path, caption, chat_ids) else 0
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    if not sent_reports:
        logger.error("Report export FAILED: nothing could be posted (%s)", destination)
        raise HTTPException(
            status_code=502,
            detail="Yuborib bo'lmadi (bot kanalda admin ekanini va sizning chatingiz ochiq ekanini tekshiring)",
        )
    logger.info("Report export sent: %d report(s) for %d zayavkas", sent_reports, len(zayavkas))
    return {"ok": True, "count": len(zayavkas), "reports": sent_reports, "destination": destination}


@app.get("/api/zayavka")
def list_zayavka(
    q: Optional[str] = Query(None, description="Free-text search"),
    object_name: Optional[str] = None,
    from_whom: Optional[str] = None,
    date_from: Optional[date_type] = None,
    date_to: Optional[date_type] = None,
    created_by: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    access: Access = Depends(current_access),
):
    query = _filtered_zayavkas(db, access, object_name, from_whom, date_from, date_to, created_by)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Zayavka.number.ilike(like),
                Zayavka.object_name.ilike(like),
                Zayavka.from_whom.ilike(like),
                Zayavka.items.any(ZayavkaItem.product_name.ilike(like)),
                Zayavka.items.any(ZayavkaItem.supplier.ilike(like)),
                Zayavka.items.any(ZayavkaItem.comment.ilike(like)),
            )
        )

    total = query.count()
    rows = (
        query.order_by(Zayavka.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    info = _version_info(db, rows)
    # Phone numbers of who submitted these rows - only fetched (and only useful) when
    # this user can see more than their own forms, to tell submitters apart in the list.
    phones: dict = {}
    if access.is_admin or access.can_view_others:
        tg_ids = {z.created_by_tg_id for z in rows if z.created_by_tg_id}
        if tg_ids:
            phones = dict(
                db.query(AppUser.telegram_id, AppUser.phone)
                .filter(AppUser.telegram_id.in_(tg_ids), AppUser.phone.isnot(None))
                .all()
            )
    items = []
    for z in rows:
        row = _list_row(z, *info.get(z.id, (1, None)))
        row["created_by_phone"] = phones.get(z.created_by_tg_id)
        # Forms of other appliers can be read (if allowed) but only own ones can be changed.
        row["can_write"] = access.can_write(z.from_whom, z.object_name, z.created_by_tg_id)
        items.append(row)
    return {"total": total, "items": items}


@app.get("/api/zayavka/{zayavka_id}")
def get_zayavka(
    zayavka_id: int, db: Session = Depends(get_db), access: Access = Depends(current_access)
):
    return _visible_zayavka(db, zayavka_id, access).to_dict()


def _excel_response(d: dict, background_tasks: BackgroundTasks, file_suffix: str = "") -> FileResponse:
    """Builds the .xlsx for a zayavka dict (live record or saved version) as a download."""
    tmp_dir = tempfile.mkdtemp(prefix="zayavka_dl_")
    path = save_workbook(d, tmp_dir)
    background_tasks.add_task(shutil.rmtree, tmp_dir, True)
    filename = os.path.basename(path)
    if file_suffix:
        filename = filename[: -len(".xlsx")] + file_suffix + ".xlsx"
    return FileResponse(
        path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _get_version(db: Session, zayavka_id: int, version_no: int) -> ZayavkaVersion:
    v = (
        db.query(ZayavkaVersion)
        .filter(ZayavkaVersion.zayavka_id == zayavka_id, ZayavkaVersion.version_no == version_no)
        .first()
    )
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    return v


@app.post("/api/zayavka/{zayavka_id}/excel_link")
def zayavka_excel_link(
    zayavka_id: int, db: Session = Depends(get_db), access: Access = Depends(current_access)
):
    """A short-lived download link for the latest Excel of a zayavka this user may access."""
    _visible_zayavka(db, zayavka_id, access)
    _require(access, access.can_export, "Excel yuklab olish")
    path = f"/api/zayavka/{zayavka_id}/excel"
    return {"url": f"{path}?t={make_download_token(access.user_id, path)}"}


@app.get("/api/zayavka/{zayavka_id}/excel")
def download_zayavka_excel(
    zayavka_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    access: Access = Depends(download_access),
):
    """Regenerates the zayavka's latest .xlsx on demand (same generator as the file sent to Telegram)."""
    z = _visible_zayavka(db, zayavka_id, access)
    _require(access, access.can_export, "Excel yuklab olish")
    return _excel_response(z.to_dict(), background_tasks)


@app.post("/api/zayavka/{zayavka_id}/send_me")
async def send_zayavka_to_me(
    zayavka_id: int, db: Session = Depends(get_db), access: Access = Depends(current_access)
):
    """Re-sends the zayavka's latest Excel to the requesting user's own chat only."""
    z = _visible_zayavka(db, zayavka_id, access)
    _require(access, access.can_export, "Excel yuborish")
    ok = await send_zayavka_to_chat(bot, z, access.user_id)
    if not ok:
        raise HTTPException(status_code=502, detail="Telegramga yuborib bo'lmadi (botga /start bosing)")
    return {"ok": True}


@app.get("/api/zayavka/{zayavka_id}/versions")
def list_zayavka_versions(
    zayavka_id: int, db: Session = Depends(get_db), access: Access = Depends(current_access)
):
    """Every saved version of a zayavka, newest first (the first entry is the latest)."""
    z = _visible_zayavka(db, zayavka_id, access)
    versions = (
        db.query(ZayavkaVersion)
        .filter(ZayavkaVersion.zayavka_id == zayavka_id)
        .order_by(ZayavkaVersion.version_no.desc())
        .all()
    )
    return {"number": z.number, "versions": [v.summary() for v in versions]}


@app.get("/api/zayavka/{zayavka_id}/versions/{version_no}")
def get_zayavka_version(
    zayavka_id: int,
    version_no: int,
    db: Session = Depends(get_db),
    access: Access = Depends(current_access),
):
    """The full contents of one saved version (what its Excel showed), for the read-only version page."""
    _visible_zayavka(db, zayavka_id, access)
    v = _get_version(db, zayavka_id, version_no)
    version_count = (
        db.query(func.max(ZayavkaVersion.version_no))
        .filter(ZayavkaVersion.zayavka_id == zayavka_id)
        .scalar()
    ) or version_no
    return {
        **v.data(),
        "version_no": v.version_no,
        "version_count": version_count,
        "action": v.action,
        "saved_by": v.saved_by,
        "saved_at": v.created_at.isoformat() if v.created_at else None,
    }


@app.post("/api/zayavka/{zayavka_id}/versions/{version_no}/excel_link")
def version_excel_link(
    zayavka_id: int,
    version_no: int,
    db: Session = Depends(get_db),
    access: Access = Depends(current_access),
):
    _visible_zayavka(db, zayavka_id, access)
    _require(access, access.can_export, "Excel yuklab olish")
    _get_version(db, zayavka_id, version_no)
    path = f"/api/zayavka/{zayavka_id}/versions/{version_no}/excel"
    return {"url": f"{path}?t={make_download_token(access.user_id, path)}"}


@app.get("/api/zayavka/{zayavka_id}/versions/{version_no}/excel")
def download_version_excel(
    zayavka_id: int,
    version_no: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    access: Access = Depends(download_access),
):
    """The Excel exactly as it was at that version."""
    _visible_zayavka(db, zayavka_id, access)
    _require(access, access.can_export, "Excel yuklab olish")
    v = _get_version(db, zayavka_id, version_no)
    return _excel_response(v.data(), background_tasks, file_suffix=f"-v{version_no}")


@app.post("/api/zayavka/{zayavka_id}/versions/{version_no}/send_me")
async def send_version_to_me(
    zayavka_id: int,
    version_no: int,
    db: Session = Depends(get_db),
    access: Access = Depends(current_access),
):
    _visible_zayavka(db, zayavka_id, access)
    _require(access, access.can_export, "Excel yuborish")
    v = _get_version(db, zayavka_id, version_no)
    ok = await send_dict_to_chat(bot, v.data(), access.user_id, f"📄 Zayavka Excel - {version_no}-versiya")
    if not ok:
        raise HTTPException(status_code=502, detail="Telegramga yuborib bo'lmadi (botga /start bosing)")
    return {"ok": True}


@app.delete("/api/zayavka/{zayavka_id}")
def delete_zayavka(
    zayavka_id: int,
    permanent: bool = False,
    db: Session = Depends(get_db),
    access: Access = Depends(current_access),
):
    """
    Deletes a zayavka the user may access. It's a SOFT delete: hidden
    everywhere, but kept (with its versions) so an admin can restore it.
    Only an admin may erase one for good (?permanent=true). The Excel already
    posted to Telegram stays in the chat - Telegram messages aren't recalled.
    """
    z = _visible_zayavka(db, zayavka_id, access)
    _require(access, access.can_delete, "o'chirish")
    _require_write_scope(access, z.from_whom, z.object_name, z.created_by_tg_id)
    if permanent:
        if not access.is_admin:
            raise HTTPException(status_code=403, detail="Faqat administrator butunlay o'chira oladi")
        db.delete(z)
    else:
        z.deleted_at = datetime.utcnow()
        z.deleted_by = access.name or str(access.user_id)
        logger.info("Zayavka %s (%s) deleted by %s (tg id %s)", z.id, z.number, access.name, access.user_id)
    db.commit()
    return {"ok": True}


@app.post("/api/zayavka/{zayavka_id}/restore")
def restore_zayavka(
    zayavka_id: int, db: Session = Depends(get_db), access: Access = Depends(current_access)
):
    """Admin only: bring a soft-deleted zayavka back."""
    if not access.is_admin:
        raise HTTPException(status_code=403, detail="Faqat administrator tiklay oladi")
    z = db.query(Zayavka).filter(Zayavka.id == zayavka_id, Zayavka.deleted_at.isnot(None)).first()
    if not z:
        raise HTTPException(status_code=404, detail="Not found")
    z.deleted_at = None
    z.deleted_by = None
    db.commit()
    return {"ok": True}


# --- access requests (a pending user) ------------------------------------------

@app.post("/api/me/request")
async def request_access(payload: AccessRequestIn, access: Access = Depends(current_access)):
    """
    A pending user asks for access. "Ro'yxatdan o'tish" additionally sends
    a typed name + phone number - unlike the bot's contact-share button
    (app/bot.py:contact_shared), Telegram hasn't verified this phone is
    really theirs, so it's saved as information for the admin to review,
    never used to auto-approve or auto-link an invited account.
    """
    if access.status != "pending":
        raise HTTPException(status_code=400, detail="So'rov faqat tasdiqlanmagan foydalanuvchilar uchun")
    person = (payload.person or "").strip() or None
    if person and person not in all_persons():
        raise HTTPException(status_code=400, detail="Noma'lum shaxs")
    note = (payload.note or "").strip()[:500] or None
    name = (payload.name or "").strip()[:120] or None
    phone = None
    if payload.phone and payload.phone.strip():
        phone = normalize_phone(payload.phone)
        if not phone:
            raise HTTPException(status_code=400, detail="Telefon raqami noto'g'ri (masalan +998 90 123 45 67)")

    with SessionLocal() as sdb:
        row = sdb.query(AppUser).filter(AppUser.telegram_id == access.user_id).first()
        if row is not None:
            if name:
                row.name = name
            if phone:
                row.phone = phone
            row.requested_person = person
            row.note = note
            sdb.commit()

    who = html.escape(name or access.name) + f" (ID <code>{access.user_id}</code>)"
    await notify_admins(
        bot,
        "📩 <b>Kirish so'rovi</b>\n"
        f"{who}\n"
        f"Telefon: {('+' + phone) if phone else '—'}\n"
        f"Shaxs/kanal: {person or '—'}\n{note or ''}\n\n"
        "Tasdiqlash: ilovada ⋮ menyu → Settings.",
    )
    return {"ok": True}


# --- admin: users, persons and permissions ------------------------------------

def _admin_user(db: Session, user_id: int) -> AppUser:
    row = db.query(AppUser).filter(AppUser.id == user_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
    return row


def _check_persons(persons) -> list:
    known = set(all_persons())
    unknown = [p for p in persons if p not in known]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Noma'lum shaxs: {', '.join(unknown)}")
    return list(persons)


def _check_objects(objects) -> list:
    known = set(all_objects())
    unknown = [o for o in objects if o not in known]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Noma'lum obyekt: {', '.join(unknown)}")
    return list(objects)


def _perms_sent(payload) -> dict:
    """The permissions the request actually carries (None = not sent)."""
    return {key: getattr(payload, key) for key in PERMISSION_KEYS if getattr(payload, key) is not None}


def _guard_target(actor: Access, row: AppUser) -> None:
    """Someone who may only "add users" can't touch admins or other user-managers."""
    if actor.is_admin:
        return
    if row.role == "admin" or row.can_manage_users:
        raise HTTPException(
            status_code=403,
            detail="Administratorlar va boshqa boshqaruvchilarni faqat administrator o'zgartira oladi",
        )


def _guard_grant(actor: Access, perms: dict, role: Optional[str], persons, objects) -> None:
    """
    What `actor` may hand out. Admins: anything. A user with "add users" can only
    give permissions, persons and projects they have themselves, and never the
    admin role or the "add users" permission (or they could raise their own rank).
    """
    if actor.is_admin:
        return
    labels = {p["key"]: p["label"] for p in PERMISSION_CATALOG}
    if role == "admin":
        raise HTTPException(status_code=403, detail="Administrator rolini faqat administrator bera oladi")
    for key, value in perms.items():
        if value is not True:
            continue
        if key == "can_manage_users":
            raise HTTPException(status_code=403, detail="\"Foydalanuvchi qo'shish\" ruxsatini faqat administrator bera oladi")
        if not getattr(actor, key):
            raise HTTPException(
                status_code=403,
                detail=f"Sizda \"{labels[key]}\" ruxsati yo'q - uni boshqalarga bera olmaysiz",
            )
    if persons is not None and set(persons) - set(actor.persons):
        raise HTTPException(status_code=403, detail="Faqat o'zingizga bog'langan shaxslarni bera olasiz")
    if objects is not None and not actor.can_view_all_objects and set(objects) - set(actor.objects or ()):
        raise HTTPException(status_code=403, detail="Faqat o'zingizga ochiq obyektlarni bera olasiz")


def _apply(row: AppUser, payload, perms: dict) -> None:
    """Writes the sent fields of an add/patch/approve request onto the row."""
    if getattr(payload, "name", None) is not None:
        row.name = payload.name.strip()
    if getattr(payload, "role", None) is not None:
        row.role = payload.role
    if getattr(payload, "persons", None) is not None:
        row.persons = payload.persons
    if getattr(payload, "objects", None) is not None:
        row.objects = payload.objects
    for key, value in perms.items():
        setattr(row, key, value)


def _clean_role(role: Optional[str]) -> Optional[str]:
    if role is None:
        return None
    if role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="Noma'lum rol")
    return role


def _phone_or_400(text: Optional[str]) -> Optional[str]:
    if text is None or not text.strip():
        return None
    phone = normalize_phone(text)
    if not phone:
        raise HTTPException(status_code=400, detail="Telefon raqami noto'g'ri (masalan +998 90 123 45 67)")
    return phone


async def _tell_user(telegram_id: Optional[int], text: str) -> None:
    if not telegram_id:
        return
    try:
        await bot.send_message(telegram_id, text, parse_mode="HTML")
    except Exception:
        logger.info("Could not message user %s (they may not have started the bot)", telegram_id)


# Names of the owners (ADMIN_IDS have no users-table row): learned when they open
# the app, or asked of Telegram once.
_admin_info: dict = {}


async def _refresh_admin_info(current: Access) -> None:
    if current.is_owner:
        _admin_info[current.user_id] = {"name": current.name, "username": None}
    for admin_id in ADMIN_IDS:
        if admin_id in _admin_info:
            continue
        try:
            chat = await bot.get_chat(admin_id)
            name = " ".join(filter(None, [chat.first_name, chat.last_name])) or chat.username or ""
            _admin_info[admin_id] = {"name": name, "username": chat.username}
        except Exception:
            _admin_info[admin_id] = {"name": "", "username": None}


def _admin_list(db: Session, actor: Access) -> dict:
    rows = db.query(AppUser).order_by(AppUser.created_at.desc()).all()
    users = [r.to_dict() for r in rows]
    counts = {
        status: sum(1 for u in users if u["status"] == status)
        for status in ("pending", "approved", "blocked", "invited")
    }
    owners = [
        {
            "telegram_id": admin_id,
            **_admin_info.get(admin_id, {"name": "", "username": None}),
            "last_seen_at": OWNER_LAST_SEEN[admin_id].isoformat() if admin_id in OWNER_LAST_SEEN else None,
        }
        for admin_id in sorted(ADMIN_IDS)
    ]
    counts["admins"] = len(owners) + sum(1 for u in users if u["role"] == "admin" and u["status"] == "approved")
    return {
        "users": users,
        "owners": owners,
        "persons": all_persons(),
        "objects": all_objects(),
        "counts": counts,
        "catalog": PERMISSION_CATALOG,
        "defaults": PERMISSION_DEFAULTS,
        "me": {
            "user_id": actor.user_id,
            "is_admin": actor.is_admin,
            "is_owner": actor.is_owner,
            "persons": all_persons() if actor.is_admin else sorted(actor.persons),
            "objects": all_objects() if (actor.is_admin or actor.can_view_all_objects) else sorted(actor.objects or []),
            "perms": actor.perms(),
        },
    }


@app.get("/api/admin/users")
async def admin_list_users(db: Session = Depends(get_db), actor: Access = Depends(manager_access)):
    await _refresh_admin_info(actor)
    return _admin_list(db, actor)


@app.post("/api/admin/users")
async def admin_add_user(
    payload: AdminUserIn, db: Session = Depends(get_db), actor: Access = Depends(manager_access)
):
    """
    Adds a user (or an admin) by PHONE NUMBER. The person then shares their phone
    with the bot (or from the Mini App) and is linked and approved with what is
    set here. If they can't, a Telegram id works instead (approved at once).
    """
    phone = _phone_or_400(payload.phone)
    if not phone and not payload.telegram_id:
        raise HTTPException(status_code=400, detail="Telefon raqamini kiriting")
    if payload.telegram_id in ADMIN_IDS:
        raise HTTPException(status_code=400, detail="Bu foydalanuvchi allaqachon bosh administrator")

    role = _clean_role(payload.role) or "user"
    persons = _check_persons(payload.persons)
    objects = _check_objects(payload.objects)
    if role == "user" and not persons:
        raise HTTPException(status_code=400, detail="Kamida bitta shaxsni tanlang")
    # Defaults a delegate doesn't hold themselves are left off rather than refused.
    defaults = {k: (v if actor.is_admin else bool(v and getattr(actor, k))) for k, v in PERMISSION_DEFAULTS.items()}
    perms = {**defaults, **_perms_sent(payload)}
    _guard_grant(actor, perms, role, persons, objects)

    row = None
    if payload.telegram_id:
        row = db.query(AppUser).filter(AppUser.telegram_id == payload.telegram_id).first()
    if row is None and phone:
        row = db.query(AppUser).filter(AppUser.phone == phone).first()
    if row is not None:
        _guard_target(actor, row)
    else:
        row = AppUser(source="admin")
        db.add(row)
    if phone and not (row.phone and payload.telegram_id):   # keep a number the person shared themselves
        clash = db.query(AppUser).filter(AppUser.phone == phone, AppUser.id != row.id).first()
        if clash is not None:
            raise HTTPException(status_code=400, detail="Bu telefon raqami boshqa foydalanuvchida bor")
        row.phone = phone
    if payload.telegram_id and row.telegram_id is None:
        row.telegram_id = payload.telegram_id

    row.role = role
    row.name = (payload.name or "").strip() or row.name or ""
    row.persons = persons
    row.objects = objects
    for key, value in perms.items():
        setattr(row, key, value)
    row.status = "approved" if row.telegram_id else "invited"
    row.approved_at = datetime.utcnow()
    row.approved_by = actor.name or str(actor.user_id)
    db.commit()

    await _tell_user(row.telegram_id, "✅ Sizga zayavka ilovasiga kirish ruxsati berildi. /start bosing.")
    return _admin_list(db, actor)


@app.patch("/api/admin/users/{user_id}")
def admin_update_user(
    user_id: int,
    payload: AdminUserPatch,
    db: Session = Depends(get_db),
    actor: Access = Depends(manager_access),
):
    row = _admin_user(db, user_id)
    _guard_target(actor, row)
    role = _clean_role(payload.role)
    if role is not None and role != row.role:
        if row.telegram_id == actor.user_id:
            raise HTTPException(status_code=400, detail="O'zingizning rolingizni o'zgartira olmaysiz")
    persons = _check_persons(payload.persons) if payload.persons is not None else None
    objects = _check_objects(payload.objects) if payload.objects is not None else None
    perms = _perms_sent(payload)
    _guard_grant(actor, perms, role if role != row.role else None, persons, objects)

    phone = _phone_or_400(payload.phone)
    if phone and phone != row.phone:
        if row.telegram_id is not None and row.phone:
            raise HTTPException(status_code=400, detail="Bog'langan foydalanuvchining raqamini o'zgartirib bo'lmaydi")
        if db.query(AppUser).filter(AppUser.phone == phone, AppUser.id != row.id).first():
            raise HTTPException(status_code=400, detail="Bu telefon raqami boshqa foydalanuvchida bor")
        row.phone = phone
    if perms.get("can_manage_users") is False and row.telegram_id == actor.user_id and not actor.is_admin:
        raise HTTPException(status_code=400, detail="O'zingizdan bu ruxsatni olib tashlay olmaysiz")
    _apply(row, payload, perms)
    if role is not None:
        row.role = role
    db.commit()
    return _admin_list(db, actor)


@app.post("/api/admin/users/{user_id}/approve")
async def admin_approve_user(
    user_id: int,
    payload: AdminUserPatch,
    db: Session = Depends(get_db),
    actor: Access = Depends(manager_access),
):
    """Approves a pending (or blocked) user for the chosen persons, projects and permissions."""
    row = _admin_user(db, user_id)
    _guard_target(actor, row)
    role = _clean_role(payload.role) or row.role
    persons = _check_persons(payload.persons if payload.persons is not None else row.persons)
    if not persons and row.requested_person and role == "user":
        persons = _check_persons([row.requested_person])
    if not persons and role == "user":
        raise HTTPException(status_code=400, detail="Kamida bitta shaxsni tanlang")
    objects = _check_objects(payload.objects if payload.objects is not None else row.objects)
    perms = _perms_sent(payload)
    _guard_grant(actor, perms, role if role != row.role else None, persons, objects)
    _apply(row, payload, perms)
    row.role = role
    row.persons = persons
    row.objects = objects
    row.status = "approved" if row.telegram_id else "invited"
    row.approved_at = datetime.utcnow()
    row.approved_by = actor.name or str(actor.user_id)
    db.commit()
    await _tell_user(row.telegram_id, "✅ Sizga zayavka ilovasiga kirish ruxsati berildi. /start bosing.")
    return _admin_list(db, actor)


@app.post("/api/admin/users/{user_id}/block")
def admin_block_user(
    user_id: int, db: Session = Depends(get_db), actor: Access = Depends(manager_access)
):
    """Removes a user's access (or rejects a request). They stay blocked until restored."""
    row = _admin_user(db, user_id)
    _guard_target(actor, row)
    if row.telegram_id == actor.user_id:
        raise HTTPException(status_code=400, detail="O'zingizni faolsizlantira olmaysiz")
    row.status = "blocked"
    db.commit()
    logger.info("User %s (%s) blocked by %s", row.telegram_id, row.name, actor.name)
    return _admin_list(db, actor)


@app.post("/api/admin/users/{user_id}/unblock")
def admin_unblock_user(
    user_id: int, db: Session = Depends(get_db), actor: Access = Depends(manager_access)
):
    """Restores a blocked user (approved, or invited if they haven't confirmed their phone yet)."""
    row = _admin_user(db, user_id)
    _guard_target(actor, row)
    if not (row.persons or row.role == "admin"):
        row.status = "pending"
    else:
        row.status = "approved" if row.telegram_id else "invited"
    if row.status == "approved":
        row.approved_at = datetime.utcnow()
        row.approved_by = actor.name or str(actor.user_id)
    db.commit()
    return _admin_list(db, actor)


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(
    user_id: int, db: Session = Depends(get_db), actor: Access = Depends(manager_access)
):
    """
    Deletes a user's record (for an invitation, that cancels it). A channel member
    can't be deleted: they would be re-added automatically the next time they open
    the app while still in the channel, so they must be deactivated (blocked) instead.
    """
    row = _admin_user(db, user_id)
    _guard_target(actor, row)
    if row.telegram_id == actor.user_id:
        raise HTTPException(status_code=400, detail="O'zingizni o'chira olmaysiz")
    if row.source == "channel":
        raise HTTPException(
            status_code=400,
            detail="Kanal a'zosini o'chirib bo'lmaydi (kanalda bo'lgani uchun qayta qo'shiladi) - uni faolsizlantiring",
        )
    logger.info("User %s (%s) deleted by %s", row.telegram_id, row.name, actor.name)
    db.delete(row)
    db.commit()
    return _admin_list(db, actor)


# Serve the mini app static files (index.html, table.html, search.html, css, js)
app.mount("/", StaticFiles(directory=str(WEBAPP_DIR), html=True), name="webapp")
