"""
Generates the "Номер заявки" code:

    day-month-MM-object_letter-from_letter

where day/month come from the zayavka's date, MM is a two-digit minute
(00-59) fixed once when the form is first opened (so it can be shown and
printed before saving), and the letters are the first letters of
Название объекта and От кого.

Example: object "Янги Шодиёна", from "Курбонов Равшан", date 19.09.2026,
form opened at 09:10  ->  "19-9-10-Я-К"

The code is generated exactly once, when the zayavka is created, and stored.
Editing a zayavka (new versions) never regenerates it - see
update_zayavka_record in app/services.py - so the MM part never changes.
"""
from datetime import date, datetime
from typing import Optional


def _first_letter(text: str) -> str:
    text = (text or "").strip()
    return text[0].upper() if text else "X"


def generate_number(
    object_name: str,
    from_whom: str,
    zayavka_date: date,
    now: Optional[datetime] = None,
    minute: Optional[int] = None,
) -> str:
    """
    `minute` (0-59) is the minute the Mini App form fixed when it was opened
    and sent along with the first save, so the number the user sees - and
    prints - before saving is exactly the one that gets stored. Without it
    (or if it's out of range) the current minute is used.
    """
    now = now or datetime.now()
    day = str(zayavka_date.day)
    month = str(zayavka_date.month)
    if minute is None or not 0 <= minute <= 59:
        minute = now.minute
    minute = str(minute).zfill(2)
    obj_letter = _first_letter(object_name)
    from_letter = _first_letter(from_whom)
    return f"{day}-{month}-{minute}-{obj_letter}-{from_letter}"
