import sys
import argparse
from pathlib import Path

from core.config import AppConfig
from core.gdrive import GoogleDriveManager
from core.sync_engine import SyncEngine
from core.watcher import SyncWatcher

BASE_DIR = Path(__file__).resolve().parent

def run_cli_sync(config: AppConfig, credentials_file: Path, token_file: Path):
    drive = GoogleDriveManager(credentials_file, token_file)
    engine = SyncEngine(config, drive)
    stats = engine.run_sync_cycle()
    print("\n--- Sync Summary ---")
    print(f"Uploaded: {stats.get('uploaded')} clips ({stats.get('bytes_uploaded', 0) / (1024**2):.1f} MB)")
    print(f"Evicted (Rolling deletion): {stats.get('evicted')} clips ({stats.get('bytes_evicted', 0) / (1024**2):.1f} MB)")
    print(f"Current Cloud Usage: {stats.get('cloud_size_gb', 0.0):.2f} / {config.storage_limit_gb:.1f} GB")
    print(f"Cloud Files Count: {stats.get('cloud_files_count', 0)}")
    if stats.get("errors"):
        print(f"Encountered {len(stats['errors'])} errors:")
        for err in stats["errors"]:
            print(f"  - {err}")

def run_cli_daemon(config: AppConfig, credentials_file: Path, token_file: Path):
    drive = GoogleDriveManager(credentials_file, token_file)
    engine = SyncEngine(config, drive)
    watcher = SyncWatcher(engine, interval_seconds=config.check_interval_seconds)
    print(f"Starting Passthru background daemon (interval: {config.check_interval_seconds}s, limit: {config.storage_limit_gb}GB)...")
    print("Press Ctrl+C to stop.")
    watcher.start()
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping daemon...")
        watcher.stop()
        print("Daemon stopped.")

def main():
    parser = argparse.ArgumentParser(description="Passthru - Game Clip Auto-Sync & Rolling Cloud Manager")
    parser.add_argument("--sync-once", action="store_true", help="Run a single sync cycle and exit (ideal for Task Scheduler)")
    parser.add_argument("--daemon", action="store_true", help="Run continuously in background console mode")
    parser.add_argument("--gui", action="store_true", help="Launch GUI interface (default if no flags)")
    parser.add_argument("--limit-gb", type=float, help="Override storage limit in GB")
    parser.add_argument("--folder", type=str, help="Override local clips directory")

    args = parser.parse_args()

    config = AppConfig.load()
    if args.limit_gb:
        config.storage_limit_gb = args.limit_gb
    if args.folder:
        config.local_clips_dir = args.folder

    credentials_file = BASE_DIR / "credentials.json"
    token_file = BASE_DIR / "token.json"

    if args.sync_once:
        run_cli_sync(config, credentials_file, token_file)
    elif args.daemon:
        run_cli_daemon(config, credentials_file, token_file)
    else:
        # Launch GUI by default
        try:
            from ui.app_gui import start_gui
            start_gui(BASE_DIR)
        except Exception as e:
            print(f"Failed to start GUI ({e}). Falling back to CLI sync...")
            run_cli_sync(config, credentials_file, token_file)

if __name__ == "__main__":
    main()
