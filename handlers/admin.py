from __future__ import annotations

import re
import logging
import sqlite3

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from database import Database, parse_size_to_bytes
from keyboards import admin_menu_keyboard
from utils import format_bytes

router = Router()
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
logger = logging.getLogger(__name__)


def _is_admin(user_id: int, admin_ids: set[int]) -> bool:
    return user_id in admin_ids


def _parse_int_arg(message: Message, index: int, usage: str) -> int | None:
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
        await message.answer("Admin panel is disabled: ADMIN_IDS is empty in config.")
    else:
        await message.answer("Access denied. Your Telegram ID is not in ADMIN_IDS.")
    return True


@router.message(F.text.regexp(r"(?i)^\s*/admin(@[A-Za-z0-9_]+)?\s*$"))
async def admin_panel(message: Message, admin_ids: set[int]) -> None:
    logger.info("admin_panel called for user_id=%s", getattr(message.from_user, "id", None))
    if await _deny_if_not_admin(message, admin_ids):
        return
    await message.answer("Admin panel:", reply_markup=admin_menu_keyboard())


# Fallback handler: match any message that starts with "/admin" (extra safety).
@router.message(F.text.regexp(r"(?i)^\s*/admin(?:@[A-Za-z0-9_]+)?\s*.*$"))
async def admin_panel_fallback(message: Message, admin_ids: set[int]) -> None:
    if message.text and message.text.strip().split()[0].lower().startswith("/admin"):
        logger.warning("admin_panel_fallback called text=%r", message.text)
        if await _deny_if_not_admin(message, admin_ids):
            return
        await message.answer("Admin panel:", reply_markup=admin_menu_keyboard())


@router.callback_query(F.data.startswith("admin:"))
async def admin_panel_callbacks(callback: CallbackQuery, db: Database, admin_ids: set[int]) -> None:
    if not callback.from_user or not _is_admin(callback.from_user.id, admin_ids):
        await callback.answer("Forbidden", show_alert=True)
        return
    action = callback.data.removeprefix("admin:")
    if action == "stats":
        s = db.stats()
        await callback.message.answer(
            "Statistics:\n"
            f"Total users: {s['total_users']}\n"
            f"Total files: {s['total_files']}\n"
            f"Queue size: {s['queue_size']}\n"
            f"Total storage: {format_bytes(s['total_storage'])}\n"
            f"Active downloads: {s['active_downloads']}"
        )
    elif action == "users":
        users = db.list_users(20)
        if not users:
            await callback.message.answer("No users yet.")
        else:
            text = ["Recent users:"]
            for u in users:
                text.append(
                    f"{u['telegram_id']} | used {format_bytes(u['used_storage'])}/{format_bytes(u['storage_limit'])} | "
                    f"banned={bool(u['is_banned'])} | verified={bool(u['is_verified'])}"
                )
            await callback.message.answer("\n".join(text))
    elif action == "storage":
        await callback.message.answer("Use /set_limit, /reset_limit and /user for storage details.")
    elif action == "quality":
        settings = db.get_settings()
        await callback.message.answer(
            "Quality settings:\n"
            f"Fixed quality: {settings['fixed_quality'] or 'None'}\n"
            f"Allowed: {', '.join(settings['allowed_qualities'])}\n"
            f"Disabled: {', '.join(settings['disabled_qualities']) or 'None'}"
        )
    elif action == "files":
        await callback.message.answer("Use /delete_old, /delete_user_files [id], /delete_file [file_id].")
    elif action == "settings":
        await callback.message.answer("Core settings are currently managed via .env and commands.")
    else:
        await callback.answer("Unknown admin action.", show_alert=True)
        return
    await callback.answer()


@router.message(Command("users"))
async def users_cmd(message: Message, db: Database, admin_ids: set[int]) -> None:
    if await _deny_if_not_admin(message, admin_ids):
        return
    users = db.list_users(50)
    if not users:
        await message.answer("No users yet.")
        return
    lines = ["Users:"]
    for u in users:
        lines.append(
            f"{u['telegram_id']} | used {format_bytes(u['used_storage'])}/{format_bytes(u['storage_limit'])} | "
            f"admin={bool(u['is_admin'])} | banned={bool(u['is_banned'])} | verified={bool(u['is_verified'])} | email={u['email'] or '-'}"
        )
    await message.answer("\n".join(lines))


@router.message(Command("user"))
async def user_cmd(message: Message, db: Database, admin_ids: set[int]) -> None:
    if await _deny_if_not_admin(message, admin_ids):
        return
    telegram_id = _parse_int_arg(message, 1, "/user [telegram_id]")
    if telegram_id is None:
        await message.answer("Usage: /user [telegram_id]")
        return
    user = db.get_user_by_telegram_id(telegram_id)
    if not user:
        await message.answer("User not found.")
        return
    await message.answer(
        f"User {user['telegram_id']}\n"
        f"Email: {user['email'] or '-'}\n"
        f"Verified: {bool(user['is_verified'])}\n"
        f"Storage: {format_bytes(user['used_storage'])}/{format_bytes(user['storage_limit'])}\n"
        f"Status: {'banned' if user['is_banned'] else 'active'}\n"
        f"Admin: {bool(user['is_admin'])}"
    )


@router.message(Command("set_limit"))
async def set_limit_cmd(message: Message, db: Database, admin_ids: set[int]) -> None:
    if await _deny_if_not_admin(message, admin_ids):
        return
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer("Usage: /set_limit [telegram_id] [10GB]")
        return
    telegram_id = _parse_int_arg(message, 1, "/set_limit [telegram_id] [10GB]")
    if telegram_id is None:
        await message.answer("Telegram ID must be a number.")
        return
    try:
        size = parse_size_to_bytes(parts[2])
    except (TypeError, ValueError):
        await message.answer("Invalid size. Example: `10GB` or `500MB`.", parse_mode="Markdown")
        return
    db.set_user_limit(telegram_id, size)
    await message.answer(f"Storage limit for {telegram_id} set to {format_bytes(size)}.")


@router.message(Command("reset_limit"))
async def reset_limit_cmd(message: Message, db: Database, admin_ids: set[int]) -> None:
    if await _deny_if_not_admin(message, admin_ids):
        return
    telegram_id = _parse_int_arg(message, 1, "/reset_limit [telegram_id]")
    if telegram_id is None:
        await message.answer("Usage: /reset_limit [telegram_id]")
        return
    db.reset_user_limit(telegram_id)
    await message.answer(f"Storage limit reset for {telegram_id}.")


@router.message(Command("ban"))
async def ban_cmd(message: Message, db: Database, admin_ids: set[int]) -> None:
    if await _deny_if_not_admin(message, admin_ids):
        return
    telegram_id = _parse_int_arg(message, 1, "/ban [telegram_id]")
    if telegram_id is None:
        await message.answer("Usage: /ban [telegram_id]")
        return
    db.ban_user(telegram_id, True)
    await message.answer(f"User {telegram_id} banned.")


@router.message(Command("unban"))
async def unban_cmd(message: Message, db: Database, admin_ids: set[int]) -> None:
    if await _deny_if_not_admin(message, admin_ids):
        return
    telegram_id = _parse_int_arg(message, 1, "/unban [telegram_id]")
    if telegram_id is None:
        await message.answer("Usage: /unban [telegram_id]")
        return
    db.ban_user(telegram_id, False)
    await message.answer(f"User {telegram_id} unbanned.")


@router.message(Command("set_quality"))
async def set_quality_cmd(message: Message, db: Database, admin_ids: set[int]) -> None:
    if await _deny_if_not_admin(message, admin_ids):
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Usage: /set_quality [720p]")
        return
    db.set_fixed_quality(parts[1])
    await message.answer(f"Fixed quality set to {parts[1]}.")


@router.message(Command("reset_quality"))
async def reset_quality_cmd(message: Message, db: Database, admin_ids: set[int]) -> None:
    if await _deny_if_not_admin(message, admin_ids):
        return
    db.set_fixed_quality(None)
    await message.answer("Fixed quality reset. Users can choose quality.")


@router.message(Command("disable_quality"))
async def disable_quality_cmd(message: Message, db: Database, admin_ids: set[int]) -> None:
    if await _deny_if_not_admin(message, admin_ids):
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Usage: /disable_quality [1080p]")
        return
    db.disable_quality(parts[1])
    await message.answer(f"Quality disabled: {parts[1]}")


@router.message(Command("enable_quality"))
async def enable_quality_cmd(message: Message, db: Database, admin_ids: set[int]) -> None:
    if await _deny_if_not_admin(message, admin_ids):
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Usage: /enable_quality [1080p]")
        return
    db.enable_quality(parts[1])
    await message.answer(f"Quality enabled: {parts[1]}")


@router.message(Command("quality_status"))
async def quality_status_cmd(message: Message, db: Database, admin_ids: set[int]) -> None:
    if await _deny_if_not_admin(message, admin_ids):
        return
    settings = db.get_settings()
    await message.answer(
        "Quality status:\n"
        f"Fixed: {settings['fixed_quality'] or 'None'}\n"
        f"Allowed: {', '.join(settings['allowed_qualities'])}\n"
        f"Disabled: {', '.join(settings['disabled_qualities']) or 'None'}"
    )


@router.message(Command("set_email"))
async def set_email_cmd(message: Message, db: Database, admin_ids: set[int]) -> None:
    if await _deny_if_not_admin(message, admin_ids):
        return
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer("Usage: /set_email [telegram_id] [email]")
        return
    telegram_id = _parse_int_arg(message, 1, "/set_email [telegram_id] [email]")
    if telegram_id is None:
        await message.answer("Telegram ID must be a number.")
        return
    email = parts[2].strip().lower()
    if not EMAIL_RE.fullmatch(email):
        await message.answer("Invalid email format.")
        return
    existing = db.get_user_by_email(email)
    if existing and existing["telegram_id"] != telegram_id:
        await message.answer("This email is already assigned to another Telegram account.")
        return
    try:
        db.set_user_email(telegram_id, email)
    except sqlite3.IntegrityError:
        await message.answer("Could not assign email (already used).")
        return
    await message.answer(f"Email for {telegram_id} set to {email}.")


@router.message(Command("reset_email"))
async def reset_email_cmd(message: Message, db: Database, admin_ids: set[int]) -> None:
    if await _deny_if_not_admin(message, admin_ids):
        return
    telegram_id = _parse_int_arg(message, 1, "/reset_email [telegram_id]")
    if telegram_id is None:
        await message.answer("Usage: /reset_email [telegram_id]")
        return
    db.reset_user_email(telegram_id)
    await message.answer(f"Email reset for {telegram_id}. User must sign up again.")
