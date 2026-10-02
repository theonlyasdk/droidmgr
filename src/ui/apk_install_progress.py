"""Progress dialog shown while a large APK is pushed and installed."""

import tkinter as tk
from tkinter import ttk

from .dpi import setup_window_dpi


class APKInstallProgressDialog(tk.Toplevel):
    def __init__(self, parent, filename: str, filesize_mb: float):
        super().__init__(parent)
        self.title("Installing APK...")
        self.geometry("420x150")
        self.resizable(False, False)
        self.transient(parent)
        
        frame = ttk.Frame(self, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(
            frame, 
            text=f"Installing '{filename}' ({filesize_mb:.1f} MB)...", 
            font=('', 10, 'bold'), 
            wraplength=380
        ).pack(anchor='w', pady=(0, 5))
        
        ttk.Label(frame, text="Please wait while ADB pushes and installs the package.", font=('', 9)).pack(anchor='w', pady=(0, 15))
        
        self.progressbar = ttk.Progressbar(frame, mode='indeterminate')
        self.progressbar.pack(fill=tk.X, expand=True)
        self.progressbar.start(10)
        
        setup_window_dpi(self, base_width=420, base_height=150, parent=parent)
            
        self.protocol("WM_DELETE_WINDOW", lambda: None)
        self.grab_set()

    def close(self):
        try:
            self.progressbar.stop()
            self.grab_release()
            self.destroy()
        except Exception:
            pass
