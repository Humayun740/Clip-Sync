# 🎮 Passthru - Game Clip Cloud Sync & Rolling Storage Manager

**Passthru** is an automated desktop application and background utility that syncs your gaming clips (such as **SteelSeries GG Moments**) to Google Drive with an intelligent **rolling storage limit** (FIFO eviction), enabling seamless offline viewing on your Android phone.

---

## ✨ Features

- **Storage-Based Rolling Quota**: Set your desired cloud storage limit (e.g. 14.0 GB). The app will automatically fill the cloud storage, and when new clips are recorded, it purges the oldest clips from Google Drive to make room.
- **Local Files Are Safe**: Your original clips on your PC (e.g., in `D:\Clips\STEELSERIES MOMENTS`) are never deleted. Only the cloud copies are rotated.
- **Resumable Chunker**: Large clips (70 MB - 150 MB+) upload in 5 MB resumable chunks with progress feedback.
- **Dual Interfaces**:
  - **Modern Desktop GUI** (`PyQt5`): Live activity logs, cloud storage progress bar, manual sync trigger, and system tray minimization.
  - **Headless CLI / Background Daemon**: Run silently via Windows Task Scheduler or console.
- **End-to-End Android Offline Sync**: Pair with Android's *Autosync for Google Drive* or *FolderSync* in **Download Mirror** mode over Wi-Fi so new clips auto-download to your phone and deleted clips auto-purge from your phone without consuming cellular data.

---

## 📁 Directory Structure

```
c:\Users\Humayun\Desktop\passthru\
├── config.json              # App settings (folder path, storage limit in GB, interval)
├── core/
│   ├── config.py            # Configuration loader and validator
│   ├── scanner.py           # Scans and chronologically sorts local clips
│   ├── gdrive.py            # Google Drive API manager (OAuth, resumable upload, deletion, quota)
│   ├── sync_engine.py       # Core FIFO rolling storage eviction and sync engine
│   └── watcher.py           # Background periodic watcher
├── ui/
│   └── app_gui.py           # PyQt5 desktop dashboard & system tray integration
├── docs/
│   ├── GOOGLE_DRIVE_SETUP.md# 3-minute Google Cloud OAuth guide (one-time setup)
│   └── ANDROID_SETUP.md     # Step-by-step setup for Vanilla Android Wi-Fi sync
├── main.py                  # CLI & GUI entry point
├── run_gui.bat              # 1-click launcher for the Desktop App
├── setup_windows_scheduler.bat # Optional: Installs silent 30-min background sync
└── requirements.txt         # Python dependencies
```

---

## 🚀 Quick Start

### 1. One-Time Google Drive Credentials
Follow the instructions in [`docs/GOOGLE_DRIVE_SETUP.md`](docs/GOOGLE_DRIVE_SETUP.md) to obtain your free `credentials.json` from Google Cloud Console and place it into the `passthru` directory.

### 2. Launching the App
Double-click `run_gui.bat` or run:
```powershell
python main.py
```
- Click **"Connect Google Drive"** to authorize your account in the browser (only needed once; saved to `token.json`).
- Verify your settings (Clips Directory: `D:\Clips\STEELSERIES MOMENTS`, Storage Limit: e.g. `14.0 GB`).
- Click **"⚡ Sync Now"** or click **"▶ Start Auto-Watcher"**.

### 3. Setup Android Phone Sync
Follow [`docs/ANDROID_SETUP.md`](docs/ANDROID_SETUP.md) to set up **Autosync for Google Drive (DriveSync)** or **FolderSync** on your vanilla Android phone with **Download Mirror** on **Wi-Fi only**.
