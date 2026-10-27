import sys
import os
import json
import time
import ctypes
import threading
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QDoubleSpinBox, QSpinBox,
    QProgressBar, QTextEdit, QFileDialog, QGroupBox, QMessageBox,
    QSystemTrayIcon, QMenu, QAction, QStyle
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt5.QtGui import QIcon, QFont, QTextCursor

from core.config import AppConfig
from core.gdrive import GoogleDriveManager
from core.sync_engine import SyncEngine, STATUS_FILE, LOG_FILE
from core.watcher import SyncWatcher

def is_pid_running(pid: int) -> bool:
    """Checks whether a given Windows PID is currently running."""
    if pid <= 0:
        return False
    try:
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        return False


class GuiLogSignals(QObject):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(str, int, int)
    sync_finished = pyqtSignal(dict)
    auth_status_signal = pyqtSignal(bool)


class PassthruMainWindow(QMainWindow):
    def __init__(self, config_dir: Path):
        super().__init__()
        self.config_dir = config_dir
        self.config = AppConfig.load()
        self.credentials_file = config_dir / "credentials.json"
        self.token_file = config_dir / "token.json"
        self.last_log_seek_pos = 0

        self.signals = GuiLogSignals()
        self.signals.log_signal.connect(self.append_log)
        self.signals.progress_signal.connect(self.update_upload_progress)
        self.signals.sync_finished.connect(self.on_sync_finished)
        self.signals.auth_status_signal.connect(self.update_auth_ui)

        self.drive = GoogleDriveManager(self.credentials_file, self.token_file)
        self.engine = SyncEngine(
            self.config,
            self.drive,
            log_callback=self.signals.log_signal.emit,
            progress_callback=self.signals.progress_signal.emit
        )
        self.watcher = SyncWatcher(self.engine, interval_seconds=self.config.check_interval_seconds)

        self.init_ui()
        self.init_tray()
        self.check_auth_status()

        # Load existing sync.log history
        self.load_initial_log_history()

        # Timer to poll background status & tail sync.log
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.poll_background_status)
        self.status_timer.start(1000)

    def init_ui(self):
        self.setWindowTitle("Passthru - Game Clip Auto-Sync & Rolling Cloud")
        self.resize(780, 680)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(12)

        # 1. Header & Auth Status Bar
        header_layout = QHBoxLayout()
        title_label = QLabel("🎮 Passthru Clip Sync")
        title_font = QFont("Segoe UI", 16, QFont.Bold)
        title_label.setFont(title_font)
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        self.auth_badge = QLabel("Checking Google Drive...")
        self.auth_badge.setStyleSheet("padding: 4px 10px; border-radius: 4px; font-weight: bold; background-color: #555; color: white;")
        header_layout.addWidget(self.auth_badge)

        self.btn_auth = QPushButton("Connect Google Drive")
        self.btn_auth.clicked.connect(self.handle_auth)
        header_layout.addWidget(self.btn_auth)

        main_layout.addLayout(header_layout)

        # 2. Configuration Group
        config_group = QGroupBox("Configuration & Storage Limit")
        config_layout = QVBoxLayout(config_group)

        # Local clips folder
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel("Clips Directory:"))
        self.txt_local_dir = QLineEdit(self.config.local_clips_dir)
        folder_layout.addWidget(self.txt_local_dir)
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self.browse_folder)
        folder_layout.addWidget(btn_browse)
        config_layout.addLayout(folder_layout)

        # Storage Limit & Cloud Folder
        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("Google Drive Folder:"))
        self.txt_drive_folder = QLineEdit(self.config.drive_folder_name)
        settings_row.addWidget(self.txt_drive_folder)

        settings_row.addWidget(QLabel("Storage Limit (GB):"))
        self.spin_limit_gb = QDoubleSpinBox()
        self.spin_limit_gb.setRange(0.5, 2000.0)
        self.spin_limit_gb.setSingleStep(0.5)
        self.spin_limit_gb.setValue(self.config.storage_limit_gb)
        self.spin_limit_gb.setToolTip("Oldest clips in Google Drive are automatically replaced when this limit is reached.")
        settings_row.addWidget(self.spin_limit_gb)

        settings_row.addWidget(QLabel("Check Every (Min):"))
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(1, 1440)
        self.spin_interval.setValue(max(1, self.config.check_interval_seconds // 60))
        settings_row.addWidget(self.spin_interval)

        btn_save = QPushButton("Save Settings")
        btn_save.setStyleSheet("background-color: #0078d4; color: white; font-weight: bold; padding: 4px 12px;")
        btn_save.clicked.connect(self.save_settings)
        settings_row.addWidget(btn_save)

        config_layout.addLayout(settings_row)
        main_layout.addWidget(config_group)

        # 3. Status & Progress Section
        status_group = QGroupBox("Cloud Storage & Sync Status")
        status_layout = QVBoxLayout(status_group)

        storage_row = QHBoxLayout()
        self.lbl_storage_info = QLabel(f"Cloud Storage Limit: {self.config.storage_limit_gb:.1f} GB")
        storage_row.addWidget(self.lbl_storage_info)
        storage_row.addStretch()
        self.lbl_cloud_file_count = QLabel("Cloud Files: Unknown")
        storage_row.addWidget(self.lbl_cloud_file_count)
        status_layout.addLayout(storage_row)

        self.bar_storage = QProgressBar()
        self.bar_storage.setRange(0, 100)
        self.bar_storage.setValue(0)
        self.bar_storage.setTextVisible(True)
        self.bar_storage.setFormat("Storage Used: %p%")
        status_layout.addWidget(self.bar_storage)

        upload_row = QHBoxLayout()
        self.lbl_upload_status = QLabel("Status: Idle")
        upload_row.addWidget(self.lbl_upload_status)
        status_layout.addLayout(upload_row)

        self.bar_upload = QProgressBar()
        self.bar_upload.setRange(0, 100)
        self.bar_upload.setValue(0)
        self.bar_upload.setTextVisible(True)
        self.bar_upload.setFormat("Upload Progress: %p%")
        status_layout.addWidget(self.bar_upload)

        main_layout.addWidget(status_group)

        # 4. Action Buttons
        actions_layout = QHBoxLayout()

        self.btn_sync_now = QPushButton("⚡ Sync Now")
        self.btn_sync_now.setStyleSheet("font-size: 14px; font-weight: bold; padding: 8px 16px; background-color: #107c41; color: white;")
        self.btn_sync_now.clicked.connect(self.trigger_sync_now)
        actions_layout.addWidget(self.btn_sync_now)

        self.btn_watcher_toggle = QPushButton("▶ Start Auto-Watcher")
        self.btn_watcher_toggle.setStyleSheet("font-size: 14px; font-weight: bold; padding: 8px 16px; background-color: #2b579a; color: white;")
        self.btn_watcher_toggle.clicked.connect(self.toggle_watcher)
        actions_layout.addWidget(self.btn_watcher_toggle)

        btn_clear_log = QPushButton("Clear Log")
        btn_clear_log.clicked.connect(lambda: self.log_box.clear())
        actions_layout.addWidget(btn_clear_log)

        main_layout.addLayout(actions_layout)

        # 5. Live Activity Log
        log_label = QLabel("Live Activity Log:")
        main_layout.addWidget(log_label)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; font-family: Consolas, monospace; font-size: 11px;")
        main_layout.addWidget(self.log_box)

    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_DriveHDIcon))
        self.tray_icon.setToolTip("Passthru - Game Clip Sync")

        tray_menu = QMenu()
        show_action = QAction("Open Passthru Window", self)
        show_action.triggered.connect(self.restore_window)
        tray_menu.addAction(show_action)

        sync_action = QAction("Sync Now", self)
        sync_action.triggered.connect(self.trigger_sync_now)
        tray_menu.addAction(sync_action)

        tray_menu.addSeparator()
        exit_action = QAction("Exit Completely", self)
        exit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(exit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger):
            self.restore_window()

    def restore_window(self):
        self.showNormal()
        self.activateWindow()

    def load_initial_log_history(self):
        if LOG_FILE.exists():
            try:
                with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    # Show last 100 lines
                    recent = lines[-100:]
                    self.log_box.setPlainText("".join(recent))
                    self.log_box.moveCursor(QTextCursor.End)
                    self.last_log_seek_pos = f.tell()
            except Exception:
                pass

    def poll_background_status(self):
        # 1. Tail sync.log for new lines
        if LOG_FILE.exists():
            try:
                with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    f.seek(self.last_log_seek_pos)
                    new_content = f.read()
                    if new_content:
                        self.log_box.append(new_content.strip())
                        self.log_box.moveCursor(QTextCursor.End)
                        self.last_log_seek_pos = f.tell()
            except Exception:
                pass

        # 2. Check status.json
        if not STATUS_FILE.exists():
            return

        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            pid = data.get("pid", 0)
            status = data.get("status", "idle")
            last_updated = data.get("last_updated", 0)
            is_active = (time.time() - last_updated < 15) and is_pid_running(pid)

            cloud_files_count = data.get("cloud_files_count", 0)
            cloud_size_gb = data.get("cloud_size_gb", 0.0)
            limit_gb = self.config.storage_limit_gb

            # Update storage meters
            if cloud_files_count > 0 or cloud_size_gb > 0:
                self.lbl_cloud_file_count.setText(f"Cloud Files: {cloud_files_count}")
                percent = int(min(100, (cloud_size_gb / limit_gb) * 100)) if limit_gb > 0 else 0
                self.bar_storage.setValue(percent)
                self.bar_storage.setFormat(f"Cloud Used: {cloud_size_gb:.2f} / {limit_gb:.1f} GB ({percent}%)")

            # If background process is uploading
            if is_active and pid != os.getpid() and status in ("uploading", "scanning", "evicting", "authenticating"):
                current_file = data.get("current_file", "")
                upload_percent = data.get("percent", 0)
                msg = data.get("last_message", "")

                self.btn_sync_now.setEnabled(False)
                self.btn_sync_now.setText(f"Syncing in Background (PID {pid})...")
                self.lbl_upload_status.setText(f"Status: {msg}")
                self.bar_upload.setValue(upload_percent)
            elif not self.engine.is_running:
                self.btn_sync_now.setEnabled(True)
                self.btn_sync_now.setText("⚡ Sync Now")
                if status == "idle" and self.lbl_upload_status.text().startswith("Status: Background"):
                    self.lbl_upload_status.setText("Status: Idle (All in sync)")
                    self.bar_upload.setValue(0)

        except Exception:
            pass

    def check_auth_status(self):
        threading.Thread(target=self._check_auth_worker, daemon=True).start()

    def _check_auth_worker(self):
        is_auth = self.drive.is_authenticated()
        self.signals.auth_status_signal.emit(is_auth)

    def update_auth_ui(self, is_auth: bool):
        if is_auth:
            self.auth_badge.setText("● Connected to Google Drive")
            self.auth_badge.setStyleSheet("padding: 4px 10px; border-radius: 4px; font-weight: bold; background-color: #107c41; color: white;")
            self.btn_auth.setText("Reconnect Account")
        else:
            self.auth_badge.setText("○ Not Connected")
            self.auth_badge.setStyleSheet("padding: 4px 10px; border-radius: 4px; font-weight: bold; background-color: #d83b01; color: white;")
            self.btn_auth.setText("Connect Google Drive")

    def handle_auth(self):
        if not self.credentials_file.exists():
            QMessageBox.warning(
                self,
                "Credentials Required",
                f"Google OAuth credentials file was not found at:\n{self.credentials_file}\n\n"
                "Please follow the setup guide (GOOGLE_DRIVE_SETUP.md) to place credentials.json in this folder."
            )
            return

        def auth_thread():
            try:
                self.signals.log_signal.emit("Starting Google Drive authorization in browser...")
                self.drive.authenticate(callback_prompt=self.signals.log_signal.emit)
                self.signals.auth_status_signal.emit(True)
                self.signals.log_signal.emit("Google Drive authorization successful!")
            except Exception as e:
                self.signals.log_signal.emit(f"Authentication failed: {e}")
                self.signals.auth_status_signal.emit(False)

        threading.Thread(target=auth_thread, daemon=True).start()

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select SteelSeries Clips Folder", self.txt_local_dir.text())
        if folder:
            self.txt_local_dir.setText(folder)

    def save_settings(self):
        self.config.local_clips_dir = self.txt_local_dir.text().strip()
        self.config.drive_folder_name = self.txt_drive_folder.text().strip()
        self.config.storage_limit_gb = float(self.spin_limit_gb.value())
        self.config.check_interval_seconds = int(self.spin_interval.value() * 60)
        self.config.save()

        self.engine.config = self.config
        self.watcher.interval_seconds = self.config.check_interval_seconds
        self.lbl_storage_info.setText(f"Cloud Storage Limit: {self.config.storage_limit_gb:.1f} GB")

        self.append_log(f"Settings saved: Storage Limit = {self.config.storage_limit_gb:.1f} GB, Interval = {self.config.check_interval_seconds // 60} mins.")
        QMessageBox.information(self, "Settings Saved", "Configuration updated successfully!")

    def append_log(self, text: str):
        self.log_box.append(text)
        self.log_box.moveCursor(QTextCursor.End)

    def update_upload_progress(self, filename: str, current_bytes: int, total_bytes: int):
        percent = int((current_bytes / total_bytes) * 100) if total_bytes > 0 else 0
        self.bar_upload.setValue(percent)
        self.lbl_upload_status.setText(f"Uploading {filename} ({percent}% - {current_bytes // (1024*1024)}/{total_bytes // (1024*1024)} MB)")

    def trigger_sync_now(self):
        if self.engine.is_running:
            self.append_log("Sync already in progress.")
            return

        self.btn_sync_now.setEnabled(False)
        self.lbl_upload_status.setText("Status: Syncing...")

        def sync_worker():
            stats = self.engine.run_sync_cycle()
            self.signals.sync_finished.emit(stats)

        threading.Thread(target=sync_worker, daemon=True).start()

    def on_sync_finished(self, stats: dict):
        self.btn_sync_now.setEnabled(True)
        self.bar_upload.setValue(0)
        self.lbl_upload_status.setText("Status: Idle")

        cloud_size_gb = stats.get("cloud_size_gb", 0.0)
        limit_gb = self.config.storage_limit_gb
        percent = int(min(100, (cloud_size_gb / limit_gb) * 100)) if limit_gb > 0 else 0

        self.bar_storage.setValue(percent)
        self.bar_storage.setFormat(f"Cloud Used: {cloud_size_gb:.2f} / {limit_gb:.1f} GB ({percent}%)")
        self.lbl_cloud_file_count.setText(f"Cloud Files: {stats.get('cloud_files_count', 0)}")

    def toggle_watcher(self):
        if self.watcher.is_running():
            self.watcher.stop()
            self.btn_watcher_toggle.setText("▶ Start Auto-Watcher")
            self.btn_watcher_toggle.setStyleSheet("font-size: 14px; font-weight: bold; padding: 8px 16px; background-color: #2b579a; color: white;")
        else:
            self.watcher.start()
            self.btn_watcher_toggle.setText("⏹ Stop Auto-Watcher")
            self.btn_watcher_toggle.setStyleSheet("font-size: 14px; font-weight: bold; padding: 8px 16px; background-color: #d83b01; color: white;")

    def quit_app(self):
        if self.watcher.is_running():
            self.watcher.stop()
        if hasattr(self, 'status_timer'):
            self.status_timer.stop()
        QApplication.quit()

    def closeEvent(self, event):
        """Minimize to system tray on window close so it doesn't interrupt background sync."""
        if self.tray_icon.isVisible():
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                "Passthru Running in Background",
                "Passthru has been minimized to your system tray. Double-click the tray icon anytime to view progress.",
                QSystemTrayIcon.Information,
                2000
            )
        else:
            event.accept()
            self.quit_app()


def start_gui(config_dir: Path):
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = PassthruMainWindow(config_dir)
    window.show()
    sys.exit(app.exec_())
