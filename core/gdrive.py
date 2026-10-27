import os
import io
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/drive"]

class DriveFile:
    def __init__(self, file_id: str, name: str, size: int, created_time: str, timestamp: float):
        self.file_id = file_id
        self.name = name
        self.size = size
        self.created_time = created_time
        self.timestamp = timestamp

    @property
    def size_mb(self) -> float:
        return self.size / (1024 * 1024)

    @property
    def size_gb(self) -> float:
        return self.size / (1024 ** 3)

    def __repr__(self) -> str:
        return f"<DriveFile '{self.name}' ({self.size_mb:.1f} MB)>"


class GoogleDriveManager:
    def __init__(self, credentials_file: Path, token_file: Path):
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.service = None
        self.folder_id = None

    def is_authenticated(self) -> bool:
        if not self.token_file.exists():
            return False
        try:
            creds = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
            return creds and (creds.valid or creds.expired and creds.refresh_token)
        except Exception:
            return False

    def authenticate(self, callback_prompt: Optional[Callable[[str], None]] = None) -> bool:
        """
        Authenticates with Google Drive using token.json or credentials.json.
        """
        creds = None
        if self.token_file.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
            except Exception as e:
                print(f"[Drive] Could not load token: {e}")

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    print(f"[Drive] Token refresh failed: {e}. Re-authenticating...")
                    creds = None

            if not creds:
                if not self.credentials_file.exists():
                    raise FileNotFoundError(
                        f"Google Drive OAuth credentials file '{self.credentials_file}' not found.\n"
                        "Please place your 'credentials.json' from Google Cloud Console in the app folder."
                    )
                if callback_prompt:
                    callback_prompt("Opening browser to authorize Google Drive access...")
                flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_file), SCOPES)
                creds = flow.run_local_server(port=0)

            # Save token for future silent runs
            with open(self.token_file, "w") as token:
                token.write(creds.to_json())

        self.service = build("drive", "v3", credentials=creds)
        return True

    def get_account_storage_info(self) -> Dict[str, int]:
        """Returns Google Account storage info in bytes: {'limit': ..., 'usage': ...}"""
        if not self.service:
            self.authenticate()
        about = self.service.about().get(fields="storageQuota").execute()
        quota = about.get("storageQuota", {})
        limit = int(quota.get("limit", 0))  # 0 or None if unlimited
        usage = int(quota.get("usage", 0))
        return {"limit": limit, "usage": usage}

    def get_or_create_folder(self, folder_name: str) -> str:
        """Finds or creates the target folder in Google Drive and caches folder_id."""
        if not self.service:
            self.authenticate()

        # Query for existing active folder
        query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = self.service.files().list(q=query, fields="files(id, name)", spaces="drive").execute()
        files = results.get("files", [])

        if files:
            self.folder_id = files[0]["id"]
            return self.folder_id

        # Folder does not exist, create it
        file_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder"
        }
        folder = self.service.files().create(body=file_metadata, fields="id").execute()
        self.folder_id = folder.get("id")
        return self.folder_id

    def list_files_in_folder(self, folder_name: str) -> List[DriveFile]:
        """
        Lists all files inside the specified Google Drive folder.
        Returns DriveFiles sorted by timestamp (oldest first).
        """
        folder_id = self.get_or_create_folder(folder_name)
        drive_files: List[DriveFile] = []
        page_token = None

        query = f"'{folder_id}' in parents and trashed = false"

        while True:
            response = self.service.files().list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, size, createdTime)",
                pageToken=page_token,
                pageSize=100
            ).execute()

            for item in response.get("files", []):
                file_id = item["id"]
                name = item["name"]
                size = int(item.get("size", 0))
                created_time = item.get("createdTime", "")
                
                # Parse timestamp from ISO format e.g. 2026-10-24T12:30:00.000Z
                try:
                    ts = datetime.fromisoformat(created_time.replace("Z", "+00:00")).timestamp()
                except Exception:
                    ts = time.time()

                drive_files.append(DriveFile(file_id=file_id, name=name, size=size, created_time=created_time, timestamp=ts))

            page_token = response.get("nextPageToken", None)
            if not page_token:
                break

        # Sort oldest first (FIFO eviction)
        drive_files.sort(key=lambda f: f.timestamp)
        return drive_files

    def upload_file(
        self,
        local_path: Path,
        folder_name: str,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> DriveFile:
        """
        Uploads a local file to the Google Drive folder using resumable chunks.
        """
        folder_id = self.get_or_create_folder(folder_name)
        file_metadata = {
            "name": local_path.name,
            "parents": [folder_id]
        }

        # 5MB chunks for reliable resumable upload
        chunk_size = 5 * 1024 * 1024
        media = MediaFileUpload(str(local_path), resumable=True, chunksize=chunk_size)

        request = self.service.files().create(body=file_metadata, media_body=media, fields="id, name, size, createdTime")

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status and progress_callback:
                progress_callback(status.resumable_progress, local_path.stat().st_size)

        file_id = response.get("id")
        name = response.get("name")
        size = int(response.get("size", local_path.stat().st_size))
        created_time = response.get("createdTime", datetime.now().isoformat())
        ts = time.time()

        return DriveFile(file_id=file_id, name=name, size=size, created_time=created_time, timestamp=ts)

    def delete_file(self, file_id: str) -> bool:
        """Permanently deletes a file from Google Drive to free storage immediately."""
        try:
            self.service.files().delete(fileId=file_id).execute()
            return True
        except HttpError as e:
            print(f"[Drive] Failed to delete file {file_id}: {e}")
            return False
