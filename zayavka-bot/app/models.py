import json
from datetime import datetime, date

from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime, ForeignKey, Text, BigInteger, Boolean,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db import Base


class Zayavka(Base):
    """
    Main "Zayavka" (request) record, corresponding to the top part of the form:
    Название объекта / Дата / От кого / Кому / Вид оплаты, plus the generated
    "Номер заявки" code.
    """
    __tablename__ = "zayavkalar"

    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(64), unique=True, index=True, nullable=False)  # Номер заявки

    object_name = Column(String(255), nullable=False)   # Название объекта
    zayavka_date = Column(Date, nullable=False)          # Дата
    from_whom = Column(String(255), nullable=False)      # От кого
    to_whom = Column(String(255), nullable=False)        # Кому (fixed)
    payment_type = Column(String(255), nullable=False)   # Вид оплаты (fixed)

    # Approval/signature block, printed at the bottom of the request.
    inspector = Column(String(255), nullable=True)        # Инспектор
    cashier = Column(String(255), nullable=True)          # Кассир
    tech_supervisor = Column(String(255), nullable=True)  # Техданзор

    created_by_tg_id = Column(BigInteger, nullable=True)
    created_by_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Soft delete: a "deleted" zayavka is hidden everywhere but the row (and its
    # versions) stay, so a mistaken delete can be undone by an admin.
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(String(255), nullable=True)

    items = relationship(
        "ZayavkaItem",
        back_populates="zayavka",
        cascade="all, delete-orphan",
        order_by="ZayavkaItem.row_no",
    )
    versions = relationship(
        "ZayavkaVersion",
        back_populates="zayavka",
        cascade="all, delete-orphan",
        order_by="ZayavkaVersion.version_no",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "number": self.number,
            "object_name": self.object_name,
            # A real date object, not .isoformat(): excel_gen.py needs it to
            # apply the DD.MM.YYYY cell format (a string would just print
            # literally, e.g. "2026-09-18" instead of "18.09.2026"). FastAPI
            # still serializes this to an ISO string in JSON responses fine.
            "date": self.zayavka_date,
            "from_whom": self.from_whom,
            "to_whom": self.to_whom,
            "payment_type": self.payment_type,
            "inspector": self.inspector,
            "cashier": self.cashier,
            "tech_supervisor": self.tech_supervisor,
            "created_by_tg_id": self.created_by_tg_id,
            "created_by_name": self.created_by_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "items": [item.to_dict() for item in self.items],
        }


class ZayavkaItem(Base):
    """
    One row of the goods/works table inside a Zayavka.
    Columns follow the spec 1-13 exactly.
    """
    __tablename__ = "zayavka_items"

    id = Column(Integer, primary_key=True, index=True)
    zayavka_id = Column(Integer, ForeignKey("zayavkalar.id"), nullable=False, index=True)

    row_no = Column(Integer, nullable=False)                # 1  т/р
    product_name = Column(String(500), nullable=True)       # 2  Наименование товара
    supplier = Column(String(255), nullable=True)            # 3  Поставщик
    block = Column(String(100), nullable=True)                # 4  Блок
    floor = Column(String(100), nullable=True)                # 5  Этаж
    unit = Column(String(50), nullable=True)                  # 6  Ед.изм
    qty = Column(Float, nullable=True)                        # 7  Кол-во
    price = Column(Float, nullable=True)                      # 8  Цена
    total = Column(Float, nullable=True)                      # 9  Общая сумма = Кол-во*Цена
    advance = Column(Float, nullable=True)                    # 10 Аванс получил
    remainder = Column(Float, nullable=True)                  # 11 Остатка
    work_type = Column(String(500), nullable=True)            # 12 Выполняемая работа (сметная группа)
    comment = Column(Text, nullable=True)                      # 13 Комментарие

    zayavka = relationship("Zayavka", back_populates="items")

    def to_dict(self):
        return {
            "row_no": self.row_no,
            "product_name": self.product_name,
            "supplier": self.supplier,
            "block": self.block,
            "floor": self.floor,
            "unit": self.unit,
            "qty": self.qty,
            "price": self.price,
            "total": self.total,
            "advance": self.advance,
            "remainder": self.remainder,
            "work_type": self.work_type,
            "comment": self.comment,
        }


class ZayavkaVersion(Base):
    """
    One saved state of a zayavka - a new row is written every time the form
    is saved (first save = version 1, each later edit = the next number), so
    the Excel that was sent to Telegram at that moment can be rebuilt exactly
    as it was, even after later edits changed the live record.
    """
    __tablename__ = "zayavka_versions"
    __table_args__ = (UniqueConstraint("zayavka_id", "version_no", name="uq_zayavka_versions_no"),)

    id = Column(Integer, primary_key=True, index=True)
    zayavka_id = Column(Integer, ForeignKey("zayavkalar.id"), nullable=False, index=True)
    version_no = Column(Integer, nullable=False)
    action = Column(String(20), nullable=False)          # "created" | "updated"
    saved_by = Column(String(255), nullable=True)         # Telegram name of who saved it
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    snapshot = Column(Text, nullable=False)               # JSON of Zayavka.to_dict()

    zayavka = relationship("Zayavka", back_populates="versions")

    def data(self) -> dict:
        """The snapshot as a zayavka dict, ready for excel_gen (date is a real date again)."""
        d = json.loads(self.snapshot)
        d["date"] = date.fromisoformat(d["date"])
        return d

    def summary(self) -> dict:
        items = json.loads(self.snapshot).get("items", [])
        return {
            "version_no": self.version_no,
            "action": self.action,
            "saved_by": self.saved_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "rows": len(items),
            "total": sum((i.get("total") or 0) for i in items),
            "advance": sum((i.get("advance") or 0) for i in items),
            "remainder": sum((i.get("remainder") or 0) for i in items),
        }


# What an admin can switch on or off per user (AppUser column -> default for a new
# user). "can_export" is the "download an Excel file" permission (kept under its
# original column name). Admins have all of them regardless.
PERMISSION_DEFAULTS = {
    "can_view": True,              # read forms of the persons the user is linked to
    "can_view_others": False,      # read forms filed by other appliers (persons)
    "can_view_all_objects": True,  # read/fill forms of building projects beyond the user's own list
    "can_create": True,            # fill a new form
    "can_edit": True,              # change a submitted form
    "can_delete": True,            # delete a form
    "can_export": True,            # download / send a form's Excel file
    "can_report": True,            # send the filtered Excel report to the channel
    "can_manage_lists": True,      # delete entries of the supplier / unit / work-type / name lists
    "can_manage_users": False,     # add and manage users (limited to what the user may grant)
}
PERMISSION_KEYS = tuple(PERMISSION_DEFAULTS)


class AppUser(Base):
    """
    Someone who uses the app, and what the admin allows them.

    status: "invited"  - added by phone number; waits until that person shares
                         their phone with the bot (then it becomes "approved")
            "pending"  - asked for access, waiting for the admin
            "approved" - may work with the persons/objects listed below
            "blocked"  - removed / rejected (stays blocked until the admin restores them)
    role:   "user" or "admin" (an approved "admin" may do everything, like the
            ADMIN_IDS owners in .env, who have no row here).
    People who are already members of a person's Telegram chat are approved
    automatically the first time they open the app (source="channel"); anyone
    else becomes a pending request (source="request") or is added by an admin
    (source="admin", by phone or Telegram id).
    """
    __tablename__ = "app_users"

    id = Column(Integer, primary_key=True, index=True)
    # NULL until an invited person confirms their phone number in the bot.
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=True)
    phone = Column(String(20), index=True, nullable=True)   # digits only, e.g. 998901234567
    name = Column(String(255), nullable=False, default="")
    username = Column(String(255), nullable=True)
    role = Column(String(10), nullable=False, default="user", server_default="user")
    status = Column(String(20), nullable=False, default="pending")
    source = Column(String(20), nullable=False, default="request")
    # The "От кого" persons this user may work with (JSON list of names).
    persons_json = Column(Text, nullable=False, default="[]")
    # Building projects (Название объекта) this user is limited to - used only
    # while can_view_all_objects is off.
    objects_json = Column(Text, nullable=False, default="[]", server_default="[]")
    can_view = Column(Boolean, nullable=False, default=True, server_default="1")
    can_view_others = Column(Boolean, nullable=False, default=False, server_default="0")
    can_view_all_objects = Column(Boolean, nullable=False, default=True, server_default="1")
    can_create = Column(Boolean, nullable=False, default=True, server_default="1")
    can_edit = Column(Boolean, nullable=False, default=True)
    can_delete = Column(Boolean, nullable=False, default=True)
    can_export = Column(Boolean, nullable=False, default=True)
    can_report = Column(Boolean, nullable=False, default=True, server_default="1")
    can_manage_lists = Column(Boolean, nullable=False, default=True, server_default="1")
    can_manage_users = Column(Boolean, nullable=False, default=False, server_default="0")
    requested_person = Column(String(255), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String(255), nullable=True)
    last_seen_at = Column(DateTime, nullable=True)   # last time they opened the app (UTC)

    @staticmethod
    def _load_list(raw) -> list:
        try:
            value = json.loads(raw or "[]")
            return [str(p) for p in value] if isinstance(value, list) else []
        except ValueError:
            return []

    @property
    def persons(self) -> list:
        return self._load_list(self.persons_json)

    @persons.setter
    def persons(self, value) -> None:
        self.persons_json = json.dumps(sorted(set(value)), ensure_ascii=False)

    @property
    def objects(self) -> list:
        return self._load_list(self.objects_json)

    @objects.setter
    def objects(self, value) -> None:
        self.objects_json = json.dumps(sorted(set(value)), ensure_ascii=False)

    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "telegram_id": self.telegram_id,
            "phone": self.phone,
            "name": self.name,
            "username": self.username,
            "role": self.role or "user",
            "status": self.status,
            "source": self.source,
            "persons": self.persons,
            "objects": self.objects,
            "requested_person": self.requested_person,
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "approved_by": self.approved_by,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
        }
        for key in PERMISSION_KEYS:
            data[key] = bool(getattr(self, key))
        return data


class BotMenuMessage(Base):
    """
    A message the bot sent that carries a Mini App (web_app) button. The
    button's address is baked into the message when it's sent, and the free
    Cloudflare tunnel address changes on every restart - so those buttons go
    dead. Remembering these messages lets the bot re-point their buttons to
    the current address on every start (see _heal_menu_messages in bot.py).
    """
    __tablename__ = "bot_menu_messages"
    __table_args__ = (UniqueConstraint("chat_id", "message_id", name="uq_bot_menu_messages"),)

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    message_id = Column(Integer, nullable=False)
    kind = Column(String(20), nullable=False)  # "menu" | "jadval"
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class NameOption(Base):
    """
    Growable dropdown/autocomplete options: the approval/signature block
    (Инспектор, Кассир, Техданзор) - "combo box" values - plus Поставщик,
    which is free-text on the item row but still remembered here so the
    same supplier's name stays consistent across zayavkas. Starts empty;
    typing a new name once saves it here so it's a pickable/suggested
    option for everyone afterwards.
    """
    __tablename__ = "name_options"
    __table_args__ = (UniqueConstraint("category", "name", name="uq_name_options_category_name"),)

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(50), nullable=False)  # "inspector" | "cashier" | "tech_supervisor" | "supplier"
    name = Column(String(255), nullable=False)
