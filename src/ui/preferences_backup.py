"""Preferences file-manager and backup tabs."""
"""Split from preferences_dialog.py (MOVE-ONLY); PreferencesDialog mixes this in."""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import shutil
from pathlib import Path
from core import DependencyManager, ConfigManager
from .dpi import setup_window_dpi


class PreferencesBackupMixin:
    """File-manager and backup preference tabs."""

    def _create_file_manager_tab(self):
        tab = ttk.Frame(self.dialog)
        
        fm_frame = ttk.LabelFrame(tab, text="File Manager Settings", padding=10)
        fm_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.show_hidden_var = tk.BooleanVar()
        ttk.Checkbutton(fm_frame, text="Show hidden files and folders", variable=self.show_hidden_var).pack(anchor=tk.W, pady=5)
        
        self.exact_sizes_var = tk.BooleanVar()
        ttk.Checkbutton(fm_frame, text="Show exact byte counts for file sizes", variable=self.exact_sizes_var).pack(anchor=tk.W, pady=5)
        
        self.confirm_rename_var = tk.BooleanVar()
        ttk.Checkbutton(fm_frame, text="Confirm before renaming files", variable=self.confirm_rename_var).pack(anchor=tk.W, pady=5)
        
        return tab

    def _create_backup_tab(self):
        tab = ttk.Frame(self.dialog)
        options = ttk.LabelFrame(tab, text="Default backup options", padding=10)
        options.pack(fill=tk.X, padx=10, pady=(10, 0))
        ttk.Label(options, text="Storage:").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=3)
        self.backup_scope_var = tk.StringVar()
        ttk.Combobox(options, textvariable=self.backup_scope_var, state="readonly",
                     values=("Internal storage", "Internal storage + system storage"), width=32).grid(
                         row=0, column=1, sticky=tk.W, pady=3)
        ttk.Label(options, text="Files downloading at once:").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=3)
        self.backup_parallelism_var = tk.StringVar()
        ttk.Combobox(options, textvariable=self.backup_parallelism_var, state="readonly",
                     values=("1", "2", "4", "8"), width=8).grid(row=1, column=1, sticky=tk.W, pady=3)
        self.backup_verify_var = tk.BooleanVar()
        ttk.Checkbutton(options, text="Create SHA-256 checksums after download",
                        variable=self.backup_verify_var).grid(row=2, column=0, columnspan=2,
                                                               sticky=tk.W, pady=(5, 0))

        frame = ttk.LabelFrame(tab, text="Excluded device paths", padding=10)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        ttk.Label(
            frame,
            text="Each path and everything inside it will be skipped during backup.",
            wraplength=500,
        ).pack(anchor=tk.W, pady=(0, 8))

        list_frame = ttk.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.backup_exclusions = tk.Listbox(list_frame, height=10, activestyle="none")
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.backup_exclusions.yview)
        self.backup_exclusions.configure(yscrollcommand=scrollbar.set)
        self.backup_exclusions.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(8, 0))
        self.add_exclusion_button = ttk.Button(buttons, text="Add Path...", command=self._add_backup_exclusion)
        self.add_exclusion_button.pack(side=tk.LEFT)
        ttk.Button(buttons, text="Remove Selected", command=self._remove_backup_exclusion).pack(side=tk.LEFT, padx=(6, 0))
        return tab

    def _add_backup_exclusion(self):
        base_path = '/storage/emulated/0'
        entry_dialog = tk.Toplevel(self.dialog)
        entry_dialog.title("Add Backup Exclusion")
        entry_dialog.transient(self.dialog)
        entry_dialog.resizable(True, False)

        body = ttk.Frame(entry_dialog, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="Exclude this folder and everything inside it:").pack(anchor=tk.W, pady=(0, 8))
        path_row = ttk.Frame(body)
        path_row.pack(fill=tk.X)
        ttk.Label(path_row, text=f'{base_path}/').pack(side=tk.LEFT)
        path_var = tk.StringVar()
        path_entry = ttk.Entry(path_row, textvariable=path_var, width=70)
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        path_entry.focus_set()
        ttk.Label(body, text="For example: Android/data or Movies/Large Files").pack(anchor=tk.W, pady=(5, 10))

        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="Cancel", command=entry_dialog.destroy).pack(side=tk.RIGHT)

        def add_path():
            relative = path_var.get().strip().replace('\\', '/')
            if relative == base_path or relative.startswith(base_path + '/'):
                relative = relative[len(base_path):]
            relative = relative.strip('/')
            parts = [part for part in relative.split('/') if part]
            if not parts or any(part in ('.', '..') or '\x00' in part for part in parts):
                messagebox.showerror("Invalid Path", "Enter a folder path below /storage/emulated/0.", parent=entry_dialog)
                return
            path = base_path + '/' + '/'.join(parts)
            existing = self.backup_exclusions.get(0, tk.END)
            if path not in existing:
                self.backup_exclusions.insert(tk.END, path)
            entry_dialog.destroy()

        ttk.Button(buttons, text="Add", command=add_path).pack(side=tk.RIGHT, padx=(0, 6))
        entry_dialog.bind('<Return>', lambda _event: add_path())
        entry_dialog.bind('<Escape>', lambda _event: entry_dialog.destroy())

        entry_dialog.update_idletasks()
        width = max(640, entry_dialog.winfo_reqwidth())
        height = max(145, entry_dialog.winfo_reqheight())
        button = self.add_exclusion_button
        x = button.winfo_rootx()
        y = button.winfo_rooty() + button.winfo_height() + 4
        screen_width = entry_dialog.winfo_screenwidth()
        screen_height = entry_dialog.winfo_screenheight()
        x = min(max(0, x), max(0, screen_width - width))
        if y + height > screen_height:
            y = max(0, button.winfo_rooty() - height - 4)
        entry_dialog.geometry(f"{width}x{height}+{x}+{y}")
        entry_dialog.grab_set()
        path_entry.focus_set()

    def _remove_backup_exclusion(self):
        for index in reversed(self.backup_exclusions.curselection()):
            self.backup_exclusions.delete(index)
