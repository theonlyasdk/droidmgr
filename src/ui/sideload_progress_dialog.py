"""Determinate progress while a device reaches sideload mode and applies a zipped update.

adb prints the transfer percentage while streaming the package, and the bar
runs on it. The caller closes the window with the outcome only, never
mid-transfer, so there is no cancel button.
"""

import tkinter as tk
from tkinter import ttk

from .dpi import setup_window_dpi


class SideloadProgressDialog(tk.Toplevel):
    def __init__(self, parent, package_name: str, filesize_mb: float,
                 device_id: str, waiting_for_sideload: bool):
        super().__init__(parent)
        self.title('Applying Update...')
        self.geometry("440x190")
        self.resizable(False, False)
        self.transient(parent)

        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame,
                  text=f"Applying '{package_name}' ({filesize_mb:.1f} MB) "
                       f"to '{device_id}'...",
                  font=('', 10, 'bold'), wraplength=400,
                  justify='left').pack(anchor='w', pady=(0, 8))

        self._stage = tk.StringVar(
            self,
            f"Waiting for '{device_id}' to reach sideload mode..."
            if waiting_for_sideload
            else f"Device '{device_id}' is in sideload mode; starting...")

        ttk.Label(frame, textvariable=self._stage, wraplength=400,
                  justify='left').pack(anchor='w', pady=(0, 10))

        self._bar = ttk.Progressbar(frame, mode='determinate',
                                    maximum=100, value=0)
        self._bar.pack(fill=tk.X, ipady=3)

        ttk.Label(frame,
                  text="The device applies the package while it streams; "
                       "keep it plugged in to the end.",
                  wraplength=400,
                  font=('', 9, 'italic')).pack(anchor='w', pady=(10, 0))

        setup_window_dpi(self, base_width=440, base_height=190,
                         min_width=400, min_height=160, parent=parent)
        self.grab_set()

    def set_stage(self, text: str):
        """Swap the line describing what the update is doing right now."""
        self._stage.set(text)

    def set_percent(self, percent: int):
        """Show adb's transfer percentage; values outside 0-100 clamp."""
        self._bar['value'] = max(0, min(100, int(percent)))

    def close(self):
        """Take the window down (called from the UI thread)."""
        self.destroy()
