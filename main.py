from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot import build_dispatcher
from config import get_settings
from database import Database
from services import GoogleDriveService
from workers import CleanupWorker, QueueWorker

log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
numeric_level = getattr(logging, log_level, logging.INFO)
logging.basicConfig(
    level=numeric_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    db = Database(db_path=settings.db_path, default_storage_bytes=settings.default_storage_bytes)
    drive = GoogleDriveService(
        oauth_credentials_path=str(settings.google_oauth_credentials_path),
        token_path=str(settings.google_oauth_token_path),
        parent_folder_id=settings.google_drive_folder_id,
    )

    dp = build_dispatcher()
    dp.workflow_data["db"] = db
    dp.workflow_data["drive"] = drive
    dp.workflow_data["admin_ids"] = settings.admin_ids

    queue_worker = QueueWorker(bot=bot, db=db, drive=drive, tmp_dir=settings.tmp_dir)
    cleanup_worker = CleanupWorker(db=db, drive=drive, interval_seconds=3600)

    await bot.delete_webhook(drop_pending_updates=True)
    worker_task = asyncio.create_task(queue_worker.run())
    cleanup_task = asyncio.create_task(cleanup_worker.run())
    logger.info("Workers started. Polling Telegram updates.")
    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("Shutdown signal received; stopping polling.")
        raise
    finally:
        worker_task.cancel()
        cleanup_task.cancel()
        await asyncio.gather(worker_task, cleanup_task, return_exceptions=True)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())