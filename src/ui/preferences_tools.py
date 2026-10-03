"""Preferences general/external-tools tabs and tool download helpers."""
"""Split from preferences_dialog.py (MOVE-ONLY); PreferencesDialog mixes this in."""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import shutil
from pathlib import Path
from core import DependencyManager, ConfigManager
from .dpi import setup_window_dpi


class PreferencesToolsMixin:
    """General and external-tools preference tabs."""

    def _create_general_tab(self):
        tab = ttk.Frame(self.dialog)
        
        polling_frame = ttk.LabelFrame(tab, text="Polling & Refresh Settings", padding=10)
        polling_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(polling_frame, text="Query Interval:").grid(row=0, column=0, sticky=tk.W, pady=5, padx=(0, 10))
        
        self.query_interval_var = tk.StringVar(value="5 seconds")
        self.query_interval_cb = ttk.Combobox(
            polling_frame,
            textvariable=self.query_interval_var,
            values=["1 second", "2 seconds", "3 seconds", "5 seconds", "10 seconds", "15 seconds", "30 seconds"],
            state="readonly",
            width=15
        )
        self.query_interval_cb.grid(row=0, column=1, sticky=tk.W, pady=5)
        
        info_frame = ttk.LabelFrame(tab, text="Application Information", padding=10)
        info_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(info_frame, text="Version: 1.0.0").pack(anchor=tk.W, pady=2)
        
        dir_frame = ttk.Frame(info_frame)
        dir_frame.pack(fill=tk.X, anchor=tk.W, pady=(10, 2))
        ttk.Label(dir_frame, text="Install Directory:").pack(side=tk.LEFT)
        ttk.Button(dir_frame, text="Open", command=self._open_install_dir, width=8).pack(side=tk.LEFT, padx=10)
        
        ttk.Label(info_frame, text=str(self.dep_manager.install_dir), 
                 foreground="gray").pack(anchor=tk.W, pady=2, padx=20)
        
        return tab

    def _create_tools_tab(self):
        tab = ttk.Frame(self.dialog)
        
        adb_frame = ttk.LabelFrame(tab, text="Android Debug Bridge (ADB)", padding=10)
        adb_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(adb_frame, text="Path:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.adb_path_var = tk.StringVar()
        adb_entry = ttk.Entry(adb_frame, textvariable=self.adb_path_var, width=50)
        adb_entry.grid(row=0, column=1, columnspan=2, padx=5, pady=5, sticky=tk.EW)
        
        btn_frame_adb = ttk.Frame(adb_frame)
        btn_frame_adb.grid(row=1, column=1, columnspan=2, sticky=tk.W, pady=5)
        ttk.Button(btn_frame_adb, text="Download", command=self._download_adb).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame_adb, text="Auto-Detect", command=self._detect_adb).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame_adb, text="Browse...", command=self._browse_adb).pack(side=tk.LEFT)
        
        scrcpy_frame = ttk.LabelFrame(tab, text="scrcpy", padding=10)
        scrcpy_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(scrcpy_frame, text="Path:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.scrcpy_path_var = tk.StringVar()
        scrcpy_entry = ttk.Entry(scrcpy_frame, textvariable=self.scrcpy_path_var, width=50)
        scrcpy_entry.grid(row=0, column=1, columnspan=2, padx=5, pady=5, sticky=tk.EW)
        
        btn_frame_scrcpy = ttk.Frame(scrcpy_frame)
        btn_frame_scrcpy.grid(row=1, column=1, columnspan=2, sticky=tk.W, pady=5)
        ttk.Button(btn_frame_scrcpy, text="Download", command=self._download_scrcpy).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame_scrcpy, text="Auto-Detect", command=self._detect_scrcpy).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame_scrcpy, text="Browse...", command=self._browse_scrcpy).pack(side=tk.LEFT)

        
        return tab

    def _browse_adb(self):
        filename = filedialog.askopenfilename(
            title="Select ADB executable",
            filetypes=[("Executable", "adb*"), ("All Files", "*.*")]
        )
        if filename:
            self.adb_path_var.set(filename)

    def _browse_scrcpy(self):
        filename = filedialog.askopenfilename(
            title="Select scrcpy executable",
            filetypes=[("Executable", "scrcpy*"), ("All Files", "*.*")]
        )
        if filename:
            self.scrcpy_path_var.set(filename)

    def _detect_adb(self):
        try:
            adb_path = self.dep_manager.get_adb_path()
            self.adb_path_var.set(str(adb_path))
            messagebox.showinfo("Success", f"ADB found at:\n{adb_path}", parent=self.dialog)
        except RuntimeError:
            result = messagebox.askyesno(
                "ADB Not Found",
                "Could not auto-detect ADB.\n\nDo you want to download it automatically?",
                parent=self.dialog
            )
            if result:
                self._download_adb()

    def _detect_scrcpy(self):
        try:
            scrcpy_path = self.dep_manager.get_scrcpy_path()
            self.scrcpy_path_var.set(str(scrcpy_path))
            messagebox.showinfo("Success", f"scrcpy found at:\n{scrcpy_path}", parent=self.dialog)
        except RuntimeError:
            result = messagebox.askyesno(
                "scrcpy Not Found",
                "Could not auto-detect scrcpy.\n\nDo you want to download it automatically?",
                parent=self.dialog
            )
            if result:
                self._download_scrcpy()

    def _download_adb(self):
        from .init_dialog import InitDialog
        
        temp_dialog = tk.Toplevel(self.dialog)
        temp_dialog.title("Downloading ADB")
        temp_dialog.transient(self.dialog)
        setup_window_dpi(temp_dialog, base_width=500, base_height=200, parent=self.dialog)
        temp_dialog.wait_visibility()
        temp_dialog.grab_set()
        

        
        main_container = ttk.Frame(temp_dialog, padding=20)
        main_container.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_container, text="Downloading ADB...", font=('Arial', 12, 'bold')).pack(pady=(0, 10))
        
        status_label = ttk.Label(main_container, text="Preparing...")
        status_label.pack(pady=5)
        
        progress = ttk.Progressbar(main_container, mode='determinate')
        progress.pack(fill=tk.X, pady=5)
        
        def progress_callback(current, total, msg):
            temp_dialog.after(0, lambda: status_label.config(text=msg))
            temp_dialog.after(0, lambda: progress.configure(value=current))
        
        def download_task():
            try:
                adb_path = self.dep_manager.get_adb_path(auto_download=True, progress_callback=progress_callback)
                temp_dialog.after(0, lambda: self.adb_path_var.set(str(adb_path)))
                temp_dialog.after(0, lambda: messagebox.showinfo("Success", "ADB downloaded successfully!", parent=self.dialog))
                temp_dialog.after(0, temp_dialog.destroy)
            except Exception as e:
                temp_dialog.after(0, lambda: messagebox.showerror("Error", f"Failed to download ADB:\n{e}", parent=self.dialog))
                temp_dialog.after(0, temp_dialog.destroy)
        
        import threading
        threading.Thread(target=download_task, daemon=True).start()

    def _download_scrcpy(self):
        temp_dialog = tk.Toplevel(self.dialog)
        temp_dialog.title("Downloading scrcpy")
        temp_dialog.transient(self.dialog)
        setup_window_dpi(temp_dialog, base_width=500, base_height=200, parent=self.dialog)
        temp_dialog.wait_visibility()
        temp_dialog.grab_set()
        

        
        main_container = ttk.Frame(temp_dialog, padding=20)
        main_container.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_container, text="Downloading scrcpy...", font=('Arial', 12, 'bold')).pack(pady=(0, 10))
        
        status_label = ttk.Label(main_container, text="Preparing...")
        status_label.pack(pady=5)
        
        progress = ttk.Progressbar(main_container, mode='determinate')
        progress.pack(fill=tk.X, pady=5)
        
        def progress_callback(current, total, msg):
            temp_dialog.after(0, lambda: status_label.config(text=msg))
            temp_dialog.after(0, lambda: progress.configure(value=current))
        
        def download_task():
            try:
                scrcpy_path = self.dep_manager.get_scrcpy_path(auto_download=True, progress_callback=progress_callback)
                temp_dialog.after(0, lambda: self.scrcpy_path_var.set(str(scrcpy_path)))
                temp_dialog.after(0, lambda: messagebox.showinfo("Success", "scrcpy downloaded successfully!", parent=self.dialog))
                temp_dialog.after(0, temp_dialog.destroy)
            except Exception as e:
                temp_dialog.after(0, lambda: messagebox.showerror("Error", f"Failed to download scrcpy:\n{e}", parent=self.dialog))
                temp_dialog.after(0, temp_dialog.destroy)
        
        import threading
        threading.Thread(target=download_task, daemon=True).start()

    def _download_adb(self):
        import platform, webbrowser
        if platform.system() == 'Linux':
            from .preferences_dialog import LinuxInstallDialog
            LinuxInstallDialog(self.dialog, tool_name="ADB")
        else:
            webbrowser.open("https://developer.android.com/tools/releases/platform-tools")

    def _download_scrcpy(self):
        import platform, webbrowser
        if platform.system() == 'Linux':
            from .preferences_dialog import LinuxInstallDialog
            LinuxInstallDialog(self.dialog, tool_name="scrcpy")
        else:
            webbrowser.open("https://github.com/Genymobile/scrcpy/releases")

    def _open_install_dir(self):
        import os, subprocess, platform
        path = str(self.dep_manager.install_dir)
        try:
            if platform.system() == 'Windows':
                os.startfile(path)
            elif platform.system() == 'Darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open directory:\n{e}", parent=self.dialog)
