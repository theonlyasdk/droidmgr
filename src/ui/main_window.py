"""Main window for the droidmgr GUI."""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import ctypes
from ctypes import wintypes
import os
import sys
from typing import Dict, List, Optional
from pathlib import Path
import threading
import re
import shutil
import zipfile
import queue
import tempfile
import hashlib
import stat
import json
import time
import datetime
from pathlib import PurePosixPath

from core import DeviceManager, ADBDeviceOfflineError, ADBDeviceNotFoundError
from .about_dialog import AboutDialog
from .preferences_dialog import PreferencesDialog
from .file_manager import FileManager
from .app_info_dialog import AppInfoDialog, ProcessInfoDialog
from .scrcpy_settings_dialog import ScrcpySettingsDialog
from .scrcpy_output_dialog import ScrcpyOutputDialog
from .scrcpy_overlay import ScrcpyOverlayToolbar
from .device_details_dialog import DeviceDetailsDialog
from .process_graph import ProcessHistoryWindow
from .forward_dialog import ForwardDialog
from .file_drop import enable_file_drop
from .logcat_view import LogcatView
from .shell_view import ShellView
from .network_inspector import NetworkInspector
from .capture import take_screenshot, record_screen
from .apk_extract import extract_apk
from .llm_report_dialog import LLMReportDialog, LLMReportProgressDialog
from .bugreport_dialog import BugReportDialog, BugReportProgressDialog
from .wireless_dialog import ConnectWirelesslyDialog
from .backup_dialog import BackupCancelToken, BackupOptionsDialog, BackupProgressDialog, RestoreSelectionDialog
from .taskbar_progress import TaskbarProgress
from .apk_install_progress import APKInstallProgressDialog
from .dpi import enable_dpi_awareness, setup_window_dpi, scale_size
from .misc_tab import MiscTab
from .tile_grid import TileGrid


from .main_devices import _DevicesTabMixin
from .main_processes import _ProcessesTabMixin
from .main_apps import _AppsTabMixin
from .main_app_grid import _AppGridMixin
from .main_app_icons import _AppIconsMixin
from .main_app_actions import _AppActionsMixin
from .main_mirror import _MirrorMixin
from .main_diag import _DiagMixin
from .main_backup import _BackupMixin
from .main_restore import _RestoreMixin
from .main_tabs import _TabsMixin
from .main_selection import _SelectionMixin
from .main_menu import _MenuMixin
from .main_utils import (_ProcessMemoryCounters, _get_process_memory_info,
    _kernel32, _MEMORY_LIMIT_BYTES)


class MainWindow(
    _DevicesTabMixin,
    _ProcessesTabMixin,
    _AppsTabMixin,
    _AppGridMixin,
    _AppIconsMixin,
    _AppActionsMixin,
    _MirrorMixin,
    _DiagMixin,
    _BackupMixin,
    _RestoreMixin,
    _TabsMixin,
    _SelectionMixin,
    _MenuMixin,
):
    """Main window (shell + notebook); feature code lives in main_*.py."""
    
    def __init__(self, adb_path=None, scrcpy_path=None):
        enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.title("droidmgr - Android Device Manager")
        setup_window_dpi(self.root, base_width=900, base_height=650, min_width=400, min_height=300)
        self.taskbar_progress = TaskbarProgress(self.root)
        
        self.adb_path = adb_path
        self.scrcpy_path = scrcpy_path
        
        try:
            self.device_manager = DeviceManager(adb_path, scrcpy_path)
        except Exception as e:
            messagebox.showerror("Initialization Error", 
                               f"Failed to initialize device manager:\n{e}\n\nPlease ensure scrcpy and adb are installed.")
            self.taskbar_progress.close()
            self.root.destroy()
            return
        
        self.selected_device: Optional[str] = None
        self.has_devices = False
        # Serials fastboot reports, which adb cannot see for itself.
        self._fastboot_devices: set = set()
        self._device_poll_job = None
        self._device_refresh_in_progress = False
        self._closing = False
        
        # Mirroring settings
        from core import ConfigManager
        self.config = ConfigManager()
        self._load_scrcpy_settings()
        
        self._create_ui()
        
        # Center main window on screen with DPI-scaled geometry
        setup_window_dpi(self.root, base_width=900, base_height=650, min_width=400, min_height=300)
            
        self._refresh_devices()
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        self._check_signals()
        self._enforce_memory_limit()

    def _enforce_memory_limit(self):
        """Hard-stop this process if its Windows working set exceeds 300 MiB."""
        if self._closing:
            return
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not _get_process_memory_info(
                _kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            # A hard limit cannot be enforced without a valid measurement.
            self._exit_for_memory_limit("The memory watchdog could not measure process memory.")
        if counters.WorkingSetSize >= _MEMORY_LIMIT_BYTES:
            self._exit_for_memory_limit(
                "droidmgr reached its 300 MiB memory limit and will now close.")
        self.root.after(1000, self._enforce_memory_limit)

    def _exit_for_memory_limit(self, reason):
        messagebox.showerror("droidmgr closing", reason, parent=self.root)
        os._exit(137)
    
    def _create_ui(self):
        self._create_menu()
        self._create_notebook()
        self._create_statusbar()
    
    
    def _create_notebook(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.devices_tab = self._create_devices_tab()
        self.processes_tab = self._create_processes_tab()
        self.apps_tab = self._create_apps_tab()
        
        # Initialize File Manager
        self.files_tab = ttk.Frame(self.notebook)
        self.file_manager = FileManager(
            self.files_tab,
            self.device_manager,
            self._set_status,
            self._show_error,
            self._require_device,
            view_mode_var=self.file_view_mode_var
        )

        # Initialize Logcat Viewer
        self.logcat_tab = ttk.Frame(self.notebook)
        self.logcat_view = LogcatView(
            self.logcat_tab,
            self.device_manager,
            self._set_status,
            self._show_error,
            self._require_device
        )

        # Initialize Interactive Shell
        self.shell_tab = ttk.Frame(self.notebook)
        self.shell_view = ShellView(
            self.shell_tab,
            self.device_manager,
            self._set_status,
            self._show_error,
            self._require_device
        )

        # Initialize Network Inspector
        self.network_tab = ttk.Frame(self.notebook)
        self.network_view = NetworkInspector(
            self.network_tab,
            device_id=None,
            device_manager=self.device_manager,
            set_status_callback=self._set_status,
            show_error_callback=self._show_error,
            require_device_callback=self._require_device,
            config=self.config
        )
        self.network_view.pack(fill=tk.BOTH, expand=True)

        # Initialize Misc / Developer Options Tab
        self.misc_tab = MiscTab(
            self.notebook,
            self.device_manager,
            lambda: self.selected_device,
            self._set_status
        )

        self.notebook.add(self.devices_tab, text="Devices")
        self.notebook.bind('<<NotebookTabChanged>>', self._on_tab_changed)

    
    def _create_statusbar(self):
        self.statusbar = ttk.Label(
            self.root,
            text="Ready",
            relief=tk.SUNKEN,
            anchor=tk.W
        )
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)
    
    
    def _update_button_states(self):
        has_selection = self.selected_device is not None
        is_ready = has_selection and self.device_manager.is_device_ready(self.selected_device)
        ready_state = tk.NORMAL if is_ready else tk.DISABLED
        sel_state = tk.NORMAL if has_selection else tk.DISABLED
        
        self.mirror_btn.config(state=ready_state)
        
        if has_selection:
            is_mirroring = self.device_manager.scrcpy.is_mirroring(self.selected_device)
            self._update_mirror_label(is_mirroring)
        
        if hasattr(self, 'connect_wireless_btn'):
            self.connect_wireless_btn.config(state=tk.NORMAL)

        self.refresh_processes_btn.config(state=sel_state)
        self.kill_process_btn.config(state=ready_state)
        self.copy_processes_btn.config(state=sel_state)
        self.refresh_apps_btn.config(state=sel_state)

        self.install_apk_btn.config(state=ready_state)
        
        self._update_fastboot_menu_state()
        
        # App specific buttons depend on both device readiness AND app selection
        self._update_app_button_states()
    

    def _update_app_button_states(self):
        has_device = self.selected_device is not None
        is_ready = has_device and self.device_manager.is_device_ready(self.selected_device)
        has_app_selection = self._get_selected_package() is not None
        
        ready_state = tk.NORMAL if is_ready else tk.DISABLED
        app_state = tk.NORMAL if (is_ready and has_app_selection) else tk.DISABLED
        
        self.start_app_btn.config(state=app_state)
        self.stop_app_btn.config(state=app_state)
        self.uninstall_app_btn.config(state=app_state)
        self.clear_cache_btn.config(state=app_state)
        self.extract_apk_btn.config(state=app_state)
        
        self.file_manager.update_button_states(ready_state)
        self.scrcpy_settings_btn.config(state=ready_state)
    
    def _set_status(self, message):
        self.statusbar.config(text=message)
    
    def _show_error(self, title, message):
        messagebox.showerror(title, message)
        self._set_status(f"Error: {title}")
    
    def _show_warning(self, message):
        messagebox.showwarning("Warning", message)
        self._set_status(f"Warning: {message}")
    
    def _show_info(self, message):
        messagebox.showinfo("Success", message)
        self._set_status(message)
    
    
    def _require_device(self, require_ready=True):
        if not self.selected_device:
            self._show_warning("Please select a device first")
            return False
        if require_ready:
            if not self.device_manager.is_device_ready(self.selected_device):
                status = None
                if hasattr(self.device_manager, 'get_device_status'):
                    status = self.device_manager.get_device_status(self.selected_device)
                status_str = status.lower() if status else 'offline'
                if status_str == 'unauthorized':
                    msg = f"Device '{self.selected_device}' is unauthorized.\nPlease accept the USB debugging prompt on the device screen."
                else:
                    msg = f"Device '{self.selected_device}' is offline.\nPlease reconnect the USB cable or restart ADB."
                self._show_warning(msg)
                return False
        return True
    

    def _check_signals(self):
        if getattr(self, '_closing', False):
            return
        # Periodically yield control back to the Python interpreter so it can process signals (like SIGINT/Ctrl+C) instantly
        self._signal_poll_job = self.root.after(100, self._check_signals)
    
    def _on_closing(self):
        if getattr(self, '_closing', False):
            return
        self._closing = True
        self._icon_extract_generation = getattr(self, '_icon_extract_generation', 0) + 1

        if getattr(self, '_device_poll_job', None) is not None:
            try:
                self.root.after_cancel(self._device_poll_job)
            except Exception:
                pass
            self._device_poll_job = None

        if getattr(self, '_signal_poll_job', None) is not None:
            try:
                self.root.after_cancel(self._signal_poll_job)
            except Exception:
                pass
            self._signal_poll_job = None

        # TileGrid widgets cancel their own resize/scroll timers on destroy.

        try:
            registry = getattr(getattr(self, 'device_manager', None), 'registry', None)
            if registry is not None:
                registry.save(force=True)
        except Exception:
            pass
        if hasattr(self, '_icon_pending_packages'):
            with self._icon_lock:
                self._icon_pending_packages.clear()

        try:
            self.taskbar_progress.close()
        except Exception:
            pass
        try:
            self.logcat_view.destroy()
        except Exception:
            pass
        try:
            self.shell_view.destroy()
        except Exception:
            pass
        try:
            self.device_manager.cleanup()
        except Exception:
            pass
        try:
            self.root.quit()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
    
    def run(self):
        try:
            self.root.mainloop()
        finally:
            try:
                self._on_closing()
            except Exception:
                pass
