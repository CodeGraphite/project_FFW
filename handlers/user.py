from __future__ import annotations

import re
import sqlite3

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import Database
from keyboards import quality_keyboard
from services import GoogleDriveService, get_quality_menu_options
from states import UploadState
from utils import format_bytes, is_youtube_url

router = Router()
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
MAX_SIGNUP_PASSWORD_ATTEMPTS = 3


def _allowed_for_user(db: Database) -> tuple[list[str], str | None]:
    settings = db.get_settings()
    fixed_quality = settings["fixed_quality"]
    allowed = settings["allowed_qualities"]
    disabled = set(settings["disabled_qualities"])
    final = [q for q in allowed if q not in disabled]
    return final, fixed_quality


def _is_verified(user) -> bool:
    return bool(user and user["is_verified"])


@router.message(Command("start"))
async def start_cmd(message: Message, db: Database, admin_ids: set[int]) -> None:
    user = db.ensure_user(message.from_user.id, is_admin=message.from_user.id in admin_ids)
    if user["is_banned"]:
        await message.answer("Your account is banned.")
        return
    if not user["is_verified"]:
        await message.answer(
            "Before using the bot, you must sign up.\n"
            "Use /signup and provide:\n"
            "- email\n"
            "- password"
        )
        return
    await message.answer("Video bot is ready. Send a Telegram video file or YouTube link.")


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer(
        "/start\n/signup\n/my_folder\n/upload\n/history\n/help\n\n"
        "Admins:\n/admin\n/users\n/user [telegram_id]\n/set_limit [telegram_id] [10GB]\n"
        "/reset_limit [telegram_id]\n/ban [telegram_id]\n/unban [telegram_id]\n"
        "/set_quality [720p]\n/reset_quality\n/disable_quality [1080p]\n"
        "/enable_quality [1080p]\n/quality_status\n/set_email [telegram_id] [email]\n"
        "/reset_email [telegram_id]\n/delete_old\n/delete_user_files [telegram_id]\n/delete_file [file_id]"
    )


@router.message(Command("signup"))
async def signup_cmd(message: Message, db: Database, state: FSMContext) -> None:
    user = db.get_user_by_telegram_id(message.from_user.id) or db.ensure_user(message.from_user.id)
    if user["is_verified"]:
        await message.answer("You are already signed up.")
        return
    await state.set_state(UploadState.signup_email)
    await message.answer("Send your email address.")


@router.message(Command("my_folder"))
async def my_folder_cmd(message: Message, db: Database) -> None:
    user = db.get_user_by_telegram_id(message.from_user.id) or db.ensure_user(message.from_user.id)
    if not _is_verified(user):
        await message.answer("Please complete signup first via /signup.")
        return
    if not user["drive_folder_id"]:
        await message.answer("No folder is linked yet. Complete /signup again or contact admin.")
        return
    await message.answer(f"Your Google Drive folder:\nhttps://drive.google.com/drive/folders/{user['drive_folder_id']}")


@router.message(UploadState.signup_email)
async def signup_email_step(message: Message, db: Database, state: FSMContext) -> None:
    email = (message.text or "").strip().lower()
    if not EMAIL_RE.fullmatch(email):
        await message.answer("Invalid email. Please send a valid email.")
        return
    existing = db.get_user_by_email(email)
    if existing and existing["telegram_id"] != message.from_user.id:
        await state.clear()
        await message.answer("This email is already used by another Telegram account.")
        return
    await state.update_data(email=email)
    await state.set_state(UploadState.signup_password)
    await message.answer("Send your password")


@router.message(UploadState.signup_password)
async def signup_password_step(message: Message, db: Database, drive: GoogleDriveService, state: FSMContext) -> None:
    data = await state.get_data()
    email = data.get("email")
    if not email:
        await state.clear()
        await message.answer("Signup session expired. Use /signup again.")
        return
    password = (message.text or "").strip()
    expected_password = f"{email}BIGO"
    if password != expected_password:
        attempts = int(data.get("signup_password_attempts", 0)) + 1
        if attempts >= MAX_SIGNUP_PASSWORD_ATTEMPTS:
            await state.clear()
            await message.answer("Too many failed attempts. Signup cancelled. Use /signup to restart.")
            return
        await state.update_data(signup_password_attempts=attempts)
        left = MAX_SIGNUP_PASSWORD_ATTEMPTS - attempts
        await message.answer(
            "Invalid password format\n"
            f"Attempts left: {left}"
        )
        return
    try:
        folder_id = drive.ensure_user_folder(message.from_user.id)
        drive.share_folder_reader(folder_id=folder_id, email=email)
        db.set_user_signup(message.from_user.id, email=email, drive_folder_id=folder_id)
    except RuntimeError as exc:
        await state.clear()
        await message.answer(f"Could not complete Google Drive setup: {exc}")
        return
    except sqlite3.IntegrityError:
        await state.clear()
        await message.answer("This email is already assigned to another account.")
        return
    await state.clear()
    await message.answer(
        "Signup completed.\n"
        f"Your folder access is granted (reader): {drive.folder_link(folder_id)}"
    )


@router.message(Command("upload"))
async def upload_cmd(message: Message, db: Database) -> None:
    user = db.get_user_by_telegram_id(message.from_user.id) or db.ensure_user(message.from_user.id)
    if not _is_verified(user):
        await message.answer("Please complete signup first via /signup.")
        return
    await message.answer("Send a Telegram video or a YouTube URL. The bot will queue and upload it to Google Drive.")


@router.message(Command("history"))
async def history_cmd(message: Message, db: Database) -> None:
    user = db.get_user_by_telegram_id(message.from_user.id) or db.ensure_user(message.from_user.id)
    if not _is_verified(user):
        await message.answer("Please complete signup first via /signup.")
        return
    rows = db.history_for_user(message.from_user.id)
    if not rows:
        await message.answer("No upload history yet.")
        return
    text = ["Recent files:"]
    for r in rows:
        text.append(f"#{r['id']} | {r['google_file_name']} | {format_bytes(r['file_size'])}")
    await message.answer("\n".join(text))


@router.message(F.video)
async def handle_telegram_video(message: Message, db: Database) -> None:
    user = db.get_user_by_telegram_id(message.from_user.id) or db.ensure_user(message.from_user.id)
    if not _is_verified(user):
        await message.answer("Please complete signup first via /signup.")
        return
    if user["is_banned"]:
        await message.answer("Your account is banned.")
        return
    video = message.video
    size = int(video.file_size or 0)
    if size > 4 * 1024 * 1024 * 1024:
        await message.answer("File exceeds 4GB Telegram processing limit.")
        return
    if not db.can_user_store(message.from_user.id, size):
        await message.answer("Storage limit exceeded. Contact admin for more space.")
        return
    video_id = db.create_video_and_queue_task(
        telegram_id=message.from_user.id,
        source="telegram",
        telegram_file_id=video.file_id,
        telegram_file_name=video.file_name or f"{video.file_unique_id}.mp4",
        telegram_file_size=size,
    )
    await message.answer(f"Added to queue. Task #{video_id}")


# Ignore Telegram slash-commands so admin commands like `/admin` don't get swallowed
# by this generic "maybe it's a YouTube link" handler.
@router.message(F.text.regexp(r"^\s*(?!/).+"))
async def handle_youtube_link(message: Message, db: Database, state: FSMContext) -> None:
    text = (message.text or "").strip()
    # Extra safety: if it still looks like a command, don't interfere with command handlers.
    if text.startswith("/"):
        return
    if not is_youtube_url(text):
        return
    user = db.get_user_by_telegram_id(message.from_user.id) or db.ensure_user(message.from_user.id)
    if user["is_banned"]:
        await message.answer("Your account is banned.")
        return
    if not _is_verified(user):
        await message.answer("Please complete signup first via /signup.")
        return
    qualities, fixed_quality = _allowed_for_user(db)
    if fixed_quality:
        video_id = db.create_video_and_queue_task(
            telegram_id=message.from_user.id,
            source="youtube",
            youtube_url=text,
            quality=fixed_quality,
        )
        await message.answer(f"Added to queue with fixed quality {fixed_quality}. Task #{video_id}")
        return
    if not qualities:
        await message.answer("No qualities enabled by admin currently.")
        return
    await state.set_state(UploadState.waiting_for_quality)
    await state.update_data(youtube_url=text)
    try:
        quality_options = await asyncio.to_thread(get_quality_menu_options, text, qualities)
    except Exception:
        quality_options = [(quality, quality) for quality in qualities]
    await message.answer("Select quality:", reply_markup=quality_keyboard(quality_options))


@router.callback_query(UploadState.waiting_for_quality, F.data.startswith("quality:"))
async def quality_selected(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    quality = callback.data.split(":", 1)[1]
    payload = await state.get_data()
    url = payload.get("youtube_url")
    if not url:
        await callback.answer("Session expired.", show_alert=True)
        return
    video_id = db.create_video_and_queue_task(
        telegram_id=callback.from_user.id,
        source="youtube",
        youtube_url=url,
        quality=quality,
    )
    await state.clear()
    await callback.message.edit_text(f"Added to queue with {quality}. Task #{video_id}")
    await callback.answer()
