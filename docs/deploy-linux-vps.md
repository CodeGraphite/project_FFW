## Deploy on a Linux VPS (systemd + polling)

This bot runs with Telegram long polling (no public HTTP endpoint required) and uses SQLite + a local temp directory for downloads.

### 1) Install OS dependencies

You should have:

- Python 3.11+
- `ffmpeg` (recommended; yt-dlp/Drive playback safety)
- Build deps for Python packages (varies by distro)
- `git` (optional)

On Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg python3.11 python3.11-venv python3-pip
```

### 2) Create a dedicated user

```bash
sudo useradd -r -m -s /bin/bash ffwbot
```

### 3) Prepare folders

Example (recommended):

```bash
sudo mkdir -p /opt/ffw-bot
sudo mkdir -p /var/lib/ffw-bot/tmp
sudo chown -R ffwbot:ffwbot /opt/ffw-bot /var/lib/ffw-bot
```

### 4) Upload the project and set up venv

Copy your project into `/opt/ffw-bot`, then:

```bash
cd /opt/ffw-bot
sudo -u ffwbot -H python3.11 -m venv .venv
sudo -u ffwbot -H bash -lc ".venv/bin/pip install --upgrade pip && .venv/bin/pip install -r requirements.txt"
```

### 5) Configure environment (`config/.env`)

Create `/opt/ffw-bot/config/.env` based on `config/.env.example`.

Important variables:

- `BOT_TOKEN`
- `GOOGLE_OAUTH_CREDENTIALS` (path to OAuth client credentials JSON)
- `GOOGLE_OAUTH_TOKEN` (token file; will be created/updated)
- `ADMIN_IDS` (comma-separated Telegram IDs)
- `DB_PATH` (SQLite file path)
- `TMP_DIR` (download temp directory path)
- `GOOGLE_OAUTH_FLOW_MODE` (recommended: `console`)
- `GOOGLE_OAUTH_OPEN_BROWSER` (recommended: `false`)

Example:

```env
BOT_TOKEN=123456:ABC...
GOOGLE_OAUTH_CREDENTIALS=config/credentials.json
GOOGLE_OAUTH_TOKEN=config/token.json
ADMIN_IDS=8362218822
DB_PATH=database/app.db
TMP_DIR=tmp/videos
DEFAULT_STORAGE_BYTES=3221225472
GOOGLE_DRIVE_FOLDER_ID=

# Headless-friendly OAuth:
GOOGLE_OAUTH_FLOW_MODE=console
GOOGLE_OAUTH_OPEN_BROWSER=false
```

### 6) One-time Google OAuth token creation

The first start must complete OAuth once to create `config/token.json`.

Recommended flow:

```bash
sudo -u ffwbot -H bash -lc 'cd /opt/ffw-bot && .venv/bin/python main.py'
```

If `GOOGLE_OAUTH_FLOW_MODE=console`, the program will prompt you in the terminal to complete the login and enter the verification code.

After the token is created, stop the program (Ctrl+C), then start via systemd.

### 7) systemd unit

Use `deploy/systemd/ffw-bot.service` (see file in repo). Create/enable it:

```bash
sudo cp deploy/systemd/ffw-bot.service /etc/systemd/system/ffw-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now ffw-bot
sudo systemctl status ffw-bot
```

Logs are available via:

```bash
journalctl -u ffw-bot -f
```

