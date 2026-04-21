from __future__ import annotations

import re


YOUTUBE_RE = re.compile(
    r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[\w\-]{6,}",
    re.IGNORECASE,
)


def is_youtube_url(text: str) -> bool:
    return bool(YOUTUBE_RE.search(text.strip()))
