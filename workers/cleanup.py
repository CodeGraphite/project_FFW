from __future__ import annotations

import asyncio
import logging

from database import Database
from services import GoogleDriveService

logger = logging.getLogger(__name__)


class CleanupWorker:
    def __init__(self, db: Database, drive: GoogleDriveService, interval_seconds: int = 60):
        self.db = db
        self.drive = drive
        self.interval_seconds = 10
        self._running = True

    async def run(self) -> None:
        logger.info("CleanupWorker started (interval_seconds=%s)", self.interval_seconds)
        try:
            while self._running:
                try:
                    await self._cleanup_once()
                except Exception as exc:
                    logger.exception("Cleanup loop failed: %s", exc)
                await asyncio.sleep(self.interval_seconds)
        except asyncio.CancelledError:
            self._running = False
            raise

    async def _cleanup_once(self) -> None:
        rows = self.db.files_older_than_24h()
        for row in rows:
            try:
                await asyncio.to_thread(self.drive.delete_file, row["google_file_id"])
                self.db.delete_file_record(row["id"])
            except Exception as exc:
                logger.warning("Could not delete old file %s: %s", row["id"], exc)
