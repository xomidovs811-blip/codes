"""
Shared "generate the Excel + send it on Telegram" logic.

Used by app/api.py's /api/zayavka endpoint, which is now the ONLY save path:
Telegram's WebApp.sendData() only works for Mini Apps launched via a Reply
Keyboard button, not the inline "Web App" button this project uses (see
https://core.telegram.org/bots/webapps - "only available for Mini Apps
launched via a Keyboard button"), so items.html posts straight to the API
instead of sending data back through the bot process.
"""
import logging
import os
import tempfile
from typing import Optional

from aiogram import Bot
from aiogram.types import FSInputFile

from app.config import ALLOWED_GROUP_IDS, PERSON_ROUTES, POST_UNROUTED_TO_DEFAULT
from app.excel_gen import save_workbook
from app.models import Zayavka

logger = logging.getLogger("zayavka-notify")


def build_caption_from_dict(d: dict, header: str) -> str:
    # "Сумма заявки" = Ostatka in the form = sum of each row's
    # (Общая сумма - Аванс получил), same total shown live in the
    # Mini App's totals bar.
    summa_zayavki = sum((item.get("remainder") or 0) for item in d["items"])
    summa_str = f"{summa_zayavki:,.0f}".replace(",", " ")
    return (
        f"{header}\n\n"
        f"<b>Номер заявки:</b> {d['number']}\n"
        f"<b>Obyekt:</b> {d['object_name']}\n"
        f"<b>Sana:</b> {d['date'].strftime('%d.%m.%Y')}\n"
        f"<b>От кого:</b> {d['from_whom']}\n"
        f"<b>Сумма заявки:</b> {summa_str}"
    )


def build_caption(zayavka: Zayavka, updated: bool = False, header: Optional[str] = None) -> str:
    if header is None:
        header = "✏️ Zayavka yangilandi!" if updated else "✅ Zayavka yuborildi!"
    return build_caption_from_dict(zayavka.to_dict(), header)


async def send_dict_to_chat(bot: Bot, d: dict, chat_id: int, header: str) -> bool:
    """
    Builds the .xlsx for a zayavka dict (a live record's to_dict() or a
    saved version's snapshot) and sends it to ONE chat only - unlike
    send_zayavka_document it never broadcasts to the group/PERSON_ROUTES
    chats, so re-sending doesn't spam everyone. Returns whether Telegram
    accepted it.
    """
    tmp_dir = tempfile.mkdtemp(prefix="zayavka_")
    tmp_path = None
    try:
        tmp_path = save_workbook(d, tmp_dir)
        await bot.send_document(
            chat_id,
            FSInputFile(tmp_path),
            caption=build_caption_from_dict(d, header),
            parse_mode="HTML",
        )
        return True
    except Exception:
        logger.exception("Failed to re-send zayavka document to chat %s", chat_id)
        return False
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
                os.rmdir(os.path.dirname(tmp_path))
            except OSError:
                pass


async def send_report_file(bot: Bot, path: str, caption: str, chat_ids: list) -> int:
    """Sends an already-built report .xlsx to each chat; returns how many accepted it."""
    sent = 0
    for chat_id in chat_ids:
        try:
            await bot.send_document(
                chat_id, FSInputFile(path), caption=caption, parse_mode="HTML"
            )
            sent += 1
        except Exception:
            logger.exception("Failed to send report to chat %s", chat_id)
    return sent


async def send_zayavka_to_chat(bot: Bot, zayavka: Zayavka, chat_id: int) -> bool:
    return await send_dict_to_chat(bot, zayavka.to_dict(), chat_id, "📄 Zayavka Excel")


async def send_zayavka_document(
    bot: Bot, zayavka: Zayavka, notify_chat_id: Optional[int], updated: bool = False
) -> None:
    """
    Builds the .xlsx for `zayavka`, sends it to `notify_chat_id` (the
    private chat with whoever submitted it, if known), then broadcasts it to
    that person's PERSON_ROUTES chat (if "От кого" matches one). A person with
    no chat is NOT posted to the shared channel (unless POST_UNROUTED_TO_DEFAULT
    is set) - a form must never appear in a channel that isn't its applier's.
    """
    tmp_dir = tempfile.mkdtemp(prefix="zayavka_")
    tmp_path = None
    try:
        tmp_path = save_workbook(zayavka.to_dict(), tmp_dir)
        caption = build_caption(zayavka, updated=updated)

        if notify_chat_id:
            try:
                await bot.send_document(
                    notify_chat_id, FSInputFile(tmp_path), caption=caption, parse_mode="HTML"
                )
            except Exception:
                logger.exception("Failed to send zayavka document to submitter %s", notify_chat_id)

        person_chat_id = PERSON_ROUTES.get(zayavka.from_whom)
        if person_chat_id:
            broadcast_chat_ids = [person_chat_id]
        elif POST_UNROUTED_TO_DEFAULT:
            broadcast_chat_ids = ALLOWED_GROUP_IDS
        else:
            broadcast_chat_ids = []
            logger.warning(
                "No channel is linked to %r - the Excel was sent only to the person who saved it",
                zayavka.from_whom,
            )

        for chat_id in broadcast_chat_ids:
            if chat_id == notify_chat_id:
                continue  # already sent above
            try:
                await bot.send_document(
                    chat_id, FSInputFile(tmp_path), caption=caption, parse_mode="HTML"
                )
            except Exception:
                logger.exception("Failed to post zayavka document to chat %s", chat_id)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
                os.rmdir(os.path.dirname(tmp_path))
            except OSError:
                pass
