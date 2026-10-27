import os
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime

from core.config import AppConfig
from core.scanner import scan_local_clips, ClipInfo
from core.gdrive import GoogleDriveManager, DriveFile

BASE_DIR = Path(__file__).resolve().parent.parent
STATUS_FILE = BASE_DIR / "status.json"
LOG_FILE = BASE_DIR / "sync.log"

class SyncEngine:
    def __init__(
        self,
        config: AppConfig,
        drive_manager: GoogleDriveManager,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ):
        self.config = config
        self.drive = drive_manager
        self.log_callback = log_callback or (lambda msg: print(f"[SyncEngine] {msg}"))
        self.progress_callback = progress_callback  # (filename, current_bytes, total_bytes)
        self.is_running = False

    def log(self, msg: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"[{timestamp}] {msg}"
        self.log_callback(formatted)
        
        # Append to persistent sync.log file
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(formatted + "\n")
        except Exception:
            pass

    def _write_status(
        self,
        status: str,
        current_file: str = "",
        percent: int = 0,
        current_bytes: int = 0,
        total_bytes: int = 0,
        cloud_files_count: int = 0,
        cloud_size_gb: float = 0.0,
        last_message: str = ""
    ):
        """Writes live atomic status for GUI or other tools to inspect."""
        data = {
            "status": status,
            "pid": os.getpid(),
            "current_file": current_file,
            "percent": percent,
            "current_bytes": current_bytes,
            "total_bytes": total_bytes,
            "cloud_files_count": cloud_files_count,
            "cloud_size_gb": round(cloud_size_gb, 2),
            "cloud_limit_gb": self.config.storage_limit_gb,
            "last_updated": time.time(),
            "last_message": last_message
        }
        try:
            temp_file = BASE_DIR / "status.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_file.replace(STATUS_FILE)
        except Exception:
            pass

    def run_sync_cycle(self) -> Dict[str, Any]:
        """
        Executes one full sync pass:
        1. Queries Google Drive for current files & size.
        2. Enforces storage limit if already exceeded (user lowered limit).
        3. Identifies new local clips.
        4. Uploads new clips while evicting oldest cloud clips to stay within limit.
        """
        if self.is_running:
            self.log("Sync already in progress. Skipping cycle.")
            return {"status": "skipped", "reason": "in_progress"}

        self.is_running = True
        stats = {
            "uploaded": 0,
            "evicted": 0,
            "bytes_uploaded": 0,
            "bytes_evicted": 0,
            "cloud_files_count": 0,
            "cloud_size_gb": 0.0,
            "errors": []
        }

        try:
            self.log("=== Starting Clip Sync Cycle ===")
            self._write_status("authenticating", last_message="Checking Google Drive authentication...")

            if not self.drive.is_authenticated():
                self.log("Google Drive is not authenticated. Attempting authentication...")
                self.drive.authenticate(callback_prompt=self.log)

            limit_bytes = self.config.storage_limit_bytes
            limit_gb = self.config.storage_limit_gb
            folder_name = self.config.drive_folder_name
            local_dir = self.config.local_clips_dir

            self.log(f"Target Cloud Folder: '{folder_name}' | Storage Limit: {limit_gb:.1f} GB")
            self._write_status("scanning", last_message=f"Fetching files from Google Drive...")

            # 1. Fetch current cloud state
            cloud_files = self.drive.list_files_in_folder(folder_name)
            current_cloud_size = sum(f.size for f in cloud_files)
            cloud_file_names = {f.name for f in cloud_files}

            cloud_size_gb = current_cloud_size / (1024 ** 3)
            self.log(
                f"Cloud status: {len(cloud_files)} files | "
                f"{cloud_size_gb:.2f} / {limit_gb:.1f} GB used"
            )
            self._write_status(
                "scanning",
                cloud_files_count=len(cloud_files),
                cloud_size_gb=cloud_size_gb,
                last_message=f"Cloud status: {len(cloud_files)} files ({cloud_size_gb:.2f} GB)"
            )

            # 2. If existing cloud size exceeds limit (e.g. user lowered limit), evict oldest first
            while cloud_files and current_cloud_size > limit_bytes:
                oldest = cloud_files.pop(0)
                msg = f"[Pruning Overlimit] Evicting oldest file '{oldest.name}' ({oldest.size_mb:.1f} MB)..."
                self.log(msg)
                self._write_status("evicting", current_file=oldest.name, last_message=msg)

                if self.drive.delete_file(oldest.file_id):
                    current_cloud_size -= oldest.size
                    cloud_file_names.discard(oldest.name)
                    stats["evicted"] += 1
                    stats["bytes_evicted"] += oldest.size

            # 3. Scan local clips
            local_clips = scan_local_clips(
                local_dir,
                allowed_extensions=self.config.allowed_extensions,
                ignore_subfolders=self.config.ignore_subfolders
            )
            self.log(f"Discovered {len(local_clips)} local clips in '{local_dir}'.")

            # 4. Find pending clips to upload
            pending_clips = [c for c in local_clips if c.name not in cloud_file_names]

            if not pending_clips:
                self.log("All local clips are already in sync with Google Drive.")
            else:
                self.log(f"Found {len(pending_clips)} new clip(s) to upload.")

                # Process pending clips chronologically
                for clip in pending_clips:
                    clip_size = clip.size
                    if clip_size > limit_bytes:
                        self.log(f"[Warning] Clip '{clip.name}' ({clip.size_gb:.2f} GB) exceeds total storage limit. Skipping.")
                        continue

                    # FIFO Eviction: While adding this clip would exceed limit, delete oldest cloud clip
                    while cloud_files and (current_cloud_size + clip_size > limit_bytes):
                        oldest = cloud_files.pop(0)
                        evict_msg = (
                            f"[Auto-Evict] Space needed for '{clip.name}'. "
                            f"Deleting oldest cloud clip '{oldest.name}' ({oldest.size_mb:.1f} MB)..."
                        )
                        self.log(evict_msg)
                        self._write_status("evicting", current_file=oldest.name, last_message=evict_msg)

                        if self.drive.delete_file(oldest.file_id):
                            current_cloud_size -= oldest.size
                            cloud_file_names.discard(oldest.name)
                            stats["evicted"] += 1
                            stats["bytes_evicted"] += oldest.size
                        else:
                            self.log(f"[Error] Could not delete cloud file '{oldest.name}'. Aborting cycle.")
                            break

                    # Check if enough room was made
                    if current_cloud_size + clip_size > limit_bytes:
                        self.log(f"[Warning] Storage limit exceeded even after eviction. Skipping '{clip.name}'.")
                        continue

                    # Upload new clip
                    self.log(f"[Uploading] '{clip.name}' ({clip.size_mb:.1f} MB)...")
                    try:
                        def upload_progress(current, total):
                            percent = int((current / total) * 100) if total > 0 else 0
                            if self.progress_callback:
                                self.progress_callback(clip.name, current, total)
                            self._write_status(
                                status="uploading",
                                current_file=clip.name,
                                percent=percent,
                                current_bytes=current,
                                total_bytes=total,
                                cloud_files_count=len(cloud_files),
                                cloud_size_gb=current_cloud_size / (1024 ** 3),
                                last_message=f"Uploading {clip.name} ({percent}%)"
                            )

                        uploaded_file = self.drive.upload_file(
                            clip.path,
                            folder_name,
                            progress_callback=upload_progress
                        )
                        cloud_files.append(uploaded_file)
                        cloud_file_names.add(uploaded_file.name)
                        current_cloud_size += uploaded_file.size
                        stats["uploaded"] += 1
                        stats["bytes_uploaded"] += uploaded_file.size

                        succ_msg = (
                            f"[Success] Uploaded '{clip.name}'. "
                            f"Cloud usage: {current_cloud_size / (1024 ** 3):.2f} / {limit_gb:.1f} GB."
                        )
                        self.log(succ_msg)

                        if self.config.delete_local_after_upload:
                            try:
                                clip.path.unlink()
                                self.log(f"[Local Cleanup] Deleted local source file '{clip.name}'.")
                            except Exception as e:
                                self.log(f"[Warning] Could not delete local file: {e}")

                    except Exception as e:
                        err_msg = f"Failed to upload '{clip.name}': {e}"
                        self.log(f"[Error] {err_msg}")
                        stats["errors"].append(err_msg)

            stats["cloud_files_count"] = len(cloud_files)
            stats["cloud_size_gb"] = current_cloud_size / (1024 ** 3)
            self.log(f"=== Sync Completed. {stats['uploaded']} uploaded, {stats['evicted']} evicted. Cloud: {stats['cloud_size_gb']:.2f} GB ===")

            self._write_status(
                status="idle",
                cloud_files_count=len(cloud_files),
                cloud_size_gb=stats["cloud_size_gb"],
                last_message="Sync completed successfully. Idle."
            )

        except Exception as e:
            err = f"Sync cycle encountered an error: {e}"
            self.log(f"[Fatal] {err}")
            stats["errors"].append(err)
            self._write_status("error", last_message=err)
        finally:
            self.is_running = False

        return stats
