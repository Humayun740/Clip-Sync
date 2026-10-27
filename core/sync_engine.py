import os
import json
import time
import msvcrt
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime

from googleapiclient.errors import HttpError
from core.config import AppConfig
from core.scanner import scan_local_clips, ClipInfo
from core.gdrive import GoogleDriveManager, DriveFile

BASE_DIR = Path(__file__).resolve().parent.parent
STATUS_FILE = BASE_DIR / "status.json"
LOG_FILE = BASE_DIR / "sync.log"
LOCK_FILE = BASE_DIR / "sync.lock"

SAFETY_BUFFER_BYTES = 500 * 1024 * 1024  # 500 MB safe margin below total Google Account limit

class CrossProcessLock:
    """Windows-native cross-process file lock using msvcrt."""
    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.handle = None

    def acquire(self) -> bool:
        try:
            self.handle = open(self.lock_path, "a+")
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            self.handle.truncate(0)
            self.handle.write(f"pid={os.getpid()}\ntime={time.time()}\n")
            self.handle.flush()
            return True
        except (IOError, OSError):
            if self.handle:
                try:
                    self.handle.close()
                except Exception:
                    pass
                self.handle = None
            return False

    def release(self):
        if self.handle:
            try:
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
                self.handle.close()
            except Exception:
                pass
            self.handle = None


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
        self.progress_callback = progress_callback
        self.is_running = False

    def log(self, msg: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"[{timestamp}] {msg}"
        self.log_callback(formatted)
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
            "retention_days": self.config.retention_days,
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
        Executes a deterministic, idempotent Top-K sync pass with cross-process concurrency locking:
        1. Acquires system-wide lock to prevent duplicate runs.
        2. Cleans Google Drive Trash.
        3. Scans local clips within retention window (e.g. last 60 days).
        4. Selects newest clips fitting within storage cap (Desired Cloud Set).
        5. Automatically cleans duplicates and prunes outdated cloud clips.
        6. Uploads remaining pending clips (newest first).
        7. Enters stable idle state.
        """
        if self.is_running:
            self.log("Sync already in progress in this instance. Skipping.")
            return {"status": "skipped", "reason": "in_progress"}

        lock = CrossProcessLock(LOCK_FILE)
        if not lock.acquire():
            self.log("Another sync cycle is actively running in the background. Skipping duplicate run.")
            return {"status": "skipped", "reason": "locked"}

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

            # 1. Clean Trash if any
            detailed_quota = self.drive.get_detailed_quota()
            trash_bytes = detailed_quota.get("usageInDriveTrash", 0)
            if trash_bytes > 0:
                self.log(f"[Cleanup] Found {trash_bytes / (1024**2):.1f} MB in Google Drive Trash. Emptying trash...")
                self.drive.empty_trash()
                detailed_quota = self.drive.get_detailed_quota()

            account_limit = detailed_quota.get("limit", 0)
            folder_name = self.config.drive_folder_name
            local_dir = self.config.local_clips_dir
            retention_days = self.config.retention_days
            limit_gb = self.config.storage_limit_gb

            # Storage cap
            effective_cap_bytes = self.config.storage_limit_bytes
            if account_limit > 0:
                safe_account_cap = max(0, account_limit - SAFETY_BUFFER_BYTES)
                effective_cap_bytes = min(effective_cap_bytes, safe_account_cap)

            self.log(
                f"Sync Policy: Retention = {retention_days} days | "
                f"Storage Limit = {limit_gb:.1f} GB | Folder: '{folder_name}'"
            )

            # 2. Scan Local Clips
            all_local_clips = scan_local_clips(
                local_dir,
                allowed_extensions=self.config.allowed_extensions,
                ignore_subfolders=self.config.ignore_subfolders
            )
            self.log(f"Discovered {len(all_local_clips)} local clips in '{local_dir}'.")

            # 3. Filter by Retention Days
            now = time.time()
            if retention_days > 0:
                cutoff = now - (retention_days * 86400)
                eligible_clips = [c for c in all_local_clips if c.timestamp >= cutoff]
                self.log(
                    f"Retention Filter: {len(eligible_clips)} / {len(all_local_clips)} clips "
                    f"are within the last {retention_days} days."
                )
            else:
                eligible_clips = all_local_clips

            # 4. Sort Eligible Clips NEWEST FIRST
            eligible_clips.sort(key=lambda c: c.timestamp, reverse=True)

            # 5. Build Desired Cloud Set (Newest first, fitting under storage cap)
            desired_clips: List[ClipInfo] = []
            accumulated_bytes = 0
            for clip in eligible_clips:
                if accumulated_bytes + clip.size <= effective_cap_bytes:
                    desired_clips.append(clip)
                    accumulated_bytes += clip.size
                else:
                    break

            desired_names = {c.name: c for c in desired_clips}
            self.log(
                f"Target Cloud Set: {len(desired_clips)} clips "
                f"({accumulated_bytes / (1024**3):.2f} / {limit_gb:.1f} GB)."
            )

            # 6. Fetch Existing Files from Google Drive & Deduplicate
            self._write_status("scanning", last_message="Inspecting Google Drive folder...")
            raw_cloud_files = self.drive.list_files_in_folder(folder_name)

            # Deduplicate cloud files if duplicate uploads occurred
            cloud_file_map: Dict[str, DriveFile] = {}
            duplicates_to_delete: List[DriveFile] = []
            for f in raw_cloud_files:
                if f.name in cloud_file_map:
                    duplicates_to_delete.append(f)
                else:
                    cloud_file_map[f.name] = f

            if duplicates_to_delete:
                self.log(f"[Deduplication] Removing {len(duplicates_to_delete)} duplicate file(s) in cloud...")
                for df in duplicates_to_delete:
                    self.drive.delete_file(df.file_id)
                self.drive.empty_trash()

            # 7. PRUNE: Remove any cloud file NOT in desired_clips
            files_to_delete = [f for f in cloud_file_map.values() if f.name not in desired_names]

            if files_to_delete:
                self.log(f"Found {len(files_to_delete)} cloud file(s) outside target retention or pushed out by newer clips. Pruning...")
                for f in files_to_delete:
                    self.log(f"[Pruning Cloud] Removing '{f.name}' ({f.size_mb:.1f} MB)...")
                    self._write_status("evicting", current_file=f.name, last_message=f"Pruning {f.name}...")
                    if self.drive.delete_file(f.file_id):
                        stats["evicted"] += 1
                        stats["bytes_evicted"] += f.size
                        cloud_file_map.pop(f.name, None)
                    else:
                        self.log(f"[Warning] Failed to delete cloud file '{f.name}'.")

                self.drive.empty_trash()

            # 8. UPLOAD: Upload any clip in desired_clips that is NOT yet on Drive (Newest First)
            clips_to_upload = [c for c in desired_clips if c.name not in cloud_file_map]

            if not clips_to_upload:
                self.log("All target clips are already in sync with Google Drive. (Idle)")
            else:
                self.log(f"Uploading {len(clips_to_upload)} pending clip(s) to Google Drive (newest first)...")
                for clip in clips_to_upload:
                    self.log(f"[Uploading] '{clip.name}' ({clip.size_mb:.1f} MB, {clip.formatted_time})...")

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
                                cloud_files_count=len(cloud_file_map),
                                cloud_size_gb=sum(f.size for f in cloud_file_map.values()) / (1024**3),
                                last_message=f"Uploading {clip.name} ({percent}%)"
                            )

                        uploaded_file = self.drive.upload_file(
                            clip.path,
                            folder_name,
                            progress_callback=upload_progress
                        )
                        cloud_file_map[uploaded_file.name] = uploaded_file
                        stats["uploaded"] += 1
                        stats["bytes_uploaded"] += uploaded_file.size
                        self.log(f"[Success] Uploaded '{clip.name}'.")

                    except Exception as e:
                        err_msg = f"Failed to upload '{clip.name}': {e}"
                        self.log(f"[Error] {err_msg}")
                        stats["errors"].append(err_msg)

            final_cloud_size = sum(f.size for f in cloud_file_map.values())
            stats["cloud_files_count"] = len(cloud_file_map)
            stats["cloud_size_gb"] = final_cloud_size / (1024 ** 3)
            self.log(
                f"=== Sync Completed. {stats['uploaded']} uploaded, {stats['evicted']} pruned. "
                f"Cloud has {stats['cloud_files_count']} clips ({stats['cloud_size_gb']:.2f} GB) ==="
            )

            self._write_status(
                status="idle",
                cloud_files_count=len(cloud_file_map),
                cloud_size_gb=stats["cloud_size_gb"],
                last_message="Sync completed. Idle."
            )

        except Exception as e:
            err = f"Sync cycle encountered an error: {e}"
            self.log(f"[Fatal] {err}")
            stats["errors"].append(err)
            self._write_status("error", last_message=err)
        finally:
            self.is_running = False
            lock.release()

        return stats
