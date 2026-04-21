from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from aiogram import Bot

from database import Database, QueueTask
from services import GoogleDriveService, download_telegram_video, download_youtube_video
from utils import progress_bar

logger = logging.getLogger(__name__)


class QueueWorker:
    def __init__(self, bot: Bot, db: Database, drive: GoogleDriveService, tmp_dir: Path):
        self.bot = bot
        self.db = db
        self.drive = drive
        self.tmp_dir = tmp_dir
        self._running = True
        self._progress_edit_last_log_ts = 0.0
        self._progress_edit_error_count = 0

    async def run(self) -> None:
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        logger.info("QueueWorker started (tmp_dir=%s)", self.tmp_dir)
        try:
            while self._running:
                task = self.db.acquire_next_queue_task()
                if not task:
                    await asyncio.sleep(2)
                    continue
                await self._process(task)
        except asyncio.CancelledError:
            self._running = False
            raise

    async def _progress(self, chat_id: int, msg_id: int, stage: str, percent: int) -> None:
        text = f"{stage}\n{progress_bar(percent)}"
        try:
            await self.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text)
        except Exception:
            self._progress_edit_error_count += 1
            now = time.time()
            # Throttle noisy "can't edit message" errors.
            if now - self._progress_edit_last_log_ts >= 60:
                logger.warning(
                    "Failed to edit progress message (stage=%s percent=%s chat_id=%s message_id=%s) [count=%s]",
                    stage,
                    percent,
                    chat_id,
                    msg_id,
                    self._progress_edit_error_count,
                )
                self._progress_edit_last_log_ts = now
                self._progress_edit_error_count = 0

    async def _process(self, task: QueueTask) -> None:
        progress_msg = await self.bot.send_message(task.telegram_id, f"Task #{task.video_id} started.")
        local_file = None
        try:
            if task.source == "telegram":
                local_file = self.tmp_dir / f"{task.video_id}_{task.telegram_file_name or 'video.mp4'}"
                local_file = await download_telegram_video(
                    bot=self.bot,
                    file_id=task.telegram_file_id,
                    output_path=local_file,
                    file_size=task.telegram_file_size,
                    progress_callback=lambda p: self.db.set_video_progress(task.video_id, p),
                )
                await self._progress(task.telegram_id, progress_msg.message_id, "⬇ Downloading", 50)
            else:
                local_file = await asyncio.to_thread(
                    download_youtube_video,
                    task.youtube_url,
                    task.quality or "720p",
                    self.tmp_dir,
                    lambda p: self.db.set_video_progress(task.video_id, p),
                )
                await self._progress(task.telegram_id, progress_msg.message_id, "⬇ Downloading", 50)

            folder_id = await asyncio.to_thread(self.drive.ensure_user_folder, task.telegram_id)
            google_id, google_name = await asyncio.to_thread(
                self.drive.upload_file,
                local_file,
                folder_id,
                lambda p: self.db.set_video_progress(task.video_id, p),
            )
            await self._progress(task.telegram_id, progress_msg.message_id, "⬆ Uploading", 100)
            size = local_file.stat().st_size
            self.db.complete_video(task.queue_id, task.video_id, task.user_id, google_id, google_name, size)
            # Avoid parse_mode="Markdown" because video titles may contain characters
            # that break markdown entity parsing.
            await self.bot.send_message(task.telegram_id, f"Upload complete: {google_name}\nDrive file id: {google_id}")
        except asyncio.CancelledError:
            # Don't mark queue items as failed when shutting down.
            raise
        except Exception as exc:
            logger.exception("Queue task failed: %s", exc)
            self.db.fail_video(task.queue_id, task.video_id, str(exc))
            await self.bot.send_message(task.telegram_id, f"Task #{task.video_id} failed: {exc}")
        finally:
            if local_file and Path(local_file).exists():
                try:
                    Path(local_file).unlink()
                except Exception:
                    logger.warning("Failed to remove temp file: %s", local_file)
