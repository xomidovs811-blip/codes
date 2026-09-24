"""
Shared "create/update a zayavka" logic, used by both the FastAPI mini-app
endpoint (app/api.py) and anything else that needs it. Keeping this in one
place means every entry point computes the Номер заявки and stores records
the same way.
"""
import json
from datetime import date as date_type, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Zayavka, ZayavkaItem, ZayavkaVersion, NameOption
from app.code_gen import generate_number
from app.config import FIXED_KOMU, WORK_TYPES


def _register_new_names(db: Session, category: str, field: str, items: list) -> None:
    """
    Both Поставщик and Ед.изм are free-text (autocomplete fields, not fixed
    dropdowns), so any value typed there that isn't already known gets
    remembered as a NameOption - otherwise the same supplier/unit ends up
    spelled differently across zayavkas over time (which, for suppliers,
    breaks tracking their prepayments).

    Require at least 2 characters - a single stray letter left behind from
    mid-typing (tabbing/clicking away before finishing) shouldn't get
    remembered as a real value.
    """
    names = {(item.get(field) or "").strip() for item in items}
    names = {n for n in names if len(n) >= 2}
    if not names:
        return
    existing = {
        n for (n,) in db.query(NameOption.name)
        .filter(NameOption.category == category, NameOption.name.in_(names))
        .all()
    }
    for name in names - existing:
        db.add(NameOption(category=category, name=name))


def _register_new_suppliers_and_units(db: Session, items: list) -> None:
    _register_new_names(db, "supplier", "supplier", items)
    _register_new_names(db, "unit", "unit", items)
    _register_new_names(db, "work_type", "work_type", items)


def seed_default_work_types(db: Session) -> int:
    """
    Fills the "Выполняемая работа (сметная группа)" list from config.WORK_TYPES
    the first time (only while the list is completely empty), so a fresh
    database starts with the standard groups. Once entries exist they're
    managed in the Mini App, and this never touches them again.
    """
    has_any = db.query(NameOption.id).filter(NameOption.category == "work_type").first()
    if has_any:
        return 0
    for name in WORK_TYPES:
        db.add(NameOption(category="work_type", name=name))
    db.commit()
    return len(WORK_TYPES)


# A form filled in over a long session (checkpointed with repeated
# "Saqlash" taps so nothing gets lost, exactly what the draft-autosave/
# unsaved-changes guard on items.html now encourages) used to get a brand
# new version for every single one of those taps - five edits ten minutes
# apart looked like five separate revisions in "Tarix" instead of one
# evolving one. Saving again within this window, by the same person, right
# after the last save updates that same version in place instead.
VERSION_COALESCE_MINUTES = 15


def _add_version(
    db: Session, zayavka: Zayavka, action: str, saved_by: Optional[str] = None, created_at=None
) -> None:
    """
    Snapshots the zayavka's current state as its next version (1, 2, 3...) -
    or, for a quick follow-up edit by the same person (see
    VERSION_COALESCE_MINUTES above), updates the last "updated" version in
    place instead of adding another one. The very first version ("created")
    is never coalesced into, so it always stays the original submission.
    Caller must have flushed so zayavka.id exists and the items are current.
    """
    last_version = (
        db.query(ZayavkaVersion)
        .filter(ZayavkaVersion.zayavka_id == zayavka.id)
        .order_by(ZayavkaVersion.version_no.desc())
        .first()
    )
    now = created_at or datetime.utcnow()
    if (
        action == "updated"
        and last_version is not None
        and last_version.action == "updated"
        and last_version.saved_by == saved_by
        and (now - last_version.created_at) <= timedelta(minutes=VERSION_COALESCE_MINUTES)
    ):
        last_version.snapshot = json.dumps(zayavka.to_dict(), default=str, ensure_ascii=False)
        last_version.created_at = now
        return

    version = ZayavkaVersion(
        zayavka_id=zayavka.id,
        version_no=(last_version.version_no if last_version else 0) + 1,
        action=action,
        saved_by=saved_by,
        snapshot=json.dumps(zayavka.to_dict(), default=str, ensure_ascii=False),
    )
    if created_at is not None:
        version.created_at = created_at
    db.add(version)


def backfill_versions(db: Session) -> int:
    """
    Gives every zayavka saved before version history existed a version 1
    (its current state - earlier edits were never recorded, so that's the
    oldest state that can be reproduced). Safe to run on every startup.
    """
    ids_with_versions = {zid for (zid,) in db.query(ZayavkaVersion.zayavka_id).distinct().all()}
    missing = [z for z in db.query(Zayavka).all() if z.id not in ids_with_versions]
    for z in missing:
        _add_version(db, z, "created", saved_by=z.created_by_name, created_at=z.created_at)
    if missing:
        db.commit()
    return len(missing)


def _build_items(items: list) -> list:
    """
    items: list of dicts with keys row_no, product_name, supplier, block,
    floor, unit, qty, price, advance, work_type, comment. `total` and
    `remainder` are computed here (qty*price, total-advance).
    """
    built = []
    for item in items:
        qty = item.get("qty") or 0
        price = item.get("price") or 0
        advance = item.get("advance") or 0
        total = qty * price
        built.append(
            ZayavkaItem(
                row_no=item.get("row_no"),
                product_name=item.get("product_name"),
                supplier=item.get("supplier"),
                block=item.get("block"),
                floor=item.get("floor"),
                unit=item.get("unit"),
                qty=item.get("qty"),
                price=item.get("price"),
                total=total,
                advance=item.get("advance"),
                remainder=total - advance,
                work_type=item.get("work_type"),
                comment=item.get("comment"),
            )
        )
    return built


def create_zayavka_record(
    db: Session,
    object_name: str,
    zayavka_date: date_type,
    from_whom: str,
    payment_type: str,
    items: list,
    to_whom: Optional[str] = None,
    tg_user_id: Optional[int] = None,
    tg_user_name: Optional[str] = None,
    inspector: Optional[str] = None,
    cashier: Optional[str] = None,
    tech_supervisor: Optional[str] = None,
    code_minute: Optional[int] = None,
) -> Zayavka:
    number = generate_number(object_name, from_whom, zayavka_date, minute=code_minute)

    # Guard against a (rare) duplicate code within the same day/object/from combo.
    suffix = 1
    base_number = number
    while db.query(Zayavka).filter(Zayavka.number == number).first() is not None:
        suffix += 1
        number = f"{base_number}-{suffix}"

    zayavka = Zayavka(
        number=number,
        object_name=object_name,
        zayavka_date=zayavka_date,
        from_whom=from_whom,
        to_whom=to_whom or FIXED_KOMU,
        payment_type=payment_type,
        inspector=inspector or None,
        cashier=cashier or None,
        tech_supervisor=tech_supervisor or None,
        created_by_tg_id=tg_user_id,
        created_by_name=tg_user_name,
    )
    zayavka.items = _build_items(items)
    _register_new_suppliers_and_units(db, items)

    db.add(zayavka)
    db.flush()
    _add_version(db, zayavka, "created", saved_by=tg_user_name)
    db.commit()
    db.refresh(zayavka)
    return zayavka


def update_zayavka_record(
    db: Session,
    zayavka_id: int,
    from_whom: str,
    payment_type: str,
    items: list,
    to_whom: Optional[str] = None,
    inspector: Optional[str] = None,
    cashier: Optional[str] = None,
    tech_supervisor: Optional[str] = None,
    saved_by: Optional[str] = None,
) -> Optional[Zayavka]:
    """
    Edits an already-submitted zayavka in place: replaces its items and
    updates От кого/Вид оплаты/approval fields. Object, date and the
    "Номер заявки" are deliberately left untouched - the number was already
    shared on the original file, so recomputing it here would make a
    corrected request look like an unrelated new one. Returns None if no
    zayavka with this id exists.
    """
    zayavka = db.query(Zayavka).filter(Zayavka.id == zayavka_id).first()
    if not zayavka:
        return None

    zayavka.from_whom = from_whom
    zayavka.payment_type = payment_type
    zayavka.to_whom = to_whom or zayavka.to_whom
    zayavka.inspector = inspector or None
    zayavka.cashier = cashier or None
    zayavka.tech_supervisor = tech_supervisor or None
    zayavka.items = _build_items(items)
    _register_new_suppliers_and_units(db, items)

    db.flush()
    _add_version(db, zayavka, "updated", saved_by=saved_by)
    db.commit()
    db.refresh(zayavka)
    return zayavka
