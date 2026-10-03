"""MainWindow mixin: menu bar, preferences, about, scrcpy settings."""

import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox
from typing import Dict, List, Optional
from core import DeviceManager
from .about_dialog import AboutDialog
from .preferences_dialog import PreferencesDialog
from .scrcpy_settings_dialog import ScrcpySettingsDialog


class _MenuMixin:
    """_MenuMixin for MainWindow (see main_window.py)."""

    def _create_menu(self):
        # View-mode variables live here (before the notebook exists) so the
        # View menu, the toolbars and the tab widgets all share one source.
        # Modes are remembered across sessions via the config file.
        if not hasattr(self, 'app_view_mode_var') or self.app_view_mode_var is None:
            self.app_view_mode_var = tk.StringVar(
                value=self.config.get('applications', 'view_mode', 'grid'))
        if not hasattr(self, 'file_view_mode_var') or self.file_view_mode_var is None:
            self.file_view_mode_var = tk.StringVar(
                value=self.config.get('file_manager', 'view_mode', 'list'))

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
        device_menu.add_command(label="Reboot to Fastboot (Bootloader)", command=lambda: self._power_action('bootloader'))
        device_menu.add_command(label="Reboot from Fastboot to Android", command=self._fastboot_reboot)
        self.fastboot_reboot_menu_index = device_menu.index('end')
        device_menu.entryconfig(self.fastboot_reboot_menu_index, state=tk.DISABLED)
        device_menu.add_command(label="Shut Down", command=lambda: self._power_action('shutdown'))
        device_menu.add_separator()
        device_menu.add_command(label="Check Root Access", command=self._check_root_access)
        device_menu.add_command(label="Reconnect ADB", command=self._reconnect_adb)
        device_menu.add_separator()
        device_menu.add_command(label="Backup to archive...", command=self._backup_to_archive)
        device_menu.add_command(label="Restore from backup...", command=self._restore_from_backup)
        device_menu.add_separator()
        device_menu.add_command(label="Generate LLM Report", command=self._generate_llm_report)
        device_menu.add_command(label="Collect Bug Report...", command=self._collect_bugreport)

        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Take Screenshot", command=self._take_screenshot)
        tools_menu.add_command(label="Record Screen...", command=self._record_screen)
        tools_menu.add_separator()
        tools_menu.add_command(label="Port Forwarding...", command=self._show_forward_dialog)

        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)

        apps_view_menu = tk.Menu(view_menu, tearoff=0)
        view_menu.add_cascade(label="Applications", menu=apps_view_menu)
        apps_view_menu.add_radiobutton(label="Grid View", variable=self.app_view_mode_var,
                                       value="grid", command=self._switch_app_view_mode)
        apps_view_menu.add_radiobutton(label="List View", variable=self.app_view_mode_var,
                                       value="list", command=self._switch_app_view_mode)

        files_view_menu = tk.Menu(view_menu, tearoff=0)
        view_menu.add_cascade(label="Files", menu=files_view_menu)
        files_view_menu.add_radiobutton(label="Grid View", variable=self.file_view_mode_var,
                                        value="grid", command=self._switch_file_view_mode)
        files_view_menu.add_radiobutton(label="List View", variable=self.file_view_mode_var,
                                        value="list", command=self._switch_file_view_mode)

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self._show_about)

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
        self.config = config

        # View modes apply live: the toolbars and View menu share these vars.
        try:
            self.app_view_mode_var.set(config.get('applications', 'view_mode', 'grid'))
            self._switch_app_view_mode()
        except Exception:
            pass
        try:
            self.file_view_mode_var.set(config.get('file_manager', 'view_mode', 'list'))
            if hasattr(self, 'file_manager'):
                self.file_manager.set_view_mode(self.file_view_mode_var.get())
        except Exception:
            pass
        
        adb_path = config.get('paths', 'adb')
        scrcpy_path = config.get('paths', 'scrcpy')
        
        if adb_path:
            self.adb_path = Path(adb_path)
        if scrcpy_path:
            self.scrcpy_path = Path(scrcpy_path)
            
        try:
            old_registry = getattr(getattr(self, 'device_manager', None), 'registry', None)
            if old_registry is not None:
                old_registry.save(force=True)
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

