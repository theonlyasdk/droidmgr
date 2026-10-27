"""Indeterminate progress while fastboot reaches and flashes a device.

One small window covers the whole flash: rebooting to the bootloader when the
device still runs Android, waiting for fastboot mode, and the flash itself.
The caller closes it through close() with the outcome, never mid-flash, so
there is no cancel button.
"""

import tkinter as tk
from tkinter import ttk

from .dpi import setup_window_dpi


class FlashProgressDialog(tk.Toplevel):
    def __init__(self, parent, image_name: str, filesize_mb: float,
                 partition: str, device_id: str, waiting_for_fastboot: bool):
        super().__init__(parent)
        self.title("Flashing Image...")
        self.geometry("440x190")
        self.resizable(False, False)
        self.transient(parent)

        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame,
                  text=f"Flashing '{image_name}' ({filesize_mb:.1f} MB) to '{partition}'...",
                  font=('', 10, 'bold'), wraplength=400,
                  justify='left').pack(anchor='w', pady=(0, 8))

        self._stage = tk.StringVar(
            self,
            f"Waiting for '{device_id}' to reach fastboot mode..."
            if waiting_for_fastboot
            else f"Device '{device_id}' is in fastboot mode; starting...")

        ttk.Label(frame, textvariable=self._stage, wraplength=400,
                  justify='left').pack(anchor='w', pady=(0, 10))

        self._bar = ttk.Progressbar(frame, mode='indeterminate', maximum=100)
        self._bar.pack(fill=tk.X)
        self._bar.start(14)

        ttk.Label(frame, text="Keep the device plugged in until the flash ends.",
                  wraplength=400,
                  font=('', 9, 'italic')).pack(anchor='w', pady=(10, 0))

        setup_window_dpi(self, base_width=440, base_height=190,
                         min_width=400, min_height=160, parent=parent)
        self.grab_set()

    def set_stage(self, text: str):
        """Swap the line describing what the flash is doing right now."""
        self._stage.set(text)

    def close(self):
        """Stop the marquee and take the window down (called from the UI thread)."""
        try:
            self._bar.stop()
        except Exception:
            pass
        self.destroy()
