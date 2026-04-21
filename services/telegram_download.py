from __future__ import annotations

from pathlib import Path
from typing import Callable

from aiogram import Bot


ProgressCb = Callable[[int], None]


async def download_telegram_video(
    bot: Bot,
    file_id: str,
    output_path: Path,
    file_size: int | None,
    progress_callback: ProgressCb,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tg_file = await bot.get_file(file_id)
    await bot.download_file(tg_file.file_path, destination=output_path)
    # aiogram downloader has no chunk callback, so we set a terminal progress update.
    _ = file_size
    progress_callback(50)
    return output_path
