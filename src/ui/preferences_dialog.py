"""Preferences dialog for droidmgr."""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import shutil
from pathlib import Path

from core import DependencyManager, ConfigManager


class PreferencesDialog:
    
    def __init__(self, parent, on_preferences_changed=None):
        self.parent = parent
        self.on_preferences_changed = on_preferences_changed
        self.dep_manager = DependencyManager()
        self.config = ConfigManager()
        
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Preferences")
        self.dialog.geometry("600x480")
        self.dialog.minsize(550, 450)
        self.dialog.transient(parent)
        
        
        self._create_widgets()
        self._load_settings()
        
        self.dialog.wait_visibility()
        self.dialog.grab_set()
    

    
    def _create_widgets(self):
        notebook = ttk.Notebook(self.dialog)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        general_tab = self._create_general_tab()
        file_manager_tab = self._create_file_manager_tab()
        tools_tab = self._create_tools_tab()
        
        notebook.add(general_tab, text="General")
        notebook.add(file_manager_tab, text="File Manager")
        notebook.add(tools_tab, text="External Tools")
        
        button_frame = ttk.Frame(self.dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        ttk.Button(button_frame, text="OK", command=self._on_ok, width=15).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=self.dialog.destroy, width=15).pack(side=tk.RIGHT)

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
    
    def _load_settings(self):
        # Load paths
        try:
            adb_path = self.dep_manager.get_adb_path()
            self.adb_path_var.set(str(adb_path))
        except:
            self.adb_path_var.set(self.config.get('paths', 'adb', ''))
        
        try:
            scrcpy_path = self.dep_manager.get_scrcpy_path()
            self.scrcpy_path_var.set(str(scrcpy_path))
        except:
            self.scrcpy_path_var.set(self.config.get('paths', 'scrcpy', ''))
            
        # Load File Manager settings
        self.show_hidden_var.set(self.config.get('file_manager', 'show_hidden', False))
        self.exact_sizes_var.set(self.config.get('file_manager', 'use_exact_sizes', False))
        self.confirm_rename_var.set(self.config.get('file_manager', 'confirm_rename', True))

    def _create_general_tab(self):
        tab = ttk.Frame(self.dialog)
        
        info_frame = ttk.LabelFrame(tab, text="Application Information", padding=10)
        info_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(info_frame, text="Version: 0.1.0").pack(anchor=tk.W, pady=2)
        ttk.Label(info_frame, text="Install Directory:").pack(anchor=tk.W, pady=(10, 2))
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
        temp_dialog.geometry("500x200")
        temp_dialog.transient(self.dialog)
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
        temp_dialog.geometry("500x200")
        temp_dialog.transient(self.dialog)
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
    
    def _on_ok(self):
        adb_path = self.adb_path_var.get()
        scrcpy_path = self.scrcpy_path_var.get()
        
        if adb_path and not Path(adb_path).exists():
            messagebox.showerror("Error", f"ADB path does not exist:\n{adb_path}", parent=self.dialog)
            return
        
        if scrcpy_path and not Path(scrcpy_path).exists():
            messagebox.showerror("Error", f"scrcpy path does not exist:\n{scrcpy_path}", parent=self.dialog)
            return
            
        # Save to config
        self.config.set('paths', 'adb', adb_path)
        self.config.set('paths', 'scrcpy', scrcpy_path)
        self.config.set('file_manager', 'show_hidden', self.show_hidden_var.get())
        self.config.set('file_manager', 'use_exact_sizes', self.exact_sizes_var.get())
        self.config.set('file_manager', 'confirm_rename', self.confirm_rename_var.get())
        self.config.save()
        
        if self.on_preferences_changed:
            self.on_preferences_changed()
        
        self.dialog.destroy()
    
    def show(self):
        self.dialog.wait_window()
