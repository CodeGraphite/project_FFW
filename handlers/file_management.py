from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from database import Database
from services import GoogleDriveService

router = Router()


def _is_admin(user_id: int, admin_ids: set[int]) -> bool:
    return user_id in admin_ids


def _parse_int_arg(message: Message, index: int) -> int | None:
    parts = (message.text or "").split()
    if len(parts) <= index:
        return None
    try:
        return int(parts[index])
    except (TypeError, ValueError):
        return None


async def _deny_if_not_admin(message: Message, admin_ids: set[int]) -> bool:
    if message.from_user and _is_admin(message.from_user.id, admin_ids):
        return False
    if not admin_ids:
        await message.answer("Admin commands are disabled: ADMIN_IDS is empty in config.")
    else:
        await message.answer("Access denied. Your Telegram ID is not in ADMIN_IDS.")
    return True


@router.message(Command("delete_old"))
async def delete_old_cmd(message: Message, db: Database, drive: GoogleDriveService, admin_ids: set[int]) -> None:
    if await _deny_if_not_admin(message, admin_ids):
        return
    rows = db.files_older_than_24h()
    deleted = 0
    for r in rows:
        try:
            drive.delete_file(r["google_file_id"])
        except Exception:
            continue
        db.delete_file_record(r["id"])
        deleted += 1
    await message.answer(f"Deleted old files: {deleted}")


@router.message(Command("delete_user_files"))
async def delete_user_files_cmd(message: Message, db: Database, drive: GoogleDriveService, admin_ids: set[int]) -> None:
    if await _deny_if_not_admin(message, admin_ids):
        return
    telegram_id = _parse_int_arg(message, 1)
    if telegram_id is None:
        await message.answer("Usage: /delete_user_files [telegram_id]")
        return
    files = db.delete_files_for_user(telegram_id)
    deleted = 0
    for row in files:
        try:
            drive.delete_file(row["google_file_id"])
            deleted += 1
        except Exception:
            pass
    await message.answer(f"Deleted files for user {telegram_id}: {deleted}")


@router.message(Command("delete_file"))
async def delete_file_cmd(message: Message, db: Database, drive: GoogleDriveService, admin_ids: set[int]) -> None:
    if await _deny_if_not_admin(message, admin_ids):
        return
    file_id = _parse_int_arg(message, 1)
    if file_id is None:
        await message.answer("Usage: /delete_file [file_id]")
        return
    row = db.delete_file_record(file_id)
    if not row:
        await message.answer("File not found in database.")
        return
    try:
        drive.delete_file(row["google_file_id"])
    except Exception:
        await message.answer("File record removed, but Google Drive deletion failed.")
        return
    await message.answer(f"Deleted file #{file_id}")
