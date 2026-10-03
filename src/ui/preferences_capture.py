"""Preferences capture tab: default folders and recording defaults."""

import tkinter as tk
from tkinter import ttk, filedialog


class PreferencesCaptureMixin:
    """Default save folders and screen-recording defaults."""

    def _create_capture_tab(self):
        tab = ttk.Frame(self.dialog)

        folders = ttk.LabelFrame(tab, text="Default Folders", padding=10)
        folders.pack(fill=tk.X, padx=10, pady=10)
        folders.columnconfigure(1, weight=1)

        self.screenshot_dir_var = tk.StringVar()
        self.record_dir_var = tk.StringVar()
        self.apk_dir_var = tk.StringVar()
        rows = (
            ("Screenshots:", self.screenshot_dir_var, "Pictures/droidmgr"),
            ("Recordings:", self.record_dir_var, "Videos/droidmgr"),
            ("APK extracts:", self.apk_dir_var, "Downloads/droidmgr"),
        )
        for row, (label, var, hint) in enumerate(rows):
            ttk.Label(folders, text=label).grid(row=row, column=0, sticky=tk.W, pady=4)
            ttk.Entry(folders, textvariable=var).grid(
                row=row, column=1, sticky=tk.EW, padx=5, pady=4)
            ttk.Button(folders, text="Browse...",
                       command=lambda v=var: self._browse_capture_dir(v)).grid(
                           row=row, column=2, pady=4)
            ttk.Label(folders, text=f"Empty = {hint}", foreground="gray").grid(
                row=row, column=3, sticky=tk.W, padx=(5, 0), pady=4)

        rec = ttk.LabelFrame(tab, text="Screen Recording Defaults", padding=10)
        rec.pack(fill=tk.X, padx=10, pady=10)
        rec.columnconfigure(1, weight=1)

        ttk.Label(rec, text="Time limit (seconds):").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.record_limit_var = tk.StringVar()
        ttk.Spinbox(rec, textvariable=self.record_limit_var, from_=1, to=180,
                    width=8).grid(row=0, column=1, sticky=tk.W, padx=5, pady=4)

        self.record_bitrate_var = tk.StringVar()
        self.record_size_var = tk.StringVar()
        ttk.Label(rec, text="Bit rate (blank = device default):").grid(
            row=1, column=0, sticky=tk.W, pady=4)
        ttk.Entry(rec, textvariable=self.record_bitrate_var, width=12).grid(
            row=1, column=1, sticky=tk.W, padx=5, pady=4)
        ttk.Label(rec, text="Size, e.g. 1280x720 (blank = native):").grid(
            row=2, column=0, sticky=tk.W, pady=4)
        ttk.Entry(rec, textvariable=self.record_size_var, width=12).grid(
            row=2, column=1, sticky=tk.W, padx=5, pady=4)

        return tab

    def _browse_capture_dir(self, var):
        directory = filedialog.askdirectory(parent=self.dialog)
        if directory:
            var.set(directory)

    def _load_capture_settings(self):
        get = self.config.get
        self.screenshot_dir_var.set(get('capture', 'screenshot_dir', '') or '')
        self.record_dir_var.set(get('capture', 'record_dir', '') or '')
        self.apk_dir_var.set(get('capture', 'apk_dir', '') or '')
        self.record_limit_var.set(str(get('capture', 'record_time_limit', 30)))
        self.record_bitrate_var.set(get('capture', 'record_bit_rate', '') or '')
        self.record_size_var.set(get('capture', 'record_size', '') or '')

    def _save_capture_settings(self):
        from pathlib import Path
        from tkinter import messagebox
        for key, var in (('screenshot_dir', self.screenshot_dir_var),
                         ('record_dir', self.record_dir_var),
                         ('apk_dir', self.apk_dir_var)):
            value = var.get().strip()
            if value and not Path(value).is_dir():
                messagebox.showerror(
                    "Error", f"Default folder does not exist:\n{value}",
                    parent=self.dialog)
                return False
            self.config.set('capture', key, value)
        try:
            limit = max(1, min(180, int(self.record_limit_var.get().strip() or 30)))
        except (TypeError, ValueError):
            messagebox.showerror("Error", "Time limit must be 1-180 seconds.",
                                 parent=self.dialog)
            return False
        self.config.set('capture', 'record_time_limit', limit)
        self.config.set('capture', 'record_bit_rate', self.record_bitrate_var.get().strip())
        self.config.set('capture', 'record_size', self.record_size_var.get().strip())
        return True
