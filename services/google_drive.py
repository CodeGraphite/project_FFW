from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload


ProgressCb = Callable[[int], None]


class GoogleDriveService:
    SCOPES = ["https://www.googleapis.com/auth/drive"]
    FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"

    def __init__(
        self,
        oauth_credentials_path: str,
        token_path: str,
        parent_folder_id: str | None = None,
        upload_chunk_size_bytes: int = 200 * 1024 * 1024,
        max_upload_attempts: int = 3,
    ):
        self.oauth_credentials_path = Path(oauth_credentials_path)
        self.token_path = Path(token_path)
        self.parent_folder_id = parent_folder_id or None
        self.upload_chunk_size_bytes = upload_chunk_size_bytes
        self.max_upload_attempts = max_upload_attempts
        self.service = self._build_service()

    def _load_token(self) -> Credentials | None:
        if not self.token_path.exists():
            return None
        return Credentials.from_authorized_user_file(str(self.token_path), self.SCOPES)

    def _save_token(self, credentials: Credentials) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(credentials.to_json(), encoding="utf-8")

    def _authorize(self) -> Credentials:
        if not self.oauth_credentials_path.exists():
            raise RuntimeError(
                f"Google OAuth credentials file was not found: {self.oauth_credentials_path}. "
                "Set GOOGLE_OAUTH_CREDENTIALS to a valid OAuth client credentials JSON file."
            )

        credentials = self._load_token()
        if credentials and credentials.valid:
            return credentials

        if credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                self._save_token(credentials)
                return credentials
            except RefreshError:
                self.token_path.unlink(missing_ok=True)
                credentials = None

        flow = InstalledAppFlow.from_client_secrets_file(str(self.oauth_credentials_path), self.SCOPES)
        flow_mode = os.getenv("GOOGLE_OAUTH_FLOW_MODE", "console").strip().lower()
        open_browser_raw = os.getenv("GOOGLE_OAUTH_OPEN_BROWSER", "false").strip().lower()
        open_browser = open_browser_raw in {"1", "true", "yes", "y", "on"}

        if flow_mode in {"local_server", "local", "browser"}:
            credentials = flow.run_local_server(host="localhost", port=0, open_browser=open_browser)
        elif flow_mode in {"console", "console_flow"}:
            if hasattr(flow, "run_console"):
                credentials = flow.run_console()
            else:
                # Fallback: local server without auto-opening browser.
                credentials = flow.run_local_server(host="localhost", port=0, open_browser=False)
        elif flow_mode in {"device", "device_code", "device_flow"}:
            if hasattr(flow, "run_device"):
                # NOTE: run_device() signature varies across google-auth-oauthlib versions.
                # If it fails, users can switch GOOGLE_OAUTH_FLOW_MODE=console.
                credentials = flow.run_device()
            else:
                raise RuntimeError(
                    "Device flow is not supported by your google-auth-oauthlib version. "
                    "Set GOOGLE_OAUTH_FLOW_MODE=console."
                )
        else:
            raise ValueError(
                "Invalid GOOGLE_OAUTH_FLOW_MODE. Expected one of: local_server|console|device. "
                f"Got: {flow_mode!r}"
            )
        self._save_token(credentials)
        return credentials

    def _build_service(self) -> Resource:
        try:
            credentials = self._authorize()
            return build("drive", "v3", credentials=credentials, cache_discovery=False)
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize Google Drive OAuth client: {exc}") from exc

    @staticmethod
    def _escape_query_value(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    def find_folder(self, name: str, parent_folder_id: str | None = None) -> str | None:
        escaped_name = self._escape_query_value(name)
        effective_parent_id = parent_folder_id or self.parent_folder_id
        query = (
            f"mimeType = '{self.FOLDER_MIME_TYPE}' "
            f"and name = '{escaped_name}' "
            "and trashed = false"
        )
        if effective_parent_id:
            query += f" and '{self._escape_query_value(effective_parent_id)}' in parents"

        try:
            response = self.service.files().list(
                q=query,
                fields="files(id, name)",
                pageSize=1,
            ).execute()
        except HttpError as exc:
            raise RuntimeError(f"Failed to search Google Drive folders: {exc}") from exc

        files = response.get("files", [])
        return files[0]["id"] if files else None

    def _create_folder(self, name: str, parent_folder_id: str | None = None) -> str:
        metadata = {"name": name, "mimeType": self.FOLDER_MIME_TYPE}
        effective_parent_id = parent_folder_id or self.parent_folder_id
        if effective_parent_id:
            metadata["parents"] = [effective_parent_id]

        try:
            folder = self.service.files().create(body=metadata, fields="id").execute()
        except HttpError as exc:
            raise RuntimeError(f"Failed to create Google Drive folder '{name}': {exc}") from exc

        return folder["id"]

    def ensure_user_folder(self, telegram_id: int) -> str:
        folder_name = f"user_{telegram_id}"
        folder_id = self.find_folder(folder_name)
        if folder_id:
            return folder_id
        return self._create_folder(folder_name)

    def share_folder_reader(self, folder_id: str, email: str) -> None:
        body = {"type": "user", "role": "reader", "emailAddress": email}
        try:
            self.service.permissions().create(
                fileId=folder_id,
                body=body,
                sendNotificationEmail=False,
                fields="id",
            ).execute()
        except HttpError as exc:
            raise RuntimeError(f"Failed to share Google Drive folder with {email}: {exc}") from exc

    def folder_link(self, folder_id: str) -> str:
        return f"https://drive.google.com/drive/folders/{folder_id}"

    def upload_file(self, file_path: Path, folder_id: str, progress_callback: ProgressCb) -> tuple[str, str]:
        metadata = {"name": file_path.name, "parents": [folder_id]}
        if not file_path.exists():
            raise RuntimeError(f"Local file does not exist: {file_path}")

        mime_type = None
        suffix = file_path.suffix.lower()
        if suffix == ".mp4":
            mime_type = "video/mp4"
        elif suffix == ".webm":
            mime_type = "video/webm"

        last_exc: Exception | None = None
        for attempt in range(1, self.max_upload_attempts + 1):
            media = MediaFileUpload(
                str(file_path),
                mimetype=mime_type,
                resumable=True,
                chunksize=self.upload_chunk_size_bytes,
            )
            request = self.service.files().create(body=metadata, media_body=media, fields="id, name")
            response = None
            progress_callback(50)

            try:
                while response is None:
                    status, response = request.next_chunk()
                    if status:
                        progress = 50 + int(status.progress() * 50)
                        progress_callback(max(50, min(99, progress)))
            except HttpError as exc:
                last_exc = exc
                status_code = getattr(getattr(exc, "resp", None), "status", None)
                # Basic retry for transient failures. Resumable uploads may restart from the beginning.
                if attempt < self.max_upload_attempts and status_code in {408, 429, 500, 502, 503, 504}:
                    continue
                raise RuntimeError(f"Google Drive upload failed for '{file_path.name}': {exc}") from exc
            except OSError as exc:
                raise RuntimeError(f"Could not read local file '{file_path}': {exc}") from exc

            progress_callback(100)
            return response["id"], response["name"]

        raise RuntimeError(f"Google Drive upload failed for '{file_path.name}': {last_exc}")

    def delete_file(self, google_file_id: str) -> None:
        try:
            self.service.files().delete(fileId=google_file_id).execute()
        except HttpError as exc:
            raise RuntimeError(f"Failed to delete Google Drive file '{google_file_id}': {exc}") from exc
