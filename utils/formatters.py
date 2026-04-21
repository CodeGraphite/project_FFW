from __future__ import annotations


def format_bytes(size: int) -> str:
    size = max(0, int(size))
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            return f"{size:.2f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.2f} TB"


def progress_bar(percent: int, length: int = 10) -> str:
    percent = max(0, min(100, percent))
    done = int(length * percent / 100)
    return f"{'█' * done}{'░' * (length - done)} {percent}%"
