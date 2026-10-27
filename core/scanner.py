import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

class ClipInfo:
    def __init__(self, path: Path, name: str, size: int, timestamp: float):
        self.path = path
        self.name = name
        self.size = size
        self.timestamp = timestamp  # Unix epoch timestamp

    @property
    def size_mb(self) -> float:
        return self.size / (1024 * 1024)

    @property
    def size_gb(self) -> float:
        return self.size / (1024 ** 3)

    @property
    def formatted_time(self) -> str:
        return datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d %H:%M:%S")

    def __repr__(self) -> str:
        return f"<Clip '{self.name}' ({self.size_mb:.1f} MB, {self.formatted_time})>"


def parse_clip_timestamp(file_path: Path) -> float:
    """
    Attempts to extract timestamp from filename (e.g., 'Alan-Wake-2__2026-09-24__10-00-42.mp4').
    Falls back to file creation/modification time.
    """
    match = re.search(r"(\d{4}-\d{2}-\d{2})__(\d{2}-\d{2}-\d{2})", file_path.name)
    if match:
        date_str, time_str = match.groups()
        time_str_clean = time_str.replace("-", ":")
        try:
            dt = datetime.strptime(f"{date_str} {time_str_clean}", "%Y-%m-%d %H:%M:%S")
            return dt.timestamp()
        except ValueError:
            pass

    try:
        # On Windows, st_ctime is file creation time
        stat = file_path.stat()
        return min(stat.st_ctime, stat.st_mtime)
    except Exception:
        return os.path.getmtime(file_path)


def scan_local_clips(
    folder_path: str,
    allowed_extensions: Optional[List[str]] = None,
    ignore_subfolders: Optional[List[str]] = None
) -> List[ClipInfo]:
    """
    Scans the given folder for clips, skipping ignored subfolders.
    Returns clips sorted chronologically (oldest to newest).
    """
    if allowed_extensions is None:
        allowed_extensions = [".mp4", ".mkv", ".mov", ".avi"]
    if ignore_subfolders is None:
        ignore_subfolders = ["Exported Clips", "Shared Clips"]

    allowed_ext_set = {ext.lower() for ext in allowed_extensions}
    ignore_set = {f.lower() for f in ignore_subfolders}

    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        print(f"[Scanner] Directory not found: {folder_path}")
        return []

    clips: List[ClipInfo] = []

    for item in folder.iterdir():
        if item.is_dir():
            # Skip ignored subfolders (and don't recurse unless configured)
            continue
        if item.is_file() and item.suffix.lower() in allowed_ext_set:
            try:
                size = item.stat().st_size
                timestamp = parse_clip_timestamp(item)
                clips.append(ClipInfo(path=item, name=item.name, size=size, timestamp=timestamp))
            except Exception as e:
                print(f"[Scanner] Error reading file {item.name}: {e}")

    # Sort oldest first so that when filling cloud space, they process chronologically
    clips.sort(key=lambda c: c.timestamp)
    return clips
