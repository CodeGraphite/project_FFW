from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / "config" / ".env")


def _parse_admin_ids(raw: str) -> set[int]:
    raw = (raw or "").strip()
    if not raw:
        return set()

    ids: set[int] = set()
    invalid: list[str] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            val = int(item)
        except ValueError:
            invalid.append(item)
            continue
        if val <= 0:
            invalid.append(item)
            continue
        ids.add(val)

    if invalid:
        raise ValueError(f"Invalid ADMIN_IDS entries: {', '.join(invalid)}")
    return ids


def _require_file(path: Path, var_name: str) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"{var_name} file not found: {path}")
    return path


def _parse_positive_int(raw_value: str, *, var_name: str) -> int:
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        raise ValueError(f"{var_name} must be an integer, got {raw_value!r}") from None
    if value <= 0:
        raise ValueError(f"{var_name} must be > 0, got {value}")
    return value


@dataclass(frozen=True)
class Settings:
    bot_token: str
    google_oauth_credentials_path: Path
    google_oauth_token_path: Path
    admin_ids: set[int]
    db_path: Path
    tmp_dir: Path
    default_storage_bytes: int
    google_drive_folder_id: str | None


def get_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("BOT_TOKEN is not set in config/.env")

    google_credentials = os.getenv("GOOGLE_OAUTH_CREDENTIALS", "").strip()
    if not google_credentials:
        raise ValueError("GOOGLE_OAUTH_CREDENTIALS is not set in config/.env")

    google_token = os.getenv("GOOGLE_OAUTH_TOKEN", "config/token.json").strip()
    if not google_token:
        raise ValueError("GOOGLE_OAUTH_TOKEN is empty in config/.env")

    google_credentials_path = _require_file(ROOT_DIR / google_credentials, "GOOGLE_OAUTH_CREDENTIALS")
    google_token_path = ROOT_DIR / google_token

    db_path_raw = os.getenv("DB_PATH", "database/app.db").strip()
    if not db_path_raw:
        raise ValueError("DB_PATH is empty in config/.env")

    tmp_dir_raw = os.getenv("TMP_DIR", "tmp/videos").strip()
    if not tmp_dir_raw:
        raise ValueError("TMP_DIR is empty in config/.env")

    return Settings(
        bot_token=token,
        google_oauth_credentials_path=google_credentials_path,
        google_oauth_token_path=google_token_path,
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS", "")),
        db_path=ROOT_DIR / db_path_raw,
        tmp_dir=ROOT_DIR / tmp_dir_raw,
        default_storage_bytes=_parse_positive_int(
            os.getenv("DEFAULT_STORAGE_BYTES", str(3 * 1024 * 1024 * 1024)),
            var_name="DEFAULT_STORAGE_BYTES",
        ),
        google_drive_folder_id=os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip() or None,
    )
