from __future__ import annotations

import math
from pathlib import Path
from typing import Callable

import yt_dlp
import re


ProgressCb = Callable[[int], None]


QUALITY_TO_FORMAT = {
    # Use single-file formats first so ffmpeg is not required.
    "360p": "best[height<=360][ext=mp4]/best[height<=360]/best",
    "480p": "best[height<=480][ext=mp4]/best[height<=480]/best",
    "720p": "best[height<=720][ext=mp4]/best[height<=720]/best",
    "1080p": "best[height<=1080][ext=mp4]/best[height<=1080]/best",
    "4k": "best[height<=2160][ext=mp4]/best[height<=2160]/best",
}

QUALITY_HEIGHTS = {
    "360p": 360,
    "480p": 480,
    "720p": 720,
    "1080p": 1080,
    "4k": 2160,
}


def _hook(download_status: dict, cb: ProgressCb) -> None:
    status = download_status.get("status")
    if status == "downloading":
        total = download_status.get("total_bytes") or download_status.get("total_bytes_estimate")
        downloaded = download_status.get("downloaded_bytes", 0)
        if total:
            percent = int((downloaded / total) * 50)
            cb(max(1, min(50, percent)))
    elif status == "finished":
        cb(50)


def _estimate_format_size_bytes(fmt: dict, duration: int | float | None) -> int | None:
    explicit_size = fmt.get("filesize") or fmt.get("filesize_approx")
    if explicit_size:
        return int(explicit_size)

    tbr = fmt.get("tbr")
    if not tbr or not duration:
        return None
    return int((float(tbr) * 1000 / 8) * float(duration))


def _format_size_label(size_bytes: int | None) -> str | None:
    if not size_bytes or size_bytes <= 0:
        return None
    size_mb = math.ceil(size_bytes / (1024 * 1024))
    return f"~{size_mb} MB"


def _pick_best_format(info: dict, max_height: int) -> dict | None:
    duration = info.get("duration")
    candidates: list[tuple[int, int, int, dict]] = []
    for fmt in info.get("formats", []):
        if fmt.get("vcodec") == "none":
            continue
        height = fmt.get("height") or 0
        if not height or height > max_height:
            continue
        ext_priority = 1 if fmt.get("ext") == "mp4" else 0
        size_bytes = _estimate_format_size_bytes(fmt, duration) or 0
        tbr = int(fmt.get("tbr") or 0)
        candidates.append((height, ext_priority, max(size_bytes, tbr), fmt))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return candidates[0][3]


def get_quality_menu_options(url: str, qualities: list[str]) -> list[tuple[str, str]]:
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    options: list[tuple[str, str]] = []
    for quality in qualities:
        max_height = QUALITY_HEIGHTS.get(quality)
        if not max_height:
            options.append((quality, quality))
            continue
        best_format = _pick_best_format(info, max_height)
        size_label = _format_size_label(
            _estimate_format_size_bytes(best_format, info.get("duration")) if best_format else None
        )
        label = f"{quality} ({size_label})" if size_label else quality
        options.append((quality, label))
    return options


def _sanitize_filename(name: str, max_len: int = 120) -> str:
    # Windows-invalid filename characters:
    # < > : " / \ | ? *
    name = re.sub(r"[<>:\"/\\|?*]", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(" .")
    if not name:
        return "video"
    return name[:max_len]


def download_youtube_video(url: str, quality: str, output_dir: Path, progress_callback: ProgressCb) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    # Use ID-based filenames during download to avoid edge cases,
    # then rename to the YouTube title for better Drive UX.
    out_tmpl = str(output_dir / "%(id)s.%(ext)s")
    ydl_opts = {
        "format": QUALITY_TO_FORMAT.get(quality, QUALITY_TO_FORMAT["720p"]),
        "outtmpl": out_tmpl,
        "noplaylist": True,
        "progress_hooks": [lambda d: _hook(d, progress_callback)],
        "quiet": True,
    }
    downloaded_path: Path | None = None
    target_path: Path | None = None
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        downloaded_path = Path(ydl.prepare_filename(info))

        # Rename to YouTube title (safe + length-limited).
        youtube_title = str(info.get("title") or "video")
        safe_title = _sanitize_filename(youtube_title)
        video_id = str(info.get("id") or "").strip()

        # Preserve the real downloaded suffix to avoid mismatched file types
        # (Drive playback/MIME detection can break if we force .mp4 incorrectly).
        suffix = downloaded_path.suffix.lower() or ".mp4"
        id_suffix = f"_{video_id}" if video_id else ""
        target_path = output_dir / f"{safe_title}{id_suffix}{suffix}"

        # If the exact target already exists and video_id is available, keep it unique.
        # (downloaded_path is normally unique via yt-dlp id template, but this is extra safety.)
        if target_path.exists() and video_id:
            target_path = output_dir / f"{safe_title}_{video_id}__dup{suffix}"

        if downloaded_path != target_path:
            downloaded_path.rename(target_path)

    progress_callback(50)
    return target_path if target_path is not None else downloaded_path  # type: ignore[return-value]
