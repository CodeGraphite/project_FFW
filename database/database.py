from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any


UTC = timezone.utc


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def parse_size_to_bytes(size_text: str) -> int:
    text = size_text.strip().upper()
    units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    for unit, factor in units.items():
        if text.endswith(unit):
            num = float(text.removesuffix(unit).strip())
            return int(num * factor)
    return int(text)


@dataclass
class QueueTask:
    queue_id: int
    video_id: int
    user_id: int
    telegram_id: int
    source: str
    youtube_url: str | None
    quality: str | None
    telegram_file_id: str | None
    telegram_file_name: str | None
    telegram_file_size: int | None


class Database:
    def __init__(self, db_path: Path, default_storage_bytes: int):
        self.db_path = db_path
        self.default_storage_bytes = default_storage_bytes
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    email TEXT UNIQUE,
                    drive_folder_id TEXT,
                    is_verified INTEGER NOT NULL DEFAULT 0,
                    storage_limit INTEGER NOT NULL,
                    used_storage INTEGER NOT NULL DEFAULT 0,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    is_banned INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    youtube_url TEXT,
                    quality TEXT,
                    telegram_file_id TEXT,
                    telegram_file_name TEXT,
                    telegram_file_size INTEGER,
                    file_size INTEGER,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    video_id INTEGER NOT NULL,
                    google_file_id TEXT NOT NULL,
                    google_file_name TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    uploaded_at TEXT NOT NULL,
                    delete_after TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    fixed_quality TEXT,
                    allowed_qualities TEXT NOT NULL,
                    disabled_qualities TEXT NOT NULL,
                    default_storage INTEGER NOT NULL
                );
                """
            )
            row = conn.execute("SELECT id FROM settings WHERE id = 1").fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO settings (id, fixed_quality, allowed_qualities, disabled_qualities, default_storage) VALUES (1, NULL, ?, ?, ?)",
                    (
                        json.dumps(["360p", "480p", "720p", "1080p", "4k"]),
                        json.dumps([]),
                        self.default_storage_bytes,
                    ),
                )
                conn.commit()
            self._migrate_users_table(conn)

    def _migrate_users_table(self, conn: sqlite3.Connection) -> None:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "email" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
        if "drive_folder_id" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN drive_folder_id TEXT")
        if "is_verified" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users(email)")
        conn.commit()

    def ensure_user(self, telegram_id: int, is_admin: bool = False) -> sqlite3.Row:
        with self._lock, self._conn() as conn:
            user = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
            if user:
                if is_admin and not user["is_admin"]:
                    conn.execute("UPDATE users SET is_admin = 1 WHERE telegram_id = ?", (telegram_id,))
                    conn.commit()
                    user = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
                return user
            conn.execute(
                "INSERT INTO users (telegram_id, storage_limit, used_storage, is_admin, is_banned, created_at) VALUES (?, ?, 0, ?, 0, ?)",
                (telegram_id, self.default_storage_bytes, 1 if is_admin else 0, utc_now()),
            )
            conn.commit()
            return conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()

    def get_user_by_telegram_id(self, telegram_id: int) -> sqlite3.Row | None:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()

    def get_user_by_email(self, email: str) -> sqlite3.Row | None:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM users WHERE lower(email) = lower(?)", (email,)).fetchone()

    def get_user_by_id(self, user_id: int) -> sqlite3.Row | None:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def set_user_signup(self, telegram_id: int, email: str, drive_folder_id: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE users SET email = ?, drive_folder_id = ?, is_verified = 1 WHERE telegram_id = ?",
                (email.lower(), drive_folder_id, telegram_id),
            )
            conn.commit()

    def set_user_email(self, telegram_id: int, email: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE users SET email = ? WHERE telegram_id = ?", (email.lower(), telegram_id))
            conn.commit()

    def reset_user_email(self, telegram_id: int) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE users SET email = NULL, is_verified = 0, drive_folder_id = NULL WHERE telegram_id = ?", (telegram_id,))
            conn.commit()

    def set_user_limit(self, telegram_id: int, size_bytes: int) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE users SET storage_limit = ? WHERE telegram_id = ?", (size_bytes, telegram_id))
            conn.commit()

    def reset_user_limit(self, telegram_id: int) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE users SET storage_limit = ? WHERE telegram_id = ?", (self.default_storage_bytes, telegram_id))
            conn.commit()

    def ban_user(self, telegram_id: int, is_banned: bool) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE users SET is_banned = ? WHERE telegram_id = ?", (1 if is_banned else 0, telegram_id))
            conn.commit()

    def list_users(self, limit: int = 50) -> list[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM users ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def get_settings(self) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
            return {
                "fixed_quality": row["fixed_quality"],
                "allowed_qualities": json.loads(row["allowed_qualities"]),
                "disabled_qualities": json.loads(row["disabled_qualities"]),
                "default_storage": row["default_storage"],
            }

    def set_fixed_quality(self, quality: str | None) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE settings SET fixed_quality = ? WHERE id = 1", (quality,))
            conn.commit()

    def disable_quality(self, quality: str) -> None:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT disabled_qualities FROM settings WHERE id = 1").fetchone()
            current = set(json.loads(row["disabled_qualities"]))
            current.add(quality)
            conn.execute("UPDATE settings SET disabled_qualities = ? WHERE id = 1", (json.dumps(sorted(current)),))
            conn.commit()

    def enable_quality(self, quality: str) -> None:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT disabled_qualities FROM settings WHERE id = 1").fetchone()
            current = set(json.loads(row["disabled_qualities"]))
            current.discard(quality)
            conn.execute("UPDATE settings SET disabled_qualities = ? WHERE id = 1", (json.dumps(sorted(current)),))
            conn.commit()

    def create_video_and_queue_task(
        self,
        telegram_id: int,
        source: str,
        youtube_url: str | None = None,
        quality: str | None = None,
        telegram_file_id: str | None = None,
        telegram_file_name: str | None = None,
        telegram_file_size: int | None = None,
    ) -> int:
        with self._lock, self._conn() as conn:
            user = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
            if not user:
                raise ValueError("User not found")
            cur = conn.execute(
                """
                INSERT INTO videos (user_id, source, youtube_url, quality, telegram_file_id, telegram_file_name, telegram_file_size, status, progress, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?)
                """,
                (user["id"], source, youtube_url, quality, telegram_file_id, telegram_file_name, telegram_file_size, utc_now()),
            )
            video_id = cur.lastrowid
            conn.execute("INSERT INTO queue (video_id, status, created_at) VALUES (?, 'pending', ?)", (video_id, utc_now()))
            conn.commit()
            return int(video_id)

    def acquire_next_queue_task(self) -> QueueTask | None:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                """
                SELECT q.id AS queue_id, v.id AS video_id, v.user_id, u.telegram_id, v.source,
                       v.youtube_url, v.quality, v.telegram_file_id, v.telegram_file_name, v.telegram_file_size
                FROM queue q
                JOIN videos v ON v.id = q.video_id
                JOIN users u ON u.id = v.user_id
                WHERE q.status = 'pending'
                ORDER BY q.id ASC
                LIMIT 1
                """
            ).fetchone()
            if not row:
                return None
            conn.execute("UPDATE queue SET status = 'processing', started_at = ? WHERE id = ?", (utc_now(), row["queue_id"]))
            conn.execute("UPDATE videos SET status = 'processing', progress = 0 WHERE id = ?", (row["video_id"],))
            conn.commit()
            return QueueTask(**dict(row))

    def set_video_progress(self, video_id: int, progress: int) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE videos SET progress = ? WHERE id = ?", (max(0, min(100, progress)), video_id))
            conn.commit()

    def complete_video(
        self,
        queue_id: int,
        video_id: int,
        user_id: int,
        google_file_id: str,
        google_file_name: str,
        file_size: int,
    ) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE queue SET status = 'completed', finished_at = ? WHERE id = ?", (utc_now(), queue_id))
            conn.execute("UPDATE videos SET status = 'completed', progress = 100, file_size = ? WHERE id = ?", (file_size, video_id))
            conn.execute("UPDATE users SET used_storage = used_storage + ? WHERE id = ?", (file_size, user_id))
            conn.execute(
                """
                INSERT INTO files (user_id, video_id, google_file_id, google_file_name, file_size, uploaded_at, delete_after)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, video_id, google_file_id, google_file_name, file_size, utc_now(), (datetime.now(tz=UTC) + timedelta(hours=24)).isoformat()),
            )
            conn.commit()

    def fail_video(self, queue_id: int, video_id: int, error_message: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE queue SET status = 'failed', finished_at = ? WHERE id = ?", (utc_now(), queue_id))
            conn.execute("UPDATE videos SET status = 'failed', error_message = ? WHERE id = ?", (error_message[:2000], video_id))
            conn.commit()

    def get_queue_size(self) -> int:
        with self._conn() as conn:
            return int(conn.execute("SELECT COUNT(*) AS c FROM queue WHERE status = 'pending'").fetchone()["c"])

    def get_active_downloads(self) -> int:
        with self._conn() as conn:
            return int(conn.execute("SELECT COUNT(*) AS c FROM queue WHERE status = 'processing'").fetchone()["c"])

    def stats(self) -> dict[str, int]:
        with self._conn() as conn:
            total_users = int(conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"])
            total_files = int(conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"])
            total_storage = int(conn.execute("SELECT COALESCE(SUM(file_size), 0) AS s FROM files").fetchone()["s"])
            return {
                "total_users": total_users,
                "total_files": total_files,
                "total_storage": total_storage,
                "queue_size": self.get_queue_size(),
                "active_downloads": self.get_active_downloads(),
            }

    def can_user_store(self, telegram_id: int, expected_size: int) -> bool:
        user = self.get_user_by_telegram_id(telegram_id)
        if not user:
            return False
        return (user["used_storage"] + max(expected_size, 0)) <= user["storage_limit"]

    def history_for_user(self, telegram_id: int, limit: int = 20) -> list[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(
                """
                SELECT f.id, f.google_file_name, f.google_file_id, f.file_size, f.uploaded_at
                FROM files f
                JOIN users u ON u.id = f.user_id
                WHERE u.telegram_id = ?
                ORDER BY f.id DESC
                LIMIT ?
                """,
                (telegram_id, limit),
            ).fetchall()

    def files_older_than_24h(self) -> list[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM files WHERE delete_after <= ? ORDER BY id ASC",
                (utc_now(),),
            ).fetchall()

    def delete_file_record(self, file_id: int) -> sqlite3.Row | None:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
            if not row:
                return None
            conn.execute("UPDATE users SET used_storage = MAX(used_storage - ?, 0) WHERE id = ?", (row["file_size"], row["user_id"]))
            conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
            conn.commit()
            return row

    def delete_files_for_user(self, telegram_id: int) -> list[sqlite3.Row]:
        with self._lock, self._conn() as conn:
            user = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
            if not user:
                return []
            files = conn.execute("SELECT * FROM files WHERE user_id = ?", (user["id"],)).fetchall()
            conn.execute("DELETE FROM files WHERE user_id = ?", (user["id"],))
            conn.execute("UPDATE users SET used_storage = 0 WHERE id = ?", (user["id"],))
            conn.commit()
            return list(files)
