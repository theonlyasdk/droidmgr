"""Main window for the droidmgr GUI."""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
from typing import Dict, List, Optional
from pathlib import Path
import threading
import re
import shutil
import zipfile
import queue
import tempfile
import stat
import json
from pathlib import PurePosixPath

from core import DeviceManager, ADBDeviceOfflineError, ADBDeviceNotFoundError
from .about_dialog import AboutDialog
from .preferences_dialog import PreferencesDialog
from .file_manager import FileManager
from .app_info_dialog import AppInfoDialog, ProcessInfoDialog
from .scrcpy_settings_dialog import ScrcpySettingsDialog
from .scrcpy_output_dialog import ScrcpyOutputDialog
from .device_details_dialog import DeviceDetailsDialog
from .forward_dialog import ForwardDialog
from .file_drop import enable_file_drop
from .logcat_view import LogcatView
from .shell_view import ShellView
from .capture import take_screenshot, record_screen
from .apk_extract import extract_apk
from .llm_report_dialog import LLMReportDialog, LLMReportProgressDialog
from .wireless_dialog import ConnectWirelesslyDialog
from .backup_dialog import BackupCancelToken, BackupOptionsDialog, BackupProgressDialog, RestoreSelectionDialog
from .taskbar_progress import TaskbarProgress
from .apk_install_progress import APKInstallProgressDialog
from .dpi import enable_dpi_awareness, setup_window_dpi, scale_size


_OFFLINE_ERROR_KEYWORDS = [
    'device offline', 'offline or unauthorized', 'device not found',
    'no devices/emulators found', 'disconnected', 'closed', 'unauthorized'
]

# The permission names a device quotes when it refuses to let adb wipe an app.
_CLEAR_DENIED_KEYWORDS = ['clear_app_user_data', 'clear_app_cache']

_CLEAR_DENIED_MESSAGE = (
    "This device does not let apps be cleared over adb.\n\n"
    "Its Android build withholds android.permission.CLEAR_APP_USER_DATA from the "
    "shell user, so the request is refused. Reaching app data on such a device "
    "needs root."
)

_MEMORY_UNITS = {
    'B': 1,
    'KB': 1024,
    'MB': 1024 * 1024,
    'GB': 1024 * 1024 * 1024
}

CORE_SYSTEM_PACKAGES = {
    'com.android.settings', 'com.android.systemui', 'com.android.launcher',
    'com.android.launcher3', 'com.google.android.apps.nexuslauncher',
    'com.google.android.gms', 'com.android.vending', 'com.android.packageinstaller',
    'com.google.android.packageinstaller', 'com.android.phone', 'com.android.providers.telephony',
    'com.android.shell', 'com.android.bluetooth', 'com.android.camera2', 'com.android.keychain',
    'com.android.location.fused', 'com.android.nfc', 'com.android.se', 'com.android.inputmethod.latin'
}

SYSTEM_APP_PATHS = ('/system', '/product', '/vendor', '/system_ext', '/odm', '/apex')

# Times (ms) to refresh the device list after a reboot or an adb reconnect, while
# the device is still coming back.
_RECONNECT_POLL_DELAYS = (8000, 20000, 35000)

# Power menu actions: the label shown to the user, the adb reboot target (None for
# a normal reboot or a shutdown), and the detail shown in the confirmation prompt.
_POWER_ACTIONS = {
    'reboot': ('Reboot', None, 'The device will restart normally.'),
    'recovery': ('Reboot to Recovery', 'recovery', 'The device will restart into recovery.'),
    'bootloader': ('Reboot to Bootloader', 'bootloader',
                   'The device will restart into the bootloader (fastboot) mode, '
                   'where adb cannot talk to it.'),
    'shutdown': ('Shut Down', None, 'The device will power off and must be turned on by hand.'),
}


def _looks_like_system_package(package: str, app_path: str = '') -> bool:
    """Whether a package sits in a system image or is a known core app."""
    if app_path and app_path.startswith(SYSTEM_APP_PATHS):
        return True
    return (package in CORE_SYSTEM_PACKAGES
            or package.startswith(('com.android.', 'com.google.android.')))


def _is_offline_error(msg: str) -> bool:
    """Whether an exception message describes an unreachable or unauthorized device."""
    lower_msg = msg.lower()
    return any(keyword in lower_msg for keyword in _OFFLINE_ERROR_KEYWORDS)


def _is_clear_denied(msg: str) -> bool:
    """Whether an exception message is the device refusing to wipe an app."""
    lower_msg = msg.lower()
    return any(keyword in lower_msg for keyword in _CLEAR_DENIED_KEYWORDS)


def _format_bytes(num_bytes: int) -> str:
    """Render a byte count as a short human-readable size such as '12.4 MB'."""
    size = float(num_bytes or 0)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            if unit == 'B':
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _app_sort_key(app: dict, col: str):
    """Sort key for one app entry, keyed by the app list's column name.

    Sorting happens on the raw values rather than the rendered cells so that
    Size orders by exact bytes instead of the rounded '4.6 MB' text.
    """
    if col == 'Size':
        return app.get('size_bytes', 0)
    return str(app.get(col.lower(), '') or '').lower()


def _parse_memory(val: str) -> int:
    """Parse a process memory string such as '12.5 MB' into a byte count."""
    parts = str(val).split()
    num = float(parts[0])
    unit = parts[1].upper() if len(parts) > 1 else 'B'
    return int(num * _MEMORY_UNITS.get(unit, 1))


class MainWindow:
    
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
    
    def _create_ui(self):
        self._create_menu()
        self._create_notebook()
        self._create_statusbar()
    
    def _create_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Preferences", command=self._show_preferences)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_closing)
        
        device_menu = tk.Menu(menubar, tearoff=0)
        self.device_menu = device_menu
        menubar.add_cascade(label="Device", menu=device_menu)
        device_menu.add_command(label="Refresh Devices", command=self._refresh_devices)
        device_menu.add_separator()
        device_menu.add_command(label="Start Mirroring", command=self._toggle_mirroring)
        self.mirror_menu_index = device_menu.index('end')
        device_menu.add_separator()
        device_menu.add_command(label="Connect Wirelessly...", command=self._show_connect_wireless_dialog)
        device_menu.add_command(label="Disconnect Wireless Device", command=self._disconnect_wireless_device)
        device_menu.add_separator()
        device_menu.add_command(label="Reboot", command=lambda: self._power_action('reboot'))
        device_menu.add_command(label="Reboot to Recovery", command=lambda: self._power_action('recovery'))
        device_menu.add_command(label="Reboot to Bootloader", command=lambda: self._power_action('bootloader'))
        device_menu.add_command(label="Shut Down", command=lambda: self._power_action('shutdown'))
        device_menu.add_separator()
        device_menu.add_command(label="Check Root Access", command=self._check_root_access)
        device_menu.add_command(label="Reconnect ADB", command=self._reconnect_adb)
        device_menu.add_separator()
        device_menu.add_command(label="Backup to archive...", command=self._backup_to_archive)
        device_menu.add_command(label="Restore from backup...", command=self._restore_from_backup)
        device_menu.add_separator()
        device_menu.add_command(label="Generate LLM Report", command=self._generate_llm_report)

        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Take Screenshot", command=self._take_screenshot)
        tools_menu.add_command(label="Record Screen...", command=self._record_screen)
        tools_menu.add_separator()
        tools_menu.add_command(label="Port Forwarding...", command=self._show_forward_dialog)

        
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self._show_about)
    
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
            self._require_device
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
    
    def _create_devices_tab(self):
        tab = ttk.Frame(self.notebook)
        
        list_frame = ttk.LabelFrame(tab, text="Connected Devices")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        columns = ('ID', 'Model', 'Status', 'Mirroring')
        self.device_tree = ttk.Treeview(list_frame, columns=columns, show='tree headings')
        
        self.device_tree.heading('#0', text='#')
        for col in columns:
            self.device_tree.heading(col, text=col)
            self.device_tree.column(col, width=scale_size(200, self.root))
        self.device_tree.column('#0', width=scale_size(50, self.root))
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.device_tree.yview)
        self.device_tree.configure(yscrollcommand=scrollbar.set)
        self.device_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.device_tree.bind('<<TreeviewSelect>>', self._on_device_select)
        self.device_tree.bind('<Double-1>', self._on_device_double_click)
        self.device_tree.bind('<Button-3>', self._show_device_context_menu)
        self.device_tree.bind('<Button-2>', self._show_device_context_menu)
        
        self.no_devices_frame = ttk.Frame(list_frame)
        
        title_label = tk.Label(self.no_devices_frame, text="No Devices Connected", 
                              font=('Arial', 16, 'bold'))
        title_label.pack(pady=(60, 20))
        
        instructions = [
            "To connect an Android device:",
            "1. Enable Developer Options on your device",
            "   (Settings > About Phone > Tap 'Build Number' 7 times)",
            "2. Enable USB Debugging",
            "   (Settings > Developer Options > USB Debugging)",
            "3. Connect your device via USB cable",
            "4. Accept 'Allow USB Debugging' prompt on your device",
            "",
            "Your device will appear here once connected."
        ]
        
        for instruction in instructions:
            label = tk.Label(self.no_devices_frame, text=instruction, 
                           font=('Arial', 10), anchor=tk.W, justify=tk.LEFT)
            pady = 8 if instruction == "" else 2
            label.pack(anchor=tk.W, padx=100, pady=pady)
        
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.refresh_devices_btn = ttk.Button(btn_frame, text="Refresh", command=self._refresh_devices)
        self.refresh_devices_btn.pack(side=tk.LEFT, padx=2)
        
        self.mirror_btn = ttk.Button(btn_frame, text="Start Mirroring", command=self._toggle_mirroring)
        self.mirror_btn.pack(side=tk.LEFT, padx=2)
        
        self.scrcpy_settings_btn = ttk.Button(btn_frame, text="scrcpy Settings", command=self._show_scrcpy_settings)
        self.scrcpy_settings_btn.pack(side=tk.LEFT, padx=2)

        self.connect_wireless_btn = ttk.Button(btn_frame, text="Connect Wirelessly...", command=self._show_connect_wireless_dialog)
        self.connect_wireless_btn.pack(side=tk.LEFT, padx=2)
        
        return tab
    
    def _create_processes_tab(self):
        tab = ttk.Frame(self.notebook)
        
        list_frame = ttk.LabelFrame(tab, text="Running Processes")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.system_info_label = tk.Label(list_frame, text="", anchor=tk.W, font=('Monospace', 9))
        self.system_info_label.pack(fill=tk.X, padx=5, pady=2)
        
        columns = ('PID', 'User', 'CPU%', 'Memory', 'Name')
        self.process_tree = ttk.Treeview(list_frame, columns=columns, show='tree headings')
        
        self.process_sort_col = 'CPU%'
        self.process_sort_reverse = True
        
        self.process_tree.heading('#0', text='#')
        self.process_tree.heading('PID', text='PID', command=lambda: self._sort_processes_by_column('PID'))
        self.process_tree.heading('User', text='User', command=lambda: self._sort_processes_by_column('User'))
        self.process_tree.heading('CPU%', text='CPU%', command=lambda: self._sort_processes_by_column('CPU%'))
        self.process_tree.heading('Memory', text='Memory', command=lambda: self._sort_processes_by_column('Memory'))
        self.process_tree.heading('Name', text='Process Name', command=lambda: self._sort_processes_by_column('Name'))

        
        self.process_tree.column('#0', width=scale_size(40, self.root))
        self.process_tree.column('PID', width=scale_size(80, self.root))
        self.process_tree.column('User', width=scale_size(120, self.root))
        self.process_tree.column('CPU%', width=scale_size(80, self.root))
        self.process_tree.column('Memory', width=scale_size(100, self.root))
        self.process_tree.column('Name', width=scale_size(350, self.root))
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.process_tree.yview)
        self.process_tree.configure(yscrollcommand=scrollbar.set)
        self.process_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.process_tree.bind('<Double-1>', self._show_process_info)

        
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.refresh_processes_btn = ttk.Button(btn_frame, text="Refresh", command=self._refresh_processes)
        self.refresh_processes_btn.pack(side=tk.LEFT, padx=2)
        
        self.kill_process_btn = ttk.Button(btn_frame, text="Kill Process", command=self._kill_process)
        self.kill_process_btn.pack(side=tk.LEFT, padx=2)
        
        self.copy_processes_btn = ttk.Button(btn_frame, text="Copy Process List", command=self._copy_processes_list)
        self.copy_processes_btn.pack(side=tk.RIGHT, padx=2)
        
        return tab

    
    def _create_apps_tab(self):
        tab = ttk.Frame(self.notebook)
        
        list_frame = ttk.LabelFrame(tab, text="Installed Applications")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Applications list
        self.app_sort_col = 'Name'
        self.app_sort_reverse = False
        columns = ('Name', 'Package', 'Type', 'Size')
        self.app_tree = ttk.Treeview(list_frame, columns=columns, show='headings',
                                     selectmode='extended')
        for col in columns:
            self.app_tree.heading(col, text=col,
                                  command=lambda c=col: self._sort_apps_by_column(c))
        self.app_tree.column('Name', width=scale_size(200, self.root))
        self.app_tree.column('Package', width=scale_size(300, self.root))
        self.app_tree.column('Type', width=scale_size(80, self.root), anchor='center')
        self.app_tree.column('Size', width=scale_size(100, self.root), anchor='e')

        scrollbar_tv = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.app_tree.yview)
        self.app_tree.configure(yscrollcommand=scrollbar_tv.set)
        self.app_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_tv.pack(side=tk.RIGHT, fill=tk.Y)
        self.app_tree.bind('<<TreeviewSelect>>', self._on_app_selection_change)
        self.app_tree.bind('<Double-1>', self._show_app_info)
        self.app_tree.bind('<Return>', self._show_app_info)

        # Dropping APKs from Explorer installs them, when the platform supports it.
        self.drop_supported = enable_file_drop(list_frame, self._on_files_dropped)
        if self.drop_supported:
            # An empty-state hint, parented to the list itself so that centring
            # it ignores the label frame's border and its scrollbar. It is hidden
            # as soon as there are rows, so it never covers anything to click.
            self.drop_hint = ttk.Label(
                self.app_tree,
                text="No applications found.\nDrop .apk files here to install them.",
                foreground='gray',
                anchor='center',
                justify='center'
            )
            self.drop_hint.place(relx=0.5, rely=0.5, anchor='center')
            # Re-wrap as the list is resized, so the hint never runs off the side.
            self.app_tree.bind('<Configure>', self._on_drop_hint_configure)



        
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.refresh_apps_btn = ttk.Button(btn_frame, text="Refresh", command=self._refresh_apps)
        self.refresh_apps_btn.pack(side=tk.LEFT, padx=2)
        
        self.install_apk_btn = ttk.Button(btn_frame, text="Install APK", command=self._install_apk)
        self.install_apk_btn.pack(side=tk.LEFT, padx=2)
        
        self.extract_apk_btn = ttk.Button(btn_frame, text="Extract APK", command=self._extract_apk)
        self.extract_apk_btn.pack(side=tk.LEFT, padx=2)
        
        self.start_app_btn = ttk.Button(btn_frame, text="Start App", command=self._start_app)
        self.start_app_btn.pack(side=tk.LEFT, padx=2)
        
        self.stop_app_btn = ttk.Button(btn_frame, text="Stop App", command=self._stop_app)
        self.stop_app_btn.pack(side=tk.LEFT, padx=2)
        
        self.uninstall_app_btn = ttk.Button(btn_frame, text="Uninstall App", command=self._uninstall_app)
        self.uninstall_app_btn.pack(side=tk.LEFT, padx=2)

        self.clear_cache_btn = ttk.Button(btn_frame, text="Clear Cache", command=self._clear_app_cache)
        self.clear_cache_btn.pack(side=tk.LEFT, padx=2)

        
        return tab
    
    def _update_tab_visibility(self):
        if self.has_devices:
            self.device_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.no_devices_frame.pack_forget()
            self._update_button_states()
            
            if self.selected_device and self.notebook.index('end') == 1:
                self.notebook.add(self.processes_tab, text="Processes")
                self.notebook.add(self.apps_tab, text="Applications")
                self.notebook.add(self.files_tab, text="Files")
                self.notebook.add(self.logcat_tab, text="Logcat")
                self.notebook.add(self.shell_tab, text="Shell")
            elif not self.selected_device:
                while self.notebook.index('end') > 1:
                    self.notebook.forget(1)
        else:
            self.device_tree.pack_forget()
            self.no_devices_frame.pack(fill=tk.BOTH, expand=True)
            self._update_button_states()
            
            while self.notebook.index('end') > 1:
                self.notebook.forget(1)
    
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
        
        # App specific buttons depend on both device readiness AND app selection
        self._update_app_button_states()
    
    def _get_selected_packages(self) -> List[str]:
        """Every selected package, in the order the rows appear in the view."""
        selected = set(self.app_tree.selection())
        packages = []
        for item_id in self.app_tree.get_children(''):
            if item_id not in selected:
                continue
            values = self.app_tree.item(item_id, 'values')
            if values and len(values) >= 2 and values[1]:
                packages.append(values[1])
        return packages

    def _get_selected_package(self) -> Optional[str]:
        """The package the single-app actions act on.

        With several rows selected this is the focused one, so Ctrl+clicking a
        pile of apps and then hitting Start still does something predictable.
        """
        packages = self._get_selected_packages()
        if not packages:
            return None

        focused = None
        focus_id = self.app_tree.focus()
        if focus_id:
            values = self.app_tree.item(focus_id, 'values')
            if values and len(values) >= 2:
                focused = values[1]

        return focused if focused in packages else packages[0]

    def _get_visible_app_types(self) -> Dict[str, str]:
        """Package -> Type column value for every app currently listed.

        The type comes from the install path the device reports, so unlike the
        name heuristic it holds for any package, vendor ones included.
        """
        types: Dict[str, str] = {}
        for item_id in self.app_tree.get_children(''):
            values = self.app_tree.item(item_id, 'values')
            if values and len(values) >= 3 and values[1]:
                types[values[1]] = values[2]
        return types

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
    
    def _show_about(self):
        AboutDialog(self.root).show()
    
    def _show_preferences(self):
        PreferencesDialog(self.root, self._on_preferences_changed).show()
        
    def _show_scrcpy_settings(self):
        if not self._require_device():
            return
            
        dialog = ScrcpySettingsDialog(self.root, self.selected_device, self.device_manager.scrcpy)
        self.root.wait_window(dialog)
        if dialog.result:
            self._load_scrcpy_settings()
            self._set_status("scrcpy settings updated")
            
    def _load_scrcpy_settings(self):
        self.mirror_settings = {
            'video_bit_rate': self.config.get('scrcpy', 'video_bit_rate', '8M'),
            'audio_bit_rate': self.config.get('scrcpy', 'audio_bit_rate', '128K'),
            'max_size': self.config.get('scrcpy', 'max_size', None),
            'max_fps': self.config.get('scrcpy', 'max_fps', 0),
            'orientation': self.config.get('scrcpy', 'orientation', '0'),
            'window_title': self.config.get('scrcpy', 'window_title', 'Droidmgr Mirroring'),
            'video_codec': self.config.get('scrcpy', 'video_codec', 'h264'),
            'audio_codec': self.config.get('scrcpy', 'audio_codec', 'opus'),
            'audio_source': self.config.get('scrcpy', 'audio_source', 'output'),
            'audio_buffer': self.config.get('scrcpy', 'audio_buffer', 50),
            'angle': self.config.get('scrcpy', 'angle', 0),
            'mouse_mode': self.config.get('scrcpy', 'mouse_mode', 'sdk'),
            'fullscreen': self.config.get('scrcpy', 'fullscreen', False),
            'always_on_top': self.config.get('scrcpy', 'always_on_top', False),
            'stay_awake': self.config.get('scrcpy', 'stay_awake', False),
            'turn_screen_off': self.config.get('scrcpy', 'turn_screen_off', False),
            'no_audio': self.config.get('scrcpy', 'no_audio', False),
            'no_video': self.config.get('scrcpy', 'no_video', False),
            'show_touches': self.config.get('scrcpy', 'show_touches', False),
            'window_borderless': self.config.get('scrcpy', 'window_borderless', False),
            'power_off_on_close': self.config.get('scrcpy', 'power_off_on_close', False),
            
            # New settings
            'video_source': self.config.get('scrcpy', 'video_source', 'display'),
            'camera_id': self.config.get('scrcpy', 'camera_id', ''),
            'camera_facing': self.config.get('scrcpy', 'camera_facing', 'any'),
            'camera_ar': self.config.get('scrcpy', 'camera_ar', ''),
            'camera_fps': self.config.get('scrcpy', 'camera_fps', 0),
            'camera_size': self.config.get('scrcpy', 'camera_size', ''),
            'keyboard_mode': self.config.get('scrcpy', 'keyboard_mode', 'sdk'),
            'no_control': self.config.get('scrcpy', 'no_control', False),
            'no_clipboard_autosync': self.config.get('scrcpy', 'no_clipboard_autosync', False),
            'no_key_repeat': self.config.get('scrcpy', 'no_key_repeat', False),
            'no_mouse_hover': self.config.get('scrcpy', 'no_mouse_hover', False),
            'no_power_on': self.config.get('scrcpy', 'no_power_on', False),
            'otg': self.config.get('scrcpy', 'otg', False),
            'print_fps': self.config.get('scrcpy', 'print_fps', False),
            'record_path': self.config.get('scrcpy', 'record_path', '') if self.config.get('scrcpy', 'record', False) else None
        }
    
    def _on_preferences_changed(self):
        from core import ConfigManager
        config = ConfigManager()
        
        adb_path = config.get('paths', 'adb')
        scrcpy_path = config.get('paths', 'scrcpy')
        
        if adb_path:
            self.adb_path = Path(adb_path)
        if scrcpy_path:
            self.scrcpy_path = Path(scrcpy_path)
            
        try:
            self.device_manager = DeviceManager(self.adb_path, self.scrcpy_path)
            self.file_manager.device_manager = self.device_manager
            self.logcat_view.device_manager = self.device_manager
            self.shell_view.device_manager = self.device_manager
            self._set_status("Preferences updated")
            self._refresh_devices()

            if self.selected_device and getattr(self.device_manager, 'is_device_ready', lambda d: True)(self.selected_device):
                self.file_manager.refresh()
                self._refresh_apps()

        except Exception as e:
            self._show_error("Error", f"Failed to reinitialize with new settings:\n{e}")
    
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
    
    def _on_device_select(self, event):
        selection = self.device_tree.selection()
        if selection:
            item = self.device_tree.item(selection[0])
            values = item['values']
            if values:
                self.selected_device = values[0]
                self._set_status(f"Selected device: {self.selected_device}")
                self._update_tab_visibility()
                self._update_button_states()
                
                # Update file manager device reference
                self.file_manager.selected_device = self.selected_device
                
                # Only refresh the currently active tab
                try:
                    current_tab_id = self.notebook.select()
                    current_tab_text = self.notebook.tab(current_tab_id, "text") if current_tab_id else ""
                except Exception:
                    current_tab_text = ""
                
                if current_tab_text == "Processes":
                    self._refresh_processes()
                elif current_tab_text == "Applications":
                    self._refresh_apps()
                elif current_tab_text == "Files":
                    self.file_manager.refresh()
                    self.logcat_view.set_device(self.selected_device)
                elif current_tab_text == "Logcat":
                    self.logcat_view.set_device(
                        self.selected_device, force_refresh=True, autostart=True)
                elif current_tab_text == "Shell":
                    self.shell_view.set_device(self.selected_device)
                else:
                    self.logcat_view.set_device(self.selected_device)
                    self.shell_view.set_device(self.selected_device)

    def _on_tab_changed(self, event=None):
        if not self.selected_device:
            return
            
        try:
            current_tab_id = self.notebook.select()
            if not current_tab_id:
                return
            tab_text = self.notebook.tab(current_tab_id, "text")
            
            if tab_text == "Processes":
                self._refresh_processes()
            elif tab_text == "Applications":
                self._refresh_apps()
            elif tab_text == "Files":
                self.file_manager.set_device(self.selected_device, force_refresh=True)
            elif tab_text == "Logcat":
                self.logcat_view.set_device(
                    self.selected_device, force_refresh=True, autostart=True)
            elif tab_text == "Shell":
                self.shell_view.set_device(self.selected_device)
        except Exception:
            pass

    def _open_shell_tab(self):
        """Focus the Shell tab (Tools > Open Shell)."""
        if not self._require_device():
            return
        if self.shell_tab not in self.notebook.tabs():
            return
        self.notebook.select(self.shell_tab)
        self.shell_view.set_device(self.selected_device)
        self.shell_view.focus_input()

    def _take_screenshot(self):
        """Tools > Take Screenshot: one click, then a save dialog."""
        if not self._require_device():
            return
        take_screenshot(self.root, self.device_manager, self.selected_device,
                        self._set_status, self._show_error, self._show_info)

    def _record_screen(self):
        """Tools > Record Screen: parameter dialog, then record, pull and open."""
        if not self._require_device():
            return
        record_screen(self.root, self.device_manager, self.selected_device,
                      self._set_status, self._show_error, self._show_info)

    def _extract_apk(self):
        """Applications > Extract APK: pull the selected package off the device."""
        if not self._require_device():
            return
        package = self._get_selected_package()
        if not package:
            self._show_warning("Please select an application first")
            return
        extract_apk(self.root, self.device_manager, self.selected_device, package,
                    self._set_status, self._show_error, self._show_info)


    def _on_device_double_click(self, event):
        if self.selected_device:
            DeviceDetailsDialog(self.root, self.selected_device, self.device_manager)
    
    def _refresh_devices(self):
        for item in self.device_tree.get_children():
            self.device_tree.delete(item)
        
        try:
            devices = self.device_manager.get_devices()
            self.has_devices = len(devices) > 0
            self._update_tab_visibility()
            
            if not hasattr(self, '_notified_device_statuses'):
                self._notified_device_statuses = {}

            problem_msgs = []
            current_statuses = {}

            for device in devices:
                dev_id = device['id']
                st = device.get('status', '').lower()
                current_statuses[dev_id] = st

                display_status = device.get('status', 'Unknown')
                if st == 'unauthorized':
                    display_status = "Unauthorized (Check Phone Prompt)"
                    msg = f"Device '{dev_id}' is unauthorized. Please accept the USB debugging prompt on the device screen."
                    if self._notified_device_statuses.get(dev_id) != 'unauthorized':
                        problem_msgs.append(msg)
                elif st == 'offline':
                    display_status = "Offline (Reconnect Cable)"
                    msg = f"Device '{dev_id}' is offline. Try reconnecting the USB cable or restarting ADB."
                    if self._notified_device_statuses.get(dev_id) != 'offline':
                        problem_msgs.append(msg)

                device['display_status'] = display_status

            self._notified_device_statuses = current_statuses

            if problem_msgs:
                self._set_status("; ".join(problem_msgs))

            for idx, device in enumerate(devices, 1):
                mirroring = "Yes" if device.get('is_mirroring', False) else "No"
                self.device_tree.insert('', tk.END, text=str(idx),
                                       values=(device['id'], device.get('model', 'Unknown'),
                                              device.get('display_status', device['status']), mirroring))
            self._set_status(f"Found {len(devices)} device(s)")

            children = self.device_tree.get_children()
            device_ids = [d['id'] for d in devices]

            if self.selected_device and self.selected_device not in device_ids:
                disconnected_id = self.selected_device
                self.statusbar.config(text=f"WARNING: Device '{disconnected_id}' disconnected.", foreground='red')
                self.root.after(4000, lambda: self.statusbar.config(foreground='black'))
                
                if self.device_manager.scrcpy.is_mirroring(disconnected_id):
                    try:
                        self.device_manager.stop_mirroring(disconnected_id)
                    except Exception:
                        pass

            if children:
                if not self.selected_device or self.selected_device not in device_ids:
                    first_item = children[0]
                    self.device_tree.selection_set(first_item)
                    self.device_tree.focus(first_item)
                    self._on_device_select(None)
                else:
                    curr_idx = device_ids.index(self.selected_device)
                    self.device_tree.selection_set(children[curr_idx])
            else:
                self.selected_device = None
                self.logcat_view.set_device(None)
                self._update_tab_visibility()

        except Exception as e:
            self.has_devices = False
            self.selected_device = None
            self.logcat_view.set_device(None)
            self._update_tab_visibility()
            self._set_status(f"Device refresh error: {e}")

        interval_sec = self.config.get('general', 'query_interval', 5)
        self.root.after(int(interval_sec) * 1000, self._refresh_devices)


    
    def _update_mirror_label(self, is_mirroring: bool):
        """Keep the mirroring toolbar button and menu item showing the same action."""
        label = "Stop Mirroring" if is_mirroring else "Start Mirroring"
        self.mirror_btn.config(text=label)
        self.device_menu.entryconfig(self.mirror_menu_index, label=label)

    def _toggle_mirroring(self):
        if not self._require_device():
            return
        
        is_mirroring = self.device_manager.scrcpy.is_mirroring(self.selected_device)
        
        if is_mirroring:
            try:
                self.device_manager.stop_mirroring(self.selected_device)
                self._update_mirror_label(False)
                self._set_status("Mirroring stopped")
            except Exception as e:
                self._show_error("Mirroring Error", str(e))
        else:
            def task():
                try:
                    process = self.device_manager.start_mirroring(self.selected_device, **self.mirror_settings)
                    
                    def start_dialog():
                        self._update_mirror_label(True)
                        self._set_status("Mirroring started")
                        ScrcpyOutputDialog(self.root, process, self.selected_device, self.device_manager.stop_mirroring)
                        
                    self.root.after(0, start_dialog)
                except Exception as e:
                    msg = str(e)
                    self.root.after(0, lambda: self._show_error("Mirroring Error", msg))
            
            self._set_status("Starting screen mirroring...")
            threading.Thread(target=task, daemon=True).start()
    
    def _enable_tcpip_mode(self):
        """Open the wireless connection dialog with the USB Setup tab active."""
        self._show_connect_wireless_dialog(initial_tab=0)

    def _show_connect_wireless_dialog(self, initial_tab=None):
        """Show unified 3-tabbed dialog to connect to an Android device wirelessly."""
        ConnectWirelesslyDialog(
            parent=self.root,
            device_manager=self.device_manager,
            selected_device=self.selected_device,
            on_connected_callback=self._refresh_devices,
            initial_tab=initial_tab
        )

    def _disconnect_wireless_device(self):
        """Disconnect a connected wireless ADB device."""
        if not self.selected_device:
            messagebox.showinfo("Select Device", "Please select a connected wireless device to disconnect.", parent=self.root)
            return

        if ":" not in self.selected_device:
            messagebox.showinfo(
                "Not a Wireless Device",
                f"Device '{self.selected_device}' is connected via USB. You can simply unplug the USB cable.",
                parent=self.root
            )
            return

        dev_id = self.selected_device
        try:
            self.device_manager.disconnect_device(dev_id)
            self._set_status(f"Disconnected {dev_id}")
            self._refresh_devices()
        except Exception as e:
            self._show_error("Disconnect Error", str(e))

    def _power_action(self, action):
        """Reboot or power off the selected device, after confirming."""
        if not self._require_device():
            return

        label, target, detail = _POWER_ACTIONS[action]
        if not messagebox.askyesno(
                label,
                f"{label} device '{self.selected_device}'?\n\n{detail}\n\n"
                "Unsaved work on the device will be lost.",
                parent=self.root):
            return

        device_id = self.selected_device
        is_shutdown = action == 'shutdown'
        self._set_status(f"{label} requested...")

        def task():
            try:
                if is_shutdown:
                    self.device_manager.shutdown_device(device_id)
                else:
                    self.device_manager.reboot_device(device_id, target)
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_error(f"{label} Failed", msg))
                return
            self.root.after(0, lambda: self._on_power_sent(label, device_id, is_shutdown))

        threading.Thread(target=task, daemon=True).start()

    def _on_power_sent(self, label, device_id, is_shutdown):
        """Report a delivered power command and watch for the device coming back."""
        self._refresh_devices()
        self._set_status(f"{label} sent to {device_id}")
        # A powered-off device never comes back on its own.
        if not is_shutdown:
            for delay in _RECONNECT_POLL_DELAYS:
                self.root.after(delay, self._refresh_devices)

    def _check_root_access(self):
        """Report whether the selected device gives adb root access."""
        if not self._require_device():
            return

        device_id = self.selected_device
        self._set_status("Checking root access...")

        def task():
            try:
                status = self.device_manager.get_root_status(device_id)
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_error("Root Check Failed", msg))
                return
            self.root.after(0, lambda: self._show_root_status(status))

        threading.Thread(target=task, daemon=True).start()

    def _show_root_status(self, status):
        """Explain what the root check found."""
        uid = status.get('shell_uid') or 'unknown'
        su_path = status.get('su_path')

        if status.get('adb_root'):
            summary = ("adb is running as root (uid 0).\n"
                       "System files and commands are unrestricted.")
        elif su_path:
            summary = (f"adb is not root (shell uid {uid}).\n\n"
                       f"An su binary is present at:\n{su_path}\n\n"
                       "It may still need approval on the device screen, or be limited "
                       "to certain apps.")
        else:
            summary = (f"adb is not root (shell uid {uid}).\n\n"
                       "No su binary found. The device is not rooted, or root is hidden.")

        self._set_status("Root check complete: "
                         + ("root available" if status.get('adb_root') else "not root"))
        messagebox.showinfo("Root Access", summary, parent=self.root)

    def _reconnect_adb(self):
        """Ask the adb server to re-establish device connections."""
        self._set_status("Reconnecting through ADB...")

        def task():
            try:
                output = self.device_manager.reconnect_devices()
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_error("Reconnect Failed", msg))
                return
            self.root.after(0, lambda: self._on_adb_reconnected(output))

        threading.Thread(target=task, daemon=True).start()

    def _on_adb_reconnected(self, output):
        self._refresh_devices()
        detail = ' '.join((output or '').split())
        self._set_status(f"ADB reconnect sent{': ' + detail if detail else ''}")
        for delay in _RECONNECT_POLL_DELAYS:
            self.root.after(delay, self._refresh_devices)

    def _show_device_context_menu(self, event):
        """Show context menu for a device row in device_tree."""
        item = self.device_tree.identify_row(event.y)
        if item:
            self.device_tree.selection_set(item)
            self._on_device_select(None)
        
        if not self.selected_device:
            return

        menu = tk.Menu(self.root, tearoff=0)
        is_mirroring = self.device_manager.scrcpy.is_mirroring(self.selected_device)
        menu.add_command(
            label="Stop Mirroring" if is_mirroring else "Start Mirroring",
            command=self._toggle_mirroring
        )
        menu.add_separator()
        if ":" not in self.selected_device:
            menu.add_command(
                label="Connect Wirelessly...",
                command=self._show_connect_wireless_dialog
            )
        else:
            menu.add_command(
                label="Disconnect Wireless Device",
                command=self._disconnect_wireless_device
            )
        menu.add_command(
            label="Device Details",
            command=lambda: DeviceDetailsDialog(self.root, self.selected_device, self.device_manager)
        )
        menu.add_separator()
        menu.add_command(label="Refresh", command=self._refresh_devices)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _refresh_processes(self):
        if not self.selected_device:
            return
        
        # Check device readiness before querying
        try:
            if not self.device_manager.is_device_ready(self.selected_device):
                status = None
                if hasattr(self.device_manager, 'get_device_status'):
                    status = self.device_manager.get_device_status(self.selected_device)
                status_str = status.lower() if status else 'offline'
                for item in self.process_tree.get_children():
                    self.process_tree.delete(item)
                if status_str == 'unauthorized':
                    msg = "Device is unauthorized. Please accept the USB debugging prompt on your phone screen."
                else:
                    msg = "Device is offline. Reconnect USB cable or restart ADB."
                self.system_info_label.config(text=msg)
                self._set_status(f"Device '{self.selected_device}' is {status_str}.")
                return
        except Exception:
            pass

        # Save selection and scroll position
        selected_items = self.process_tree.selection()
        selected_pids = []
        for item_id in selected_items:
            values = self.process_tree.item(item_id, 'values')
            if values:
                selected_pids.append(values[0])
        
        yview = self.process_tree.yview()
        
        def task():
            try:
                import concurrent.futures
                device = self.selected_device
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    f_proc = executor.submit(self.device_manager.get_processes, device)
                    f_stats = executor.submit(self.device_manager.adb.get_system_stats, device)
                    processes = f_proc.result(timeout=15)
                    stats = f_stats.result(timeout=15)

                
                # Sort processes based on the saved column and direction
                if hasattr(self, 'process_sort_col') and self.process_sort_col:
                    col = self.process_sort_col
                    reverse = self.process_sort_reverse
                    
                    def get_proc_sort_key(proc):
                        if col == 'PID':
                            try:
                                return int(proc['pid'])
                            except ValueError:
                                return 0
                        elif col == 'CPU%':
                            try:
                                return float(proc.get('cpu', 0))
                            except ValueError:
                                return 0.0
                        elif col == 'Memory':
                            try:
                                return _parse_memory(proc.get('mem', '0 MB'))
                            except Exception:
                                return 0.0
                        elif col == 'User':
                            return proc['user'].lower()
                        else:
                            return proc['name'].lower()
                            
                    processes.sort(key=get_proc_sort_key, reverse=reverse)

                
                def update():
                    # Clear existing items inside the main thread to avoid intermediate empty states
                    for item in self.process_tree.get_children():
                        self.process_tree.delete(item)
                        
                    system_info = f"System: {stats.get('cpu_cores', '?')} cores | "
                    system_info += f"Memory: {stats.get('free_memory', '?')} free / {stats.get('total_memory', '?')} total"
                    self.system_info_label.config(text=system_info)
                    
                    for idx, proc in enumerate(processes, 1):
                        cpu_color = ''
                        try:
                            cpu_val = float(proc.get('cpu', 0))
                            if cpu_val > 50:
                                cpu_color = 'red'
                            elif cpu_val > 20:
                                cpu_color = 'orange'
                        except:
                            pass
                        
                        item_id = self.process_tree.insert(
                            '', tk.END, text=str(idx),
                            values=(proc['pid'], proc['user'], proc.get('cpu', '0'), 
                                   proc.get('mem', '0 MB'), proc['name'])
                        )
                        
                        if cpu_color:
                            self.process_tree.item(item_id, tags=(cpu_color,))
                            
                        # Restore selection if it matches one of the saved PIDs
                        if proc['pid'] in selected_pids:
                            self.process_tree.selection_add(item_id)
                            self.process_tree.focus(item_id)
                    
                    self.process_tree.tag_configure('red', foreground='red')
                    self.process_tree.tag_configure('orange', foreground='orange')
                    
                    # Restore scroll position
                    if yview:
                        self.process_tree.yview_moveto(yview[0])
                        
                    self._set_status(f"Found {len(processes)} processes")
                self.root.after(0, update)
            except (ADBDeviceOfflineError, ADBDeviceNotFoundError):
                def handle_offline():
                    for item in self.process_tree.get_children():
                        self.process_tree.delete(item)
                    self.system_info_label.config(text="Device is offline or disconnected.")
                    self._set_status(f"Device '{device}' is offline or disconnected.")
                self.root.after(0, handle_offline)
            except concurrent.futures.TimeoutError:
                self.root.after(0, lambda: self._set_status("Process query timed out after 15 seconds."))
            except Exception as e:
                msg = str(e)
                if _is_offline_error(msg):
                    def handle_offline():
                        for item in self.process_tree.get_children():
                            self.process_tree.delete(item)
                        self.system_info_label.config(text="Device is offline or disconnected.")
                        self._set_status(f"Device '{device}' is offline or disconnected.")
                    self.root.after(0, handle_offline)
                else:
                    self.root.after(0, lambda: self._show_error("Process Refresh Error", msg))
        
        threading.Thread(target=task, daemon=True).start()


    
    def _kill_process(self):
        if not self._require_device():
            return
        
        selection = self.process_tree.selection()
        if not selection:
            self._show_warning("Please select a process to kill")
            return
        
        values = self.process_tree.item(selection[0])['values']
        if not values or len(values) < 5:
            return
            
        pid = str(values[0]).strip()
        user = str(values[1]).strip()
        name = str(values[4]).strip()
        
        # 1. Check for PIDs 1 or 2
        is_critical_pid = pid in ('1', '2')
        
        # 2. Check for expanded core Android processes
        CORE_PROCESSES = {
            'system_server', 'com.android.systemui', 'com.android.phone', 'init', 'adbd',
            'surfaceflinger', 'zygote', 'zygote64', 'lmkd', 'vold', 'servicemanager',
            'keystore', 'keystore2', 'hwservicemanager', 'netd', 'logd', 'tombstoned',
            'ueventd', 'healthd', 'storaged', 'auditd', 'kthreadd'
        }
        is_core_name = name in CORE_PROCESSES
        
        # 3. Check for root kernel workers
        CRITICAL_PREFIXES = ('kworker', 'ksoftirqd', 'migration', 'watchdog', 'rcu_')
        is_kernel_worker = (user == 'root' and any(name.startswith(p) for p in CRITICAL_PREFIXES))
        
        if is_critical_pid or is_core_name or is_kernel_worker:
            msg = (
                f"Warning: '{name}' (PID: {pid}) is a core Android system/kernel process.\n\n"
                "Terminating this process may cause your device to crash, reboot, or lose connectivity.\n\n"
                "Are you sure you want to proceed and force-kill this process?"
            )
            if not messagebox.askyesno("Warning - Core System Process", msg, icon=messagebox.WARNING):
                return
        else:
            # Check for system UID / system process elevated warning
            is_system_uid = False
            if user in ('root', 'system'):
                is_system_uid = True
            elif user.isdigit() and int(user) < 1000:
                is_system_uid = True
            elif name.startswith(('com.android.', 'com.google.android.')):
                is_system_uid = True
                
            if is_system_uid:
                msg = (
                    f"Process '{name}' (PID: {pid}, User: {user}) is a system service.\n\n"
                    "Terminating it may affect system functionality or cause it to automatically restart.\n\n"
                    "Do you want to terminate this process?"
                )
                if not messagebox.askyesno("Confirm Kill System Process", msg, icon=messagebox.WARNING):
                    return
            else:
                if not messagebox.askyesno("Confirm Kill", f"Kill process {pid} ({name})?"):
                    return

        device_id = self.selected_device
        def task():
            try:
                self.device_manager.kill_process(device_id, pid)
                self.root.after(0, lambda: self._set_status(f"Sent kill signal to process {pid} ({name})"))
                
                # Post-kill verification after 500ms
                import time
                time.sleep(0.5)
                
                processes = self.device_manager.get_processes(device_id)
                still_running = any(str(p.get('pid')) == pid for p in processes)
                
                def update_ui():
                    self._refresh_processes()
                    if still_running:
                        self._show_warning(f"Process {pid} ({name}) is still running.\n\nIt may require root privileges or may have automatically restarted.")
                    else:
                        self._set_status(f"Killed process {pid} ({name})")
                        
                self.root.after(0, update_ui)
                
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_error("Kill Process Error", msg))
                
        threading.Thread(target=task, daemon=True).start()


    
    def _refresh_apps(self):
        if not self.selected_device:
            return
        
        # Check device readiness before querying
        try:
            if not self.device_manager.is_device_ready(self.selected_device):
                status = None
                if hasattr(self.device_manager, 'get_device_status'):
                    status = self.device_manager.get_device_status(self.selected_device)
                status_str = status.lower() if status else 'offline'
                for item in self.app_tree.get_children():
                    self.app_tree.delete(item)
                tag_text = f"[Device is {status_str}]"
                self.app_tree.insert('', tk.END, values=(tag_text, "", "", ""))
                self._update_drop_hint()
                self._update_app_button_states()
                self._set_status(f"Device '{self.selected_device}' is {status_str}.")
                return
        except Exception:
            pass

        selected_packages = set(self._get_selected_packages())
        yview = self.app_tree.yview()

        def task():
            try:
                apps_details = self.device_manager.get_installed_apps_details(self.selected_device)

                # Re-apply the column sort so a refresh does not snap back to name order
                sort_col = getattr(self, 'app_sort_col', None)
                if sort_col:
                    apps_details.sort(key=lambda app: _app_sort_key(app, sort_col),
                                      reverse=self.app_sort_reverse)

                def update():
                    for item in self.app_tree.get_children():
                        self.app_tree.delete(item)

                    target_ids = []
                    for app in apps_details:
                        item_id = self.app_tree.insert(
                            '', tk.END,
                            values=(app['name'], app['package'], app['type'],
                                    _format_bytes(app.get('size_bytes', 0)))
                        )
                        if app['package'] in selected_packages:
                            target_ids.append(item_id)

                    self._update_drop_hint()

                    if target_ids:
                        self.app_tree.selection_set(target_ids)
                        self.app_tree.focus(target_ids[0])

                    if yview:
                        self.app_tree.yview_moveto(yview[0])

                    self._update_app_button_states()
                    self._set_status(f"Found {len(apps_details)} applications")
                self.root.after(0, update)
            except (ADBDeviceOfflineError, ADBDeviceNotFoundError):
                def handle_offline():
                    for item in self.app_tree.get_children():
                        self.app_tree.delete(item)
                    self.app_tree.insert('', tk.END, values=("[Device is offline]", "", "", ""))
                    self._update_drop_hint()
                    self._update_app_button_states()
                    self._set_status(f"Device '{self.selected_device}' is offline or disconnected.")
                self.root.after(0, handle_offline)
            except Exception as e:
                msg = str(e)
                lower_msg = msg.lower()
                if _is_offline_error(msg):
                    def handle_offline():
                        for item in self.app_tree.get_children():
                            self.app_tree.delete(item)
                        tag = "[Device is unauthorized]" if "unauthorized" in lower_msg else "[Device is offline]"
                        self.app_tree.insert('', tk.END, values=(tag, "", "", ""))
                        self._update_drop_hint()
                        self._update_app_button_states()
                        self._set_status(f"Device '{self.selected_device}' is offline or disconnected.")
                    self.root.after(0, handle_offline)
                else:
                    self.root.after(0, lambda: self._show_error("App Refresh Error", msg))
        
        threading.Thread(target=task, daemon=True).start()

    def _on_app_selection_change(self, event):
        self._update_app_button_states()
        count = len(self._get_selected_packages())
        if count > 1:
            self._set_status(f"{count} applications selected")

    def _show_app_info(self, event=None):
        package = self._get_selected_package()
        if not package:
            return
            
        def task():
            try:
                info = self.device_manager.adb.get_app_info(self.selected_device, package)
                self.root.after(0, lambda: AppInfoDialog(self.root, info, self.selected_device, self.device_manager))

            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_error("App Info Error", msg))
                
        threading.Thread(target=task, daemon=True).start()

    def _start_app(self):
        if not self._require_device():
            return
        
        package = self._get_selected_package()
        if not package:
            self._show_warning("Please select an app to start")
            return
        
        def task():
            try:
                self.device_manager.start_app(self.selected_device, package)
                self.root.after(0, lambda: self._show_info(f"Started {package}"))
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_error("Start App Error", msg))
        
        self._set_status(f"Starting {package}...")
        threading.Thread(target=task, daemon=True).start()
    
    def _stop_app(self):
        if not self._require_device():
            return
        
        package = self._get_selected_package()
        if not package:
            self._show_warning("Please select an app to stop")
            return
        
        try:
            self.device_manager.stop_app(self.selected_device, package)
            self._show_info(f"Stopped {package}")
        except Exception as e:
            self._show_error("Stop App Error", str(e))

    def _clear_app_cache(self):
        if not self._require_device():
            return

        packages = self._get_selected_packages()
        if not packages:
            self._show_warning("Please select one or more applications to clear")
            return

        if not self._confirm_clear_cache(packages):
            return

        device_id = self.selected_device
        self._set_status(f"Clearing data for {len(packages)} "
                         f"application{'s' if len(packages) > 1 else ''}...")

        def task():
            cleared = []
            failed = {}
            for package in packages:
                try:
                    self.device_manager.clear_app_data(device_id, package)
                    cleared.append(package)
                except Exception as e:
                    failed[package] = str(e)
            self.root.after(0, self._refresh_apps)
            self.root.after(0, lambda: self._report_clear_cache(cleared, failed))

        threading.Thread(target=task, daemon=True).start()

    def _confirm_clear_cache(self, packages: List[str]) -> bool:
        """Confirm a clear, spelling out that an app's data goes with its cache."""
        listed = '\n'.join(f"  - {pkg}" for pkg in packages[:10])
        if len(packages) > 10:
            listed += f"\n  ... and {len(packages) - 10} more"
        count = len(packages)
        return messagebox.askyesno(
            "Confirm Clear Cache",
            "Android cannot clear one app's cache on its own: its cache sits inside "
            "the app's own data directory, which only this operation can reach.\n\n"
            f"So the {count} selected application{'s' if count != 1 else ''} will also "
            "lose their stored data. Each will be signed out, its settings reset and "
            "anything it downloaded removed. What is not held by an account is lost.\n\n"
            f"{listed}\n\nClear data now?",
            icon=messagebox.WARNING)

    def _report_clear_cache(self, cleared: List[str], failed: Dict[str, str]):
        """Say what was cleared, and give the reason for anything that was not."""
        total = len(cleared) + len(failed)
        if not failed:
            self._show_info(f"Cleared data for {total} "
                            f"application{'s' if total != 1 else ''}")
            return
        if not cleared and all(_is_clear_denied(msg) for msg in failed.values()):
            self._show_error("Clear Cache Denied", _CLEAR_DENIED_MESSAGE)
            return
        detail = '\n'.join(f'  - {pkg}: {msg}'
                           for pkg, msg in list(failed.items())[:10])
        if len(failed) > 10:
            detail += f"\n  ... and {len(failed) - 10} more"
        self._show_error("Clear Cache Error",
                         f"{len(failed)} of {total} could not be cleared:\n{detail}")

    def _uninstall_app(self):
        if not self._require_device():
            return

        packages = self._get_selected_packages()
        if not packages:
            self._show_warning("Please select an application to uninstall")
            return

        device_id = self.selected_device

        if len(packages) > 1:
            self._confirm_bulk_uninstall(packages)
        else:
            if not self._confirm_single_uninstall(device_id, packages[0]):
                return

        self._set_status(f"Uninstalling {len(packages)} "
                         f"application{'s' if len(packages) > 1 else ''}...")

        def task():
            failed = []
            for package in packages:
                try:
                    self.device_manager.uninstall_app(device_id, package)
                except Exception:
                    failed.append(package)
            self.root.after(0, self._refresh_apps)
            if failed:
                detail = '\n'.join(failed)
                self.root.after(0, lambda: self._show_error(
                    "Uninstall Error",
                    f"{len(failed)} of {len(packages)} could not be uninstalled:\n{detail}"))
            elif len(packages) == 1:
                self.root.after(0, lambda: messagebox.showinfo(
                    "Success", f"Successfully uninstalled {packages[0]}"))
            else:
                self.root.after(0, lambda: messagebox.showinfo(
                    "Success", f"Successfully uninstalled {len(packages)} applications"))

        threading.Thread(target=task, daemon=True).start()

    def _confirm_bulk_uninstall(self, packages: List[str]) -> bool:
        """One confirmation for a multi-app uninstall, with a system-app warning."""
        # A listed app is judged by the install path the device reports, which
        # catches vendor system apps the name heuristic would miss. The name
        # check stays on as a floor for core packages.
        types = self._get_visible_app_types()
        risky = [pkg for pkg in packages
                 if types.get(pkg) == 'System' or _looks_like_system_package(pkg)]
        if risky:
            listed = '\n'.join(risky[:10])
            if len(risky) > 10:
                listed += f"\n  ... and {len(risky) - 10} more"
            if not messagebox.askyesno(
                    "Warning - System Applications",
                    f"{len(risky)} of the {len(packages)} selected applications look like "
                    f"system or core apps:\n\n{listed}\n\n"
                    "Uninstalling them can break core functionality, cause boot loops, "
                    "or disable system services.\n\nDo you want to proceed?",
                    icon=messagebox.WARNING):
                return False
            if not messagebox.askyesno(
                    "Critical Confirmation",
                    "You selected system or core applications. Your device may become "
                    "unusable.\n\nAre you ABSOLUTELY sure you want to proceed?",
                    icon=messagebox.WARNING):
                return False

        listed = '\n'.join(f"  - {pkg}" for pkg in packages[:10])
        if len(packages) > 10:
            listed += f"\n  ... and {len(packages) - 10} more"
        return messagebox.askyesno(
            "Confirm Uninstall",
            f"Are you sure you want to uninstall {len(packages)} applications?\n\n{listed}")

    def _confirm_single_uninstall(self, device_id: str, package: str) -> bool:
        """The original per-app checks, including the exact install path."""
        app_path = ""
        try:
            info = self.device_manager.adb.get_app_info(device_id, package)
            app_path = info.get('path', '')
        except Exception:
            pass

        is_system_app = _looks_like_system_package(package, app_path)
        app_type = "System Application" if is_system_app else "User Application"
        path_display = app_path if app_path else "Unknown"

        if is_system_app:
            msg1 = (
                f"Warning: '{package}' is a System Application.\n\n"
                f"Package: {package}\n"
                f"Type: {app_type}\n"
                f"Install Path: {path_display}\n\n"
                "Uninstalling system applications can break core functionality, cause boot loops, or disable system services.\n\n"
                "Do you want to proceed?"
            )
            if not messagebox.askyesno("Warning - System Application", msg1, icon=messagebox.WARNING):
                return False

            msg2 = (
                f"This is a system application ({package}).\n\n"
                "Uninstalling it may cause system instability or render your device unusable.\n\n"
                "Are you ABSOLUTELY sure you want to proceed and uninstall this application?"
            )
            if not messagebox.askyesno("Critical Confirmation", msg2, icon=messagebox.WARNING):
                return False
        else:
            msg = (
                f"Are you sure you want to uninstall this application?\n\n"
                f"Package: {package}\n"
                f"Type: {app_type}\n"
                f"Install Path: {path_display}"
            )
            if not messagebox.askyesno("Confirm Uninstall", msg):
                return False
        return True



    def _on_files_dropped(self, paths):
        """Install APKs dropped from Explorer onto the applications list."""
        self._install_apk_paths(paths)

    def _on_drop_hint_configure(self, event):
        """Wrap the drop hint to the width the applications list currently has."""
        available = event.width - scale_size(16, self.root)
        if available > scale_size(80, self.root):
            self.drop_hint.configure(wraplength=available)

    def _update_drop_hint(self):
        """Show the drop hint only while the applications list is empty."""
        if not getattr(self, 'drop_supported', False):
            return
        if self.app_tree.get_children():
            self.drop_hint.place_forget()
        else:
            self.drop_hint.place(relx=0.5, rely=0.5, anchor='center')

    def _show_forward_dialog(self):
        """Open the port forward manager for the selected device."""
        if not self._require_device():
            return
        ForwardDialog(self.root, self.selected_device, self.device_manager, self._set_status)

    def _install_apk(self):
        """Ask for an APK file and install it."""
        if not self._require_device():
            return

        apk_path = filedialog.askopenfilename(
            title="Select APK file",
            filetypes=[("APK files", "*.apk"), ("All files", "*.*")]
        )

        if apk_path:
            self._install_apk_paths([apk_path])

    def _install_apk_paths(self, paths):
        """Install one or more APK files in turn, from the picker or a drop."""
        if not self._require_device():
            return

        apks = [Path(p) for p in paths if Path(p).suffix.lower() == '.apk']
        if not apks:
            self._show_error("No APKs", "None of the selected files are .apk files.")
            return

        sizes = []
        for path in apks:
            if not path.exists() or not path.is_file():
                self._show_error("Invalid File", f"This file does not exist or is invalid:\n{path}")
                return
            sizes.append(path.stat().st_size / (1024 * 1024))

        biggest_index = sizes.index(max(sizes))
        if sizes[biggest_index] > 500:
            msg = (
                f"{apks[biggest_index].name} is very large ({sizes[biggest_index]:.1f} MB).\n\n"
                "Installing large applications over ADB may take several minutes.\n\n"
                "Do you want to proceed with the installation?"
            )
            if not messagebox.askyesno("Large File Warning", msg, icon=messagebox.WARNING):
                return

        total_mb = sum(sizes)
        label = apks[0].name if len(apks) == 1 else f"{len(apks)} APKs"
        progress_dialog = None
        if total_mb > 50:
            progress_dialog = APKInstallProgressDialog(self.root, label, total_mb)
        device_id = self.selected_device

        def task():
            installed, failures = [], []
            for path, size_mb in zip(apks, sizes):
                try:
                    self.device_manager.adb.install_apk(device_id, str(path))
                    installed.append(path.name)
                except Exception as e:
                    failures.append(f"{path.name}: {e}")
            if progress_dialog:
                self.root.after(0, progress_dialog.close)
            self.root.after(0, lambda: self._on_apks_installed(installed, failures))

        self._set_status(f"Installing {label}...")
        threading.Thread(target=task, daemon=True).start()

    def _on_apks_installed(self, installed, failures):
        """Report the outcome of a batch install."""
        if failures:
            details = '\n'.join(failures)
            if installed:
                succeeded = '\n'.join(f'  {name}' for name in installed)
                details = f"Installed:\n{succeeded}\n\nFailed:\n{details}"
            self._show_error("Install APK Error", details)
        elif len(installed) > 1:
            names = '\n'.join(installed)
            self._show_info(f"Installed {len(installed)} APKs:\n{names}")
        else:
            self._show_info("APK installed successfully")
        self._refresh_apps()


    
    def _generate_llm_report(self):
        if not self._require_device():
            return
        
        device_id = self.selected_device
        progress_dialog = LLMReportProgressDialog(self.root, title=f"Generating LLM Report - {device_id}")
        
        def progress_cb(pct, msg):
            self.root.after(0, lambda: progress_dialog.update_progress(pct, msg))
            
        def task():
            try:
                report_text = self.device_manager.generate_llm_report(device_id, progress_callback=progress_cb)
                
                def on_done():
                    if progress_dialog.winfo_exists():
                        progress_dialog.destroy()
                    if not progress_dialog.cancelled:
                        LLMReportDialog(self.root, device_id, report_text)
                        self._set_status(f"Generated LLM report for {device_id}")
                
                self.root.after(0, on_done)
            except Exception as e:
                err_msg = str(e)
                def on_error():
                    if progress_dialog.winfo_exists():
                        progress_dialog.destroy()
                    self._show_error("LLM Report Generation Error", err_msg)
                self.root.after(0, on_error)
                
        threading.Thread(target=task, daemon=True).start()

    def _backup_to_archive(self):
        if not self._require_device():
            return
        device_id = self.selected_device
        safe_id = re.sub(r'\s+', '', device_id)
        safe_id = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', safe_id).rstrip(' .') or 'device'
        if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', safe_id, re.IGNORECASE):
            safe_id = f'_{safe_id}'
        options = BackupOptionsDialog(
            self.root,
            self.config.get('backup', 'scope', 0),
            self.config.get('backup', 'parallelism', 4),
        ).result
        if options is None:
            return
        choice, parallelism = options
        self.config.set('backup', 'scope', choice)
        self.config.set('backup', 'parallelism', parallelism)
        verify_checksums = bool(self.config.get('backup', 'verify_checksums', False))
        exclusions = self.config.get('backup', 'exclude_paths', [])
        if not isinstance(exclusions, list):
            exclusions = []
        downloads_dir = Path.home() / 'Downloads'
        downloads_dir.mkdir(parents=True, exist_ok=True)
        backup_sets = [("internal storage (/storage/emulated/0)", '/storage/emulated/0', downloads_dir / f'{safe_id}_backup_progress')]
        if choice == 1:
            backup_sets.append(("system storage", 'system', downloads_dir / f'{safe_id}_system_backup_progress'))
        existing_dirs = [folder for _, _, folder in backup_sets if folder.exists()]
        if existing_dirs:
            if not messagebox.askyesno(
                "Replace Backup Folder?",
                "These backup folders already exist. Replace them?\n\n" + "\n".join(str(p) for p in existing_dirs),
                parent=self.root,
            ):
                return
            try:
                for folder in existing_dirs:
                    shutil.rmtree(folder)
            except OSError as exc:
                self._show_error("Backup Error", f"Could not replace the existing folder:\n{exc}")
                return

        cancel_event = BackupCancelToken()
        indexed_ack = threading.Event()
        index_started = threading.Event()
        progress_events = queue.Queue()
        failed_by_folder = {str(folder): [] for _, _, folder in backup_sets}
        verification_by_folder = {}
        poll_active = [True]
        dialog = BackupProgressDialog(self.root, f"Backing Up {device_id}", cancel_event)

        def poll_progress_events():
            index_updates = []

            def flush_index_updates():
                if index_updates:
                    section = index_updates[-1][0]
                    included = [item[2] for item in index_updates if item[3]]
                    dialog.add_indexed_paths(index_updates[-1][1], included, section, index_updates[-1][2])
                    index_updates.clear()

            for _ in range(500):
                try:
                    event = progress_events.get_nowait()
                except queue.Empty:
                    break
                stage = event[0]
                if stage == 'index':
                    index_updates.append((event[1], event[2], event[3], True))
                    continue
                if stage == 'index_skipped':
                    index_updates.append((event[1], event[2], event[3], False))
                    continue
                flush_index_updates()
                if stage == 'index_start':
                    dialog.start_indexing(event[1])
                    self.taskbar_progress.set_indeterminate()
                    event[2].set()
                elif stage == 'indexed':
                    dialog.set_queue(event[2], event[1])
                    self.taskbar_progress.set_value(0, len(event[2]))
                    dialog.status.config(text=f"Estimating size for {event[1]}...")
                    def check_space(section=event[1], root=event[4], ack=event[3]):
                        try:
                            estimate = self.device_manager.estimate_filesystem_size(device_id, root, cancel_event)
                            free = shutil.disk_usage(downloads_dir).free
                        except OSError:
                            estimate, free = None, 0
                        def continue_after_check():
                            if not dialog.winfo_exists():
                                cancel_event.set()
                                ack.set()
                                return
                            if estimate is not None and estimate > free:
                                estimate_text = BackupProgressDialog._format_byte_rate(estimate).replace('/s', '')
                                free_text = BackupProgressDialog._format_byte_rate(free).replace('/s', '')
                                proceed = messagebox.askyesno(
                                    "Low Disk Space",
                                    f"Estimated backup size: {estimate_text}\nAvailable space: {free_text}\n\nContinue anyway?",
                                    parent=dialog,
                                )
                                if not proceed:
                                    cancel_event.set()
                            ack.set()
                        self.root.after(0, continue_after_check)
                    threading.Thread(target=check_space, daemon=True).start()
                elif stage == 'download_current':
                    dialog.set_current_download(event[1], event[2], event[3], event[4])
                    self.taskbar_progress.set_value(event[1], event[2])
                    dialog.update_idletasks()
                elif stage == 'download':
                    dialog.set_download(event[1], event[2], event[3], event[4])
                    self.taskbar_progress.set_value(event[1], event[2])
                    dialog.update_idletasks()
                elif stage == 'download_rate':
                    dialog.set_download_rate(event[1], event[2], event[3], event[4])
                    self.taskbar_progress.set_value(event[1], event[2])
                elif stage == 'download_failed':
                    dialog.set_failed(event[1], event[2], event[3], event[4][0])
                elif stage == 'verification':
                    verification_by_folder[event[1]] = event[2]
                    dialog.status.config(text=f"Verified {event[2].get('verified', 0):,} files; "
                                              f"{len(event[2].get('invalid', [])):,} size/checksum errors")
                elif stage == 'verification_start':
                    dialog.status.config(text="Verifying downloaded file sizes and checksums...")
                    self.taskbar_progress.set_indeterminate()
                elif stage == 'done':
                    poll_active[0] = False
                    self._backup_download_done(dialog, event[1], event[2], event[3], event[4], event[5],
                                               event[6], event[7], event[8])
                elif stage == 'error':
                    poll_active[0] = False
                    self._backup_failed(dialog, event[1])
            flush_index_updates()
            if poll_active[0] and dialog.winfo_exists():
                dialog.after(10 if not progress_events.empty() else 50, poll_progress_events)

        dialog.after(50, poll_progress_events)

        def make_progress(section, backup_dir, root_path):
            def progress(stage, done, total, path, paths, indexed_root=root_path):
                if stage == 'index':
                    progress_events.put(('index', section, done, path))
                elif stage == 'index_skipped':
                    progress_events.put(('index_skipped', section, done, path))
                elif stage == 'indexed':
                    progress_events.put(('indexed', section, paths, indexed_ack, indexed_root))
                    indexed_ack.wait()
                elif stage == 'download_current':
                    progress_events.put(('download_current', done, total, path, paths))
                elif stage == 'download':
                    progress_events.put(('download', done, total, path, paths))
                elif stage == 'download_rate':
                    progress_events.put(('download_rate', done, total, path, paths))
                elif stage == 'download_failed':
                    failed_by_folder[str(backup_dir)].append((path, paths[0]))
                    progress_events.put(('download_failed', done, total, path, paths))
                elif stage == 'verification':
                    result = dict(paths)
                    result['verified'] = done
                    verification_by_folder[str(backup_dir)] = result
                    progress_events.put(('verification', str(backup_dir), result))
                elif stage == 'verification_start':
                    progress_events.put(('verification_start',))
            return progress

        def backup_task():
            try:
                completed = True
                for section, root_path, backup_dir in backup_sets:
                    if cancel_event.is_set():
                        completed = False
                        break
                    progress_events.put(('index_start', section, index_started))
                    index_started.wait()
                    index_started.clear()
                    indexed_ack.clear()
                    completed = self.device_manager.backup_filesystem(
                        device_id, str(backup_dir), cancel_event, make_progress(section, backup_dir, root_path),
                        root_path, parallelism, exclusions, None, verify_checksums
                    )
                    if not completed:
                        break
                progress_events.put(('done', backup_sets, cancel_event, completed, safe_id,
                                     failed_by_folder, parallelism, verify_checksums, verification_by_folder))
            except Exception as exc:
                progress_events.put(('error', str(exc)))

        threading.Thread(target=backup_task, daemon=True).start()

    def _restore_from_backup(self):
        if not self._require_device():
            return
        choose_zip = messagebox.askyesnocancel(
            "Choose Backup Source", "Restore from a ZIP archive?\n\nChoose No to select a backup folder.", parent=self.root
        )
        if choose_zip is None:
            return
        if choose_zip:
            archive_path = filedialog.askopenfilename(
                parent=self.root, title="Select Backup ZIP", filetypes=(("ZIP archives", "*.zip"), ("All files", "*.*"))
            )
            if not archive_path:
                return
            source_root = Path(archive_path)
            try:
                with zipfile.ZipFile(source_root) as archive:
                    remote_by_local = {}
                    try:
                        manifest = json.loads(archive.read('.droidmgr_backup_manifest.json').decode('utf-8'))
                        remote_by_local = {row['local_path'].replace('\\', '/'): row['remote_path']
                                           for row in manifest.get('files', [])}
                    except (KeyError, ValueError, TypeError, UnicodeDecodeError):
                        pass
                    candidates = []
                    for info in archive.infolist():
                        if info.is_dir() or info.filename.endswith('.droidmgr_index.json') or info.filename.endswith('.droidmgr_backup_manifest.json'):
                            continue
                        member = PurePosixPath(info.filename)
                        if member.is_absolute() or not member.parts or any(part in ('', '.', '..') for part in member.parts):
                            continue
                        mode = info.external_attr >> 16
                        if stat.S_ISLNK(mode):
                            continue
                        remote = remote_by_local.get(member.as_posix(), '/' + member.as_posix())
                        remote_parts = PurePosixPath(remote).parts
                        if not remote.startswith('/') or any(part == '..' for part in remote_parts):
                            continue
                        candidates.append((remote, ('zip', str(source_root), info.filename)))
            except (OSError, zipfile.BadZipFile) as exc:
                self._show_error("Restore Error", f"Could not read this ZIP archive:\n{exc}")
                return
        else:
            folder = filedialog.askdirectory(parent=self.root, title="Select Backup Folder")
            if not folder:
                return
            source_root = Path(folder)
            candidates = []
            remote_by_local = {}
            try:
                manifest = json.loads((source_root / '.droidmgr_backup_manifest.json').read_text(encoding='utf-8'))
                remote_by_local = {row['local_path'].replace('\\', '/'): row['remote_path']
                                   for row in manifest.get('files', [])}
            except (OSError, ValueError, KeyError, TypeError):
                pass
            if remote_by_local:
                for relative, remote in remote_by_local.items():
                    if PurePosixPath(relative).is_absolute() or '..' in PurePosixPath(relative).parts:
                        continue
                    local_path = source_root / Path(relative)
                    if local_path.is_file() and remote.startswith('/') and '..' not in PurePosixPath(remote).parts:
                        candidates.append((remote, ('file', str(local_path), None)))
            else:
                for path in source_root.rglob('*'):
                    if not path.is_file() or path.name.startswith('.droidmgr_'):
                        continue
                    relative = path.relative_to(source_root).as_posix()
                    member = PurePosixPath(relative)
                    if member.is_absolute() or any(part in ('', '.', '..') for part in member.parts):
                        continue
                    candidates.append(('/' + member.as_posix(), ('file', str(path), None)))
        if not candidates:
            messagebox.showinfo("No Backup Files", "No restorable files were found in that backup.", parent=self.root)
            return
        selected = RestoreSelectionDialog(self.root, candidates).result
        if not selected:
            return
        if not messagebox.askyesno(
            "Confirm Restore",
            f"Copy {len(selected):,} selected files to {self.selected_device}? Existing device files at those paths may be overwritten.",
            parent=self.root,
        ):
            return
        cancel_event = BackupCancelToken()
        dialog = BackupProgressDialog(self.root, f"Restoring to {self.selected_device}", cancel_event)
        dialog.set_queue([remote for remote, _source in selected], "restore")
        self.taskbar_progress.set_indeterminate()
        self._restore_batch(dialog, self.selected_device, selected, cancel_event)

    def _restore_batch(self, dialog, device_id, selected, cancel_event):
        cancel_event.clear()
        failures = []
        total = len(selected)
        dialog.set_queue([remote for remote, _source in selected], "restore")

        def task():
            completed = 0
            for index, (remote, source) in enumerate(selected):
                if cancel_event.is_set():
                    break
                pending_paths = [item[0] for item in selected[index + 1:]]
                self.root.after(0, lambda d=completed, t=total, p=remote, pending=pending_paths:
                                dialog.set_current_download(d, t, p, pending))
                temp_path = None
                try:
                    kind, location, member = source
                    local_path = location
                    if kind == 'zip':
                        with zipfile.ZipFile(location) as archive, archive.open(member) as source_file:
                            with tempfile.NamedTemporaryFile(prefix='droidmgr-restore-', delete=False) as temp_file:
                                temp_path = temp_file.name
                                shutil.copyfileobj(source_file, temp_file, 1024 * 1024)
                        local_path = temp_path
                    self.device_manager.upload_file(device_id, local_path, remote, cancel_event)
                    if cancel_event.is_set():
                        break
                    completed += 1
                    self.root.after(0, lambda d=completed, t=total: self.taskbar_progress.set_value(d, t))
                    self.root.after(0, lambda d=completed, t=total, p=remote, pending=[item[0] for item in selected[index + 1:]]:
                                    dialog.set_download(d, t, p, (pending, [], 0)))
                except Exception as exc:
                    failures.append((remote, str(exc)))
                    completed += 1
                    self.root.after(0, lambda d=completed, t=total, p=remote, e=str(exc):
                                    dialog.set_failed(d, t, p, e))
                finally:
                    if temp_path:
                        try:
                            os.unlink(temp_path)
                        except OSError:
                            pass
            self.root.after(0, lambda: self._restore_batch_done(dialog, device_id, selected, failures, cancel_event))

        threading.Thread(target=task, daemon=True).start()

    def _restore_batch_done(self, dialog, device_id, selected, failures, cancel_event):
        if cancel_event.is_set():
            self.taskbar_progress.clear()
            dialog.finish("Restore canceled. Files already copied remain on the device.", close_after_ms=600)
            return
        if failures:
            summary = "Some files could not be restored:\n\n" + "\n".join(
                f"{remote}: {error}" for remote, error in failures[:30]
            )
            if len(failures) > 30:
                summary += f"\n...and {len(failures) - 30} more."
            if messagebox.askyesno("Retry Failed Files?", summary + "\n\nRetry the failed files?", parent=dialog):
                failed_paths = {remote for remote, _error in failures}
                self._restore_batch(dialog, device_id,
                                    [item for item in selected if item[0] in failed_paths], cancel_event)
                return
            messagebox.showinfo("Restore Summary", summary, parent=dialog)
            self.taskbar_progress.clear()
            dialog.finish(f"Restore finished with {len(failures):,} failed files.")
        else:
            self.taskbar_progress.clear()
            dialog.finish(f"Restored {len(selected):,} files to {device_id}.")

    def _retry_backup_failures(self, dialog, backup_sets, failed_by_folder, cancel_event,
                               parallelism, verify_checksums, verification_by_folder):
        retries = {folder: list(items) for folder, items in failed_by_folder.items() if items}
        if not retries:
            return
        cancel_event.clear()
        failed_again = {str(folder): [] for _, _, folder in backup_sets}
        for section, _remote_root, folder in backup_sets:
            for remote, _error in retries.get(str(folder), []):
                row = dialog._queue_indexes.get(remote)
                if row is not None:
                    dialog.queue.delete(row)
                    dialog.queue.insert(row, remote)
            paths = [remote for remote, _error in retries.get(str(folder), [])]
            if paths:
                dialog.set_queue(paths, section)
                self.taskbar_progress.set_value(0, len(paths))

        def retry_task():
            try:
                for section, root_path, folder in backup_sets:
                    paths = [remote for remote, _error in retries.get(str(folder), [])]
                    if not paths or cancel_event.is_set():
                        continue

                    def progress(stage, done, total, path, details):
                        if stage == 'download':
                            self.root.after(0, lambda d=done, t=total: self.taskbar_progress.set_value(d, t))
                            self.root.after(0, lambda d=done, t=total, p=path, r=details:
                                            dialog.set_download(d, t, p, r))
                        elif stage == 'download_current':
                            self.root.after(0, lambda d=done, t=total, p=path, r=details:
                                            dialog.set_current_download(d, t, p, r))
                        elif stage == 'download_failed':
                            failed_again[str(folder)].append((path, details[0]))
                            self.root.after(0, lambda d=done, t=total, p=path, r=details[0]:
                                            dialog.set_failed(d, t, p, r))
                        elif stage == 'download_rate':
                            self.root.after(0, lambda d=done, t=total: self.taskbar_progress.set_value(d, t))
                            self.root.after(0, lambda d=done, t=total, p=path, r=details:
                                            dialog.set_download_rate(d, t, p, r))
                        elif stage == 'verification':
                            result = dict(details)
                            result['verified'] = done
                            result['indexed'] = verification_by_folder.get(str(folder), {}).get(
                                'indexed', result.get('indexed', done)
                            )
                            self.root.after(0, lambda r=result, key=str(folder): verification_by_folder.__setitem__(key, r))
                        elif stage == 'verification_start':
                            self.root.after(0, self.taskbar_progress.set_indeterminate)

                    self.device_manager.backup_filesystem(
                    self.selected_device, str(folder), cancel_event, progress,
                        root_path, parallelism, [], paths, verify_checksums
                    )
                remaining = [(folder, remote, error) for folder, items in failed_again.items()
                             for remote, error in items]
                self.root.after(0, lambda: self._retry_backup_done(
                    dialog, backup_sets, cancel_event, failed_again, remaining, parallelism, verify_checksums
                    , verification_by_folder
                ))
            except Exception as exc:
                self.root.after(0, lambda error=str(exc): self._backup_failed(dialog, error))

        threading.Thread(target=retry_task, daemon=True).start()

    def _retry_backup_done(self, dialog, backup_sets, cancel_event, failed_by_folder, remaining,
                           parallelism, verify_checksums, verification_by_folder):
        if cancel_event.is_set():
            self.taskbar_progress.clear()
            dialog.finish("Retry canceled. Downloaded files were kept.", close_after_ms=600)
            return
        if remaining:
            summary = "Still unable to download:\n\n" + "\n".join(
                f"{remote}: {error}" for _folder, remote, error in remaining[:30]
            )
            if len(remaining) > 30:
                summary += f"\n...and {len(remaining) - 30} more."
            if messagebox.askyesno("Retry Failed Files?", summary + "\n\nTry these files again?", parent=dialog):
                self._retry_backup_failures(dialog, backup_sets, failed_by_folder, cancel_event,
                                            parallelism, verify_checksums, verification_by_folder)
                return
            messagebox.showinfo("Backup File Summary", summary, parent=dialog)
        self._backup_download_done(dialog, backup_sets, cancel_event, True,
                                   re.sub(r'\s+', '', self.selected_device or 'device'),
                                   failed_by_folder, parallelism, verify_checksums,
                                   verification_by_folder, allow_retry=False)

    def _backup_download_done(self, dialog, backup_sets, cancel_event, completed, safe_id,
                              failed_by_folder, parallelism, verify_checksums, verification_by_folder,
                              allow_retry=True):
        if not dialog.winfo_exists():
            return
        backup_dirs = [folder for _, _, folder in backup_sets]
        if not completed:
            self.taskbar_progress.clear()
            dialog.finish("Backup canceled. Downloaded files were kept.", close_after_ms=600)
            return
        failures = [(folder, remote, error) for folder, items in failed_by_folder.items()
                    for remote, error in items]
        for folder, result in verification_by_folder.items():
            for remote, error in result.get('invalid', []):
                if not any(existing_remote == remote for _folder, existing_remote, _reason in failures):
                    failures.append((folder, remote, error))
                    failed_by_folder.setdefault(folder, []).append((remote, error))
        verification_lines = []
        for folder, result in verification_by_folder.items():
            invalid = result.get('invalid', [])
            checksum_note = " with SHA-256" if result.get('checksums') else " (file sizes)"
            checked = BackupProgressDialog._format_byte_rate(result.get('bytes', 0)).replace('/s', '')
            verification_lines.append(
                f"{folder}: {result.get('verified', 0):,}/{result.get('indexed', result.get('verified', 0)):,} files verified{checksum_note}; "
                f"{len(invalid):,} mismatches; {checked} checked"
            )
        if verification_lines:
            messagebox.showinfo("Backup Verification", "\n".join(verification_lines), parent=dialog)
        if failures:
            summary = "Some files could not be downloaded:\n\n" + "\n".join(
                f"{remote}: {error}" for _folder, remote, error in failures[:30]
            )
            if len(failures) > 30:
                summary += f"\n...and {len(failures) - 30} more."
            if allow_retry and messagebox.askyesno("Retry Failed Files?", summary + "\n\nRetry the failed files now?", parent=dialog):
                self._retry_backup_failures(dialog, backup_sets, failed_by_folder, cancel_event,
                                            parallelism, verify_checksums, verification_by_folder)
                return
            if not allow_retry:
                summary += "\n\nBackup is partial. The rest of the backup is available."
            messagebox.showinfo("Backup File Summary", summary, parent=dialog)
        sections = [name for name, _, _ in backup_sets]
        if not messagebox.askyesno(
            "Create ZIP Archive?",
            "Backup finished. Create separate ZIP archives for " + " and ".join(sections) + " and remove the staging folders?",
            parent=dialog,
        ):
            self.taskbar_progress.clear()
            dialog.finish("Backups saved to:\n" + "\n".join(str(folder) for folder in backup_dirs))
            return

        cancel_event.clear()
        archive_paths = [
            Path.home() / 'Downloads' / f"{safe_id}_{'internal_storage' if i == 0 else 'system_storage'}_backup.zip"
            for i in range(len(backup_sets))
        ]
        existing_archives = [path for path in archive_paths if path.exists()]
        if existing_archives and not messagebox.askyesno(
            "Replace Archives?",
            "These ZIP archives already exist. Replace them?\n\n" + "\n".join(str(p) for p in existing_archives),
            parent=dialog,
        ):
            self.taskbar_progress.clear()
            dialog.finish("Backups saved to:\n" + "\n".join(str(folder) for folder in backup_dirs))
            return

        def zip_task():
            created_archives = []
            try:
                all_files = [path for folder in backup_dirs for path in folder.rglob('*')
                             if path.is_file() and path.name != '.droidmgr_index.json']
                total = len(all_files)
                done = 0
                for backup_dir, archive_path in zip(backup_dirs, archive_paths):
                    if archive_path.exists():
                        archive_path.unlink()
                    created_archives.append(archive_path)
                    files = [path for path in backup_dir.rglob('*')
                             if path.is_file() and path.name != '.droidmgr_index.json']
                    with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                        for path in files:
                            if cancel_event.is_set():
                                raise InterruptedError("Archive creation canceled")
                            arcname = path.relative_to(backup_dir).as_posix()
                            with path.open('rb') as source, archive.open(arcname, 'w') as target:
                                while True:
                                    if cancel_event.is_set():
                                        raise InterruptedError("Archive creation canceled")
                                    chunk = source.read(1024 * 1024)
                                    if not chunk:
                                        break
                                    target.write(chunk)
                            done += 1
                            self.root.after(0, lambda i=done, n=total, p=path: self._set_archive_progress(dialog, i, n, p))
                if cancel_event.is_set():
                    raise InterruptedError("Archive creation canceled")
                for backup_dir in backup_dirs:
                    shutil.rmtree(backup_dir)
                self.root.after(0, lambda: self._finish_backup(dialog, "Archives saved to:\n" + "\n".join(str(p) for p in archive_paths)))
            except InterruptedError:
                for path in created_archives:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
                self.root.after(0, lambda: self._finish_backup(dialog,
                    "Archive canceled. Backup folders were kept.", close_after_ms=600
                ))
            except Exception as exc:
                for path in created_archives:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
                self.root.after(0, lambda error=str(exc): self._backup_failed(dialog, error))

        dialog.status.config(text="Preparing ZIP archives...")
        dialog.progress.configure(value=0)
        threading.Thread(target=zip_task, daemon=True).start()

    def _backup_failed(self, dialog, error):
        self.taskbar_progress.clear()
        if dialog.winfo_exists():
            dialog.finish("Backup failed. Any downloaded files were kept.")
        self._show_error("Backup Error", error)

    def _set_archive_progress(self, dialog, done, total, path):
        if dialog.winfo_exists():
            dialog.set_archiving(done, total, str(path))
        self.taskbar_progress.set_value(done, total)

    def _finish_backup(self, dialog, message, close_after_ms=None):
        self.taskbar_progress.clear()
        if dialog.winfo_exists():
            dialog.finish(message, close_after_ms=close_after_ms)
        
    def _copy_processes_list(self):
        items = self.process_tree.get_children()
        if not items:
            self._show_warning("No processes to copy")
            return
            
        headers = ['PID', 'User', 'CPU%', 'Memory', 'Process Name']
        
        # Get all rows
        rows = []
        for item in items:
            vals = self.process_tree.item(item, 'values')
            if vals:
                rows.append([str(v) for v in vals])
                
        if not rows:
            self._show_warning("No process list data available to copy")
            return
            
        # Determine maximum width for each column to align nicely
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, val in enumerate(row):
                if i < len(col_widths):
                    col_widths[i] = max(col_widths[i], len(val))
                    
        # Generate formatted markdown table
        header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
        separator_line = "|-" + "-|-".join("-" * col_widths[i] for i in range(len(headers))) + "-|"
        
        table_lines = [header_line, separator_line]
        for row in rows:
            row_line = "| " + " | ".join(val.ljust(col_widths[i]) for i, val in enumerate(row)) + " |"
            table_lines.append(row_line)
            
        table_text = "\n".join(table_lines)
        
        self.root.clipboard_clear()
        self.root.clipboard_append(table_text)
        self._set_status("Process list copied as formatted table!")
        
        self.copy_processes_btn.config(text="Copied!")
        self.root.after(2000, lambda: self.copy_processes_btn.config(text="Copy Process List"))

    def _show_process_info(self, event=None):
        selection = self.process_tree.selection()
        if not selection:
            return
            
        item_id = selection[0]
        values = self.process_tree.item(item_id, 'values')
        if not values:
            return
            
        pid, user, cpu, mem, name = values
        
        proc_info = {
            'pid': pid,
            'user': user,
            'cpu': cpu,
            'mem': mem,
            'name': name
        }
        
        # Check if the process name looks like a package or is in the installed app list
        is_package_guess = '.' in name and not name.startswith('/') and '[' not in name
        
        if is_package_guess:
            def task():
                try:
                    info = self.device_manager.adb.get_app_info(self.selected_device, name)
                    self.root.after(0, lambda: AppInfoDialog(self.root, info, self.selected_device, self.device_manager))

                except Exception:
                    self.root.after(0, lambda: ProcessInfoDialog(self.root, proc_info))
            threading.Thread(target=task, daemon=True).start()
        else:
            ProcessInfoDialog(self.root, proc_info)

    def _sort_processes_by_column(self, col):
        if hasattr(self, 'process_sort_col') and self.process_sort_col == col:
            self.process_sort_reverse = not self.process_sort_reverse
        else:
            self.process_sort_col = col
            if col in ('PID', 'User', 'Name'):
                self.process_sort_reverse = False
            else:
                self.process_sort_reverse = True
                
        # Immediate UI sorting for instant feedback
        children = [(self.process_tree.set(k, col), k) for k in self.process_tree.get_children('')]
        
        def get_sort_key(item):
            val = item[0]
            if col == 'PID':
                try:
                    return int(val)
                except ValueError:
                    return 0
            elif col == 'CPU%':
                try:
                    return float(val.replace('%', ''))
                except ValueError:
                    return 0.0
            elif col == 'Memory':
                try:
                    return _parse_memory(val)
                except Exception:
                    return 0.0
            else:
                return val.lower()
                
        children.sort(key=get_sort_key, reverse=self.process_sort_reverse)
        
        for index, (_, k) in enumerate(children):
            self.process_tree.move(k, '', index)
            
        self._set_status(f"Sorted processes by {col} ({'descending' if self.process_sort_reverse else 'ascending'})")

    def _sort_apps_by_column(self, col):
        """Sort the applications list by a heading click, toggling the direction."""
        if getattr(self, 'app_sort_col', None) == col:
            self.app_sort_reverse = not self.app_sort_reverse
        else:
            self.app_sort_col = col
            # Biggest first for Size, alphabetical for everything else
            self.app_sort_reverse = col == 'Size'

        self._apply_app_sort()
        direction = 'descending' if self.app_sort_reverse else 'ascending'
        self._set_status(f"Sorted applications by {col} ({direction})")

    def _apply_app_sort(self):
        """Reorder the rows already listed, without re-querying the device."""
        col = getattr(self, 'app_sort_col', None)
        if not col:
            return

        def row_key(item_id):
            val = self.app_tree.set(item_id, col)
            if col == 'Size':
                try:
                    return _parse_memory(val)
                except Exception:
                    return 0
            return val.lower()

        items = [(row_key(item_id), item_id) for item_id in self.app_tree.get_children('')]
        items.sort(key=lambda pair: pair[0], reverse=self.app_sort_reverse)
        for index, (_, item_id) in enumerate(items):
            self.app_tree.move(item_id, '', index)


        
    def _check_signals(self):
        # Periodically yield control back to the Python interpreter so it can process signals (like SIGINT/Ctrl+C) instantly
        self.root.after(100, self._check_signals)
    
    def _on_closing(self):


        self.taskbar_progress.close()
        try:
            self.logcat_view.destroy()
        except Exception:
            pass
        try:
            self.shell_view.destroy()
        except Exception:
            pass
        self.device_manager.cleanup()
        self.root.destroy()
    
    def run(self):
        self.root.mainloop()
