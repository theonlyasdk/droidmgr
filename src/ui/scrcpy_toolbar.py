"""Shell widgets (buttons, drag grip) for the scrcpy overlay toolbar."""

import subprocess
import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable

from .scrcpy_overlay_tooltip import _Tooltip


class ScrcpyToolbarMixin:
    """Shell widget methods for ScrcpyOverlayToolbar."""


    def __init__(
        self,
        parent: tk.Tk,
        process: subprocess.Popen,
        device_id: str,
        device_manager,
        stop_callback: Optional[Callable[[str], None]] = None,
        show_settings_callback: Optional[Callable[[], None]] = None,
        take_screenshot_callback: Optional[Callable[[], None]] = None,
        record_screen_callback: Optional[Callable[[], None]] = None,
        window_title: Optional[str] = None,
    ):
        super().__init__(parent)
        self.process = process
        self.device_id = device_id
        self.device_manager = device_manager
        self.stop_callback = stop_callback
        self.show_settings_callback = show_settings_callback
        self.take_screenshot_callback = take_screenshot_callback
        self.record_screen_callback = record_screen_callback
        self.target_window_title = window_title

        self.scrcpy_hwnd = None
        self._following = True
        self._is_pinned = False
        self._last_rect = None
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._is_alive = True

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.config(background="#1a1a1a", borderwidth=1, relief=tk.SOLID)

        self._create_widgets()
        self._bind_drag()

        # Start tracking thread / loop
        self.after(200, self._track_scrcpy_window)

    def _get_device_id(self) -> Optional[str]:
        if self.device_id:
            return self.device_id
        if self.device_manager:
            try:
                devs = self.device_manager.get_devices()
                if devs:
                    return devs[0].get('id')
            except Exception:
                pass
        return None

    def _create_widgets(self):
        container = tk.Frame(self, background="#1a1a1a")
        container.pack(fill=tk.BOTH, expand=True, padx=2, pady=4)

        # Drag grip handle at top
        grip = tk.Label(
            container, text="⋮", font=("Segoe UI", 11, "bold"),
            background="#1a1a1a", foreground="#777777", cursor="fleur"
        )
        grip.pack(side=tk.TOP, pady=(1, 3))
        self.grip = grip

        # Vertical Button definitions: (icon, command, tooltip, color)
        # Larger icon glyphs
        buttons = [
            ("⏻", self._on_power, "Power (Screen On/Off)", "#EF5350"),
            ("🔒", self._on_lock_wake, "Lock / Wake Device", "#FFA726"),
            ("🔊", self._on_vol_up, "Volume Up", "#eeeeee"),
            ("🔉", self._on_vol_down, "Volume Down", "#eeeeee"),
            ("---", None, None, None),
            ("◀", self._on_back, "Back (◁)", "#4FC3F7"),
            ("○", self._on_home, "Home (○)", "#81C784"),
            ("▢", self._on_recents, "Recents (▢)", "#FFD54F"),
            ("---", None, None, None),
            ("T", self._on_text_input, "Send Text / Clipboard", "#CE93D8"),
            ("🔄", self._on_rotate, "Rotate Screen", "#4DD0E1"),
            ("📷", self._on_screenshot, "Take Screenshot", "#66BB6A"),
            ("📹", self._on_record, "Record Screen", "#F06292"),
            ("---", None, None, None),
            ("📌", self._on_toggle_pin, "Always on Top (Pin)", "#FFB74D"),
            ("🧲", self._on_snap_window, "Snap to Right Edge", "#64B5F6"),
            ("⚙", self._on_settings, "Scrcpy Settings", "#B0BEC5"),
            ("---", None, None, None),
            ("✕", self._on_close, "Stop Mirroring", "#E57373"),
        ]

        self.btn_widgets = {}
        for icon, cmd, tip, fg in buttons:
            if icon == "---":
                sep = tk.Frame(container, height=1, background="#333333", width=32)
                sep.pack(side=tk.TOP, fill=tk.X, padx=4, pady=3)
                continue

            btn = tk.Button(
                container, text=icon, font=("Segoe UI", 12, "bold"),
                command=cmd, width=3, height=1, relief=tk.FLAT,
                background="#252525", foreground=fg or "#ffffff",
                activebackground="#0e639c", activeforeground="#ffffff",
                cursor="hand2", bd=0, padx=2, pady=2
            )
            btn.pack(side=tk.TOP, pady=1)
            self._add_hover(btn)
            if tip:
                _Tooltip(btn, tip, side="left")
            self.btn_widgets[icon] = btn

    def _add_hover(self, btn):
        orig_bg = btn.cget("background")
        btn.bind("<Enter>", lambda e: btn.config(background="#383838"))
        btn.bind("<Leave>", lambda e: btn.config(background=orig_bg))

    def _bind_drag(self):
        for widget in (self, self.grip):
            widget.bind("<Button-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._do_drag)

    def _start_drag(self, event):
        self._drag_start_x = event.x_root - self.winfo_x()
        self._drag_start_y = event.y_root - self.winfo_y()

    def _do_drag(self, event):
        self._following = False  # User manually positioned
        x = event.x_root - self._drag_start_x
        y = event.y_root - self._drag_start_y
        self.geometry(f"+{x}+{y}")
