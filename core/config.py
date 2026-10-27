import json
import os
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import List

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"

@dataclass
class AppConfig:
    local_clips_dir: str = r"D:\Clips\STEELSERIES MOMENTS"
    drive_folder_name: str = "SteelSeries_Clips"
    storage_limit_gb: float = 13.0
    retention_days: int = 14  # Only sync clips created in the last N days (0 to disable)
    allowed_extensions: List[str] = field(default_factory=lambda: [".mp4", ".mkv", ".mov", ".avi"])
    ignore_subfolders: List[str] = field(default_factory=lambda: ["Exported Clips", "Shared Clips"])
    check_interval_seconds: int = 1800
    auto_sync: bool = True
    delete_local_after_upload: bool = False

    @property
    def storage_limit_bytes(self) -> int:
        return int(self.storage_limit_gb * (1024 ** 3))

    @classmethod
    def load(cls) -> "AppConfig":
        if not CONFIG_FILE.exists():
            default_config = cls()
            default_config.save()
            return default_config
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Filter valid fields for dataclass compatibility
            valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
            filtered_data = {k: v for k, v in data.items() if k in valid_keys}
            return cls(**filtered_data)
        except Exception as e:
            print(f"[Config] Error loading {CONFIG_FILE}: {e}. Using defaults.")
            return cls()

    def save(self) -> None:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=4)
        except Exception as e:
            print(f"[Config] Error saving {CONFIG_FILE}: {e}")
