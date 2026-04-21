# Telegram Drive Bot

Production-ready multi-user Telegram bot that accepts Telegram videos and YouTube links, queues work, uploads to Google Drive, and enforces per-user storage limits with an admin control panel.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![aiogram](https://img.shields.io/badge/aiogram-3.x-1f425f)
![SQLite](https://img.shields.io/badge/SQLite-DB-333333)
![Google Drive](https://img.shields.io/badge/Google%20Drive-API-green)

## Features

- Accept Telegram video files (up to 4GB from Telegram side)
- Accept YouTube links and download via `yt-dlp`
- Queue-based processing with SQLite (`pending`, `processing`, `completed`, `failed`)
- Upload files to Google Drive and auto-create per-user folders (`user_<telegram_id>`)
- Signup flow with unique email per Telegram account
- Password policy: exact `<email>BIGO`
- Folder sharing to signed-up user email (`reader` permission)
- Track upload history per user
- Enforce per-user storage limits (default 3GB)
- Admin panel + admin commands for users, quality policy, and file management
- Auto cleanup worker deletes old files (older than 24 hours)

## Architecture

```text
Telegram Updates
        |
        v
Aiogram Dispatcher
        |
        +--> Handlers (user/admin) --> SQLite (users/files/queue)
        |
        +--> QueueWorker Loop --------> Telegram Download / YouTube Download
        |                                 |
        |                                 v
        |                             Google Drive Upload
        |
        +--> CleanupWorker Loop --------> Delete Drive files older than 24h
```

## Requirements
- Python `3.11+`
- Telegram bot token from [@BotFather](https://t.me/BotFather)
- Google Cloud OAuth client credentials JSON with Google Drive API enabled
- `pip` and internet access for package installation

## 1) Installation

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 2) Configure Environment

1. Copy `config/.env.example` to `config/.env`
2. Fill all required values

Example:

```env
BOT_TOKEN=123456:ABC...
GOOGLE_OAUTH_CREDENTIALS=config/credentials.json
GOOGLE_OAUTH_TOKEN=config/token.json
ADMIN_IDS=123456789,987654321
DB_PATH=database/app.db
TMP_DIR=tmp/videos
DEFAULT_STORAGE_BYTES=3221225472
GOOGLE_DRIVE_FOLDER_ID=

# Recommended for Linux VPS/headless environments:
GOOGLE_OAUTH_FLOW_MODE=console
GOOGLE_OAUTH_OPEN_BROWSER=false

# Logging verbosity:
LOG_LEVEL=INFO
```

### Env Variables Explained

- `BOT_TOKEN`: Telegram bot token
- `GOOGLE_OAUTH_CREDENTIALS`: OAuth client credentials JSON path
- `GOOGLE_OAUTH_TOKEN`: Saved OAuth token path; created automatically after first login
- `GOOGLE_OAUTH_FLOW_MODE`: `console` (recommended) / `local_server` / `device` (depends on google-auth-oauthlib version)
- `GOOGLE_OAUTH_OPEN_BROWSER`: `true|false` (default `false` in VPS setups)
- `ADMIN_IDS`: Comma-separated Telegram user IDs that can use admin commands
- `DB_PATH`: SQLite database location
- `TMP_DIR`: Temporary local folder for download/upload staging
- `DEFAULT_STORAGE_BYTES`: Default per-user storage limit in bytes (3GB = `3221225472`)
- `GOOGLE_DRIVE_FOLDER_ID`: Optional parent folder in the authenticated user's Drive where all user folders are created

## 3) Google Drive OAuth Setup

1. Open Google Cloud Console
2. Create/select a project
3. Enable **Google Drive API**
4. Create an **OAuth client ID** for a Desktop App (Installed App flow)
5. Download the OAuth credentials JSON
6. Save it as `config/credentials.json` or update `GOOGLE_OAUTH_CREDENTIALS`
7. Start the bot once to generate `config/token.json`
8. If you're on a Linux VPS/headless machine, use:
   - `GOOGLE_OAUTH_FLOW_MODE=console`
   - `GOOGLE_OAUTH_OPEN_BROWSER=false`
   The bot will prompt you in the terminal to complete login (paste the verification code back into the terminal).

### Drive Access Model

- Files and folders are created in the authenticated Google account's Drive.
- If `GOOGLE_DRIVE_FOLDER_ID` is set, the bot creates `user_<telegram_id>` folders inside that parent folder.
- If `GOOGLE_DRIVE_FOLDER_ID` is empty, user folders are created in the Drive root.

## 4) Run the Bot

### Local (development / quick test)

```bash
python main.py
```

Expected behavior:
- DB initializes automatically
- Queue worker starts
- Cleanup worker starts (runs every hour)
- Bot begins Telegram polling

### Production (Linux VPS + systemd)

See: [docs/deploy-linux-vps.md](docs/deploy-linux-vps.md)

## 5) User Flow

### Telegram Video

1. User sends video
2. Bot checks:
   - user banned status
   - 4GB Telegram file-size ceiling
   - user storage limit
3. If valid, task is queued
4. Worker downloads -> uploads to Drive -> updates DB -> notifies user
5. Temporary file is deleted

### YouTube Link

1. User sends YouTube URL
2. Bot checks quality policy:
   - fixed quality by admin OR
   - user-selectable quality keyboard
3. Task is queued
4. Worker downloads with `yt-dlp` -> uploads -> updates DB -> notifies user
5. Temporary file is deleted

## 6) Commands

### User Commands

- `/start` - start bot; unverified users are forced to signup before using features
- `/signup` - register with unique email and password format `<email>BIGO`
- `/my_folder` - return user Google Drive folder link
- `/upload` - upload usage info
- `/history` - show user upload history
- `/help` - show all available commands

### Admin Commands

- `/admin`
- `/users`
- `/user <telegram_id>`
- `/set_limit <telegram_id> <10GB>`
- `/reset_limit <telegram_id>`
- `/ban <telegram_id>`
- `/unban <telegram_id>`
- `/set_quality <720p>`
- `/reset_quality`
- `/disable_quality <1080p>`
- `/enable_quality <1080p>`
- `/quality_status`
- `/set_email <telegram_id> <email>`
- `/reset_email <telegram_id>`
- `/delete_old`
- `/delete_user_files <telegram_id>`
- `/delete_file <file_id>`

## Signup Policy

- User must complete `/signup` to use upload/history media features.
- Global middleware blocks unverified users from all actions except `/start`, `/signup`, `/help`.
- Email must be unique globally (cannot be reused by another Telegram account).
- Password must be exactly `<email>BIGO`.
- Maximum 3 wrong password attempts per signup session; then user must restart with `/signup`.
- On successful signup, bot shares user Drive folder with:
  - `type=user`
  - `role=reader`
  - `emailAddress=<user_email>`

## 7) Admin Usage Examples

Set user storage to 10GB:

```text
/set_limit 123456789 10GB
```

Reset user storage to default:

```text
/reset_limit 123456789
```

Force all users to 720p:

```text
/set_quality 720p
```

Disable 1080p option:

```text
/disable_quality 1080p
```

Delete expired files:

```text
/delete_old
```

## 8) Data Model

- `users`: account, limits, used storage, admin/banned flags
- `videos`: source metadata, status, progress, errors
- `files`: uploaded Drive files and retention timestamps
- `queue`: execution lifecycle for worker
- `settings`: quality policy and defaults

## 9) Progress Semantics

- Download phase maps to `0-50%`
- Upload phase maps to `50-100%`
- Progress stored in DB and reflected in status updates

## 10) Project Structure

- `main.py` - entrypoint and service wiring
- `bot/` - dispatcher bootstrap
- `handlers/` - user/admin/management handlers
- `workers/` - queue and cleanup workers
- `services/` - external integrations (YouTube, Telegram file, Drive)
- `database/` - SQLite schema and repository methods
- `states/` - FSM states
- `keyboards/` - inline keyboards
- `utils/` - formatters/parsers
- `config/` - runtime configuration

## 11) Operations Notes

- Ensure your bot host has enough disk for temporary downloads
- `tmp/videos` is runtime scratch space; temp files are deleted after processing
- Keep OAuth credentials and `token.json` secure and out of git
- Set `GOOGLE_OAUTH_FLOW_MODE=console` on headless servers to avoid needing a browser
- Back up `database/app.db` if you need historical tracking

## 12) Troubleshooting

### Bot does not start

- Check `BOT_TOKEN` in `config/.env`
- Verify environment is activated and dependencies installed
- Run: `python -m compileall .` to validate syntax

### Drive upload fails

- Verify Drive API is enabled in Google Cloud
- Verify `GOOGLE_OAUTH_CREDENTIALS` points to a valid OAuth client credentials JSON file
- If OAuth token is invalid/revoked:
  - delete `config/token.json`
  - restart the bot so it generates a new token
- On headless servers, ensure:
  - `GOOGLE_OAUTH_FLOW_MODE=console`
  - `GOOGLE_OAUTH_OPEN_BROWSER=false`
- Verify the authenticated Google account has enough Drive storage quota

### User cannot queue Telegram video

- Check if user is banned
- Check file is <= 4GB
- Check user storage limit (`used_storage + file_size <= storage_limit`)

### YouTube download fails

- Validate URL format
- Check server/network restrictions
- Confirm `yt-dlp` can access the target video
- If you need merged best-quality streams, install `ffmpeg`
- Current bot configuration is set to single-file formats to work without `ffmpeg`