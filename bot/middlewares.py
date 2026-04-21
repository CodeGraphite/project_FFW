from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
import logging

from database import Database


logger = logging.getLogger(__name__)


class VerifiedUserMiddleware(BaseMiddleware):
    def __init__(self, allowed_commands: set[str] | None = None):
        admin_commands = {
            "/admin",
            "/users",
            "/user",
            "/set_limit",
            "/reset_limit",
            "/ban",
            "/unban",
            "/set_quality",
            "/reset_quality",
            "/disable_quality",
            "/enable_quality",
            "/quality_status",
            "/set_email",
            "/reset_email",
            "/delete_old",
            "/delete_user_files",
            "/delete_file",
        }
        self.allowed_commands = (allowed_commands or {"/start", "/signup", "/help"}) | admin_commands
        self.allowed_signup_states = {"UploadState:signup_email", "UploadState:signup_password"}

    @staticmethod
    def _is_admin(user_id: int, admin_ids: set[int] | None) -> bool:
        return bool(admin_ids and user_id in admin_ids)

    @staticmethod
    def _extract_command(message_text: str) -> str | None:
        if not message_text.startswith("/"):
            return None
        command = message_text.split()[0].split("@")[0].lower()
        return command

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        db: Database | None = data.get("db")
        admin_ids: set[int] = data.get("admin_ids", set())
        if not db:
            return await handler(event, data)

        if isinstance(event, Message):
            if not event.from_user:
                return await handler(event, data)
            user = db.get_user_by_telegram_id(event.from_user.id) or db.ensure_user(event.from_user.id)
            # If user is admin (according to DB or passed config), allow.
            if self._is_admin(event.from_user.id, admin_ids) or user["is_admin"]:
                return await handler(event, data)
            if user["is_verified"]:
                return await handler(event, data)
            fsm_state = data.get("state")
            if fsm_state:
                current_state = await fsm_state.get_state()
                if current_state in self.allowed_signup_states:
                    return await handler(event, data)
            command = self._extract_command(event.text or "")
            if command in self.allowed_commands:
                logger.info("Middleware allowed command=%s user_id=%s", command, event.from_user.id)
                return await handler(event, data)
            await event.answer("Please complete signup first via /signup.")
            return None

        if isinstance(event, CallbackQuery):
            if not event.from_user:
                return await handler(event, data)
            # Let admin menu callbacks through; admin callback handlers do final access checks.
            if (event.data or "").startswith("admin:"):
                return await handler(event, data)
            user = db.get_user_by_telegram_id(event.from_user.id) or db.ensure_user(event.from_user.id)
            if self._is_admin(event.from_user.id, admin_ids) or user["is_admin"]:
                return await handler(event, data)
            if user["is_verified"]:
                return await handler(event, data)
            await event.answer("Complete signup first via /signup.", show_alert=True)
            return None

        return await handler(event, data)
