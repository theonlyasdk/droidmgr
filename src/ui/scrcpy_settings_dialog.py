import tkinter as tk
from tkinter import ttk
from core import ConfigManager
from .dpi import setup_window_dpi
from .scrcpy_settings_tooltip import ToolTip
from .scrcpy_video_settings import VideoSettingsMixin
from .scrcpy_audio_settings import AudioSettingsMixin
from .scrcpy_control_settings import ControlSettingsMixin
from .scrcpy_window_settings import WindowSettingsMixin
from .scrcpy_save_settings import SaveSettingsMixin


__all__ = [
    'ScrcpySettingsDialog',
    'ToolTip',
]


class ScrcpySettingsDialog(
    VideoSettingsMixin,
    AudioSettingsMixin,
    ControlSettingsMixin,
    WindowSettingsMixin,
    SaveSettingsMixin,
    tk.Toplevel,
):
    def __init__(self, parent, device_id=None, scrcpy_manager=None):
        super().__init__(parent)
        self.title("scrcpy Settings")
        self.parent = parent
        self.device_id = device_id
        self.scrcpy_manager = scrcpy_manager
        self.config = ConfigManager()
        self.result = None
        
        self.geometry("600x550")
        self.resizable(True, True)
        self.transient(parent)
        
        # Main container
        self.container = ttk.Frame(self, padding="10")
        self.container.pack(fill=tk.BOTH, expand=True)
        
        # Tabs for better organization
        self.notebook = ttk.Notebook(self.container)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        self.video_tab = ttk.Frame(self.notebook, padding=10)
        self.audio_tab = ttk.Frame(self.notebook, padding=10)
        self.control_tab = ttk.Frame(self.notebook, padding=10)
        self.window_tab = ttk.Frame(self.notebook, padding=10)
        
        self.notebook.add(self.video_tab, text="Video/Camera")
        self.notebook.add(self.audio_tab, text="Audio")
        self.notebook.add(self.control_tab, text="Control")
        self.notebook.add(self.window_tab, text="Window/Other")
        
        self._create_video_settings()
        self._create_audio_settings()
        self._create_control_settings()
        self._create_window_settings()
        
        # Buttons
        btn_frame = ttk.Frame(self.container, padding=(0, 10, 0, 0))
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        ttk.Button(btn_frame, text="Save", command=self._on_save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        
        # Initial states
        self._toggle_camera_settings()
        self._toggle_record_settings()
        
        setup_window_dpi(self, base_width=600, base_height=550, min_width=500, min_height=450, parent=parent)
            
        # Ensure window is visible before grabbing
        self.wait_visibility()
        self.grab_set()
        self.bind('<Escape>', lambda e: self.destroy())

    def _add_tooltip(self, widget, text):
        ToolTip(widget, text)
