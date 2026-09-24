from datetime import date
from typing import Optional, List

from pydantic import BaseModel, Field


class ItemIn(BaseModel):
    row_no: int
    product_name: Optional[str] = None
    supplier: Optional[str] = None
    block: Optional[str] = None
    floor: Optional[str] = None
    unit: Optional[str] = None
    qty: Optional[float] = None
    price: Optional[float] = None
    advance: Optional[float] = None
    remainder: Optional[float] = None
    work_type: Optional[str] = None
    comment: Optional[str] = None


class ZayavkaIn(BaseModel):
    object_name: str
    date: date
    from_whom: str
    to_whom: Optional[str] = None
    payment_type: Optional[str] = None
    inspector: Optional[str] = None
    cashier: Optional[str] = None
    tech_supervisor: Optional[str] = None
    items: List[ItemIn] = Field(default_factory=list)

    # Telegram WebApp init data, sent for server-side authentication.
    init_data: Optional[str] = None
    # Fallback identity fields (used only if init_data can't be validated,
    # e.g. during local testing without Telegram).
    tg_user_id: Optional[int] = None
    tg_user_name: Optional[str] = None
    # Two-digit minute (00-59) the form fixed when it was opened - used for
    # the middle part of the Номер заявки so the number shown/printed before
    # saving is the one stored (see app/code_gen.py). Invalid values are ignored.
    code_minute: Optional[str] = None


class SendToMeIn(BaseModel):
    # Telegram WebApp init data - the only accepted identity for this
    # endpoint (no tg_user_id fallback), since it makes the bot message
    # whoever is named.
    init_data: Optional[str] = None


class ExportIn(BaseModel):
    # Same criteria the table page filters by. init_data is required: the
    # export posts to the shared channel, so it must come from a real
    # Telegram user (no tg_user_id fallback).
    init_data: Optional[str] = None
    object_name: Optional[str] = None
    from_whom: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    created_by: Optional[int] = None


class PermsIn(BaseModel):
    """Every permission an admin can switch (None = not sent / leave as is)."""
    can_view: Optional[bool] = None
    can_view_others: Optional[bool] = None
    can_view_all_objects: Optional[bool] = None
    can_create: Optional[bool] = None
    can_edit: Optional[bool] = None
    can_delete: Optional[bool] = None
    can_export: Optional[bool] = None
    can_report: Optional[bool] = None
    can_manage_lists: Optional[bool] = None
    can_manage_users: Optional[bool] = None


class AdminUserIn(PermsIn):
    """Add a user or an admin: by phone number (they confirm it in the bot) or, if they can't, by Telegram id."""
    phone: Optional[str] = None
    telegram_id: Optional[int] = None
    name: Optional[str] = ""
    role: Optional[str] = "user"
    persons: List[str] = Field(default_factory=list)
    objects: List[str] = Field(default_factory=list)


class AdminUserPatch(PermsIn):
    """Admin changes a user; only the fields that are sent are changed."""
    name: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    persons: Optional[List[str]] = None
    objects: Optional[List[str]] = None


class AccessRequestIn(BaseModel):
    """
    A pending user asks for access - either a quick "Kirish" (just says which
    person, if they forgot the contact-share step) or a full "Ro'yxatdan
    o'tish" (registration: name + phone typed in, since they may not have
    used Telegram's own contact-share). The typed phone is NOT Telegram-
    verified, so it never auto-approves - it's shown to the admin like the
    other fields, for them to review and approve by hand.
    """
    name: Optional[str] = None
    phone: Optional[str] = None
    person: Optional[str] = None
    note: Optional[str] = None


class NameOptionIn(BaseModel):
    category: str
    name: str
