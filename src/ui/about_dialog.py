"""About dialog for droidmgr."""

import tkinter as tk
from tkinter import ttk, font
from .dpi import setup_window_dpi


def _light_font(size):
    """Segoe UI Light where available, else the regular face (never fails)."""
    try:
        available = set(font.families())
    except Exception:
        available = set()
    family = 'Segoe UI Light' if 'Segoe UI Light' in available else 'Segoe UI'
    return (family, size)


class AboutDialog:

    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("About droidmgr")
        self.dialog.transient(parent)

        self._create_widgets()
        setup_window_dpi(self.dialog, base_width=360, base_height=280, min_width=320, min_height=240, parent=parent)

        # Ensure window is visible before grabbing
        self.dialog.wait_visibility()
        self.dialog.grab_set()
        self.dialog.bind('<Escape>', lambda e: self.dialog.destroy())

    def _create_widgets(self):
        main_frame = ttk.Frame(self.dialog, padding=24)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            main_frame,
            text="Droidmgr",
            font=_light_font(30),
            fg='#2196F3'
        ).pack(pady=(0, 2))

        tk.Label(
            main_frame,
            text="Version 1.2.0",
            font=_light_font(12),
            fg='gray'
        ).pack()

        ttk.Separator(main_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=16)

        tk.Label(
            main_frame,
            text="Android device manager & scrcpy frontend",
            font=('Segoe UI', 10),
            justify=tk.CENTER
        ).pack()

        tk.Label(
            main_frame,
            text="© 2026 theonlyasdk  ·  MPL 2.0",
            font=('Segoe UI', 8),
            fg='gray'
        ).pack(pady=(12, 0))

        ttk.Button(
            main_frame,
            text="Close",
            command=self.dialog.destroy,
            width=15
        ).pack(pady=(16, 0))

    def show(self):
        self.dialog.wait_window()
