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
        
        # Center dialog relative to parent window
        self.dialog.update_idletasks()
        try:
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            dw = 600
            dh = 480
            cx = px + (pw // 2) - (dw // 2)
            cy = py + (ph // 2) - (dh // 2)
            self.dialog.geometry(f"+{max(0, cx)}+{max(0, cy)}")
        except Exception:
            pass
            
        self.dialog.wait_visibility()
        self.dialog.grab_set()
        self.dialog.bind('<Escape>', lambda e: self.dialog.destroy())


    

    
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
        
        # Load General settings
        interval = self.config.get('general', 'query_interval', 5)
        self.query_interval_var.set(f"{interval} second{'s' if int(interval) > 1 else ''}")
        
        apps_mode = self.config.get('general', 'apps_view_mode', 'compact')
        if apps_mode == 'detailed':
            self.apps_view_mode_var.set("Detailed (Icon, Name, Package, Size)")
        else:
            self.apps_view_mode_var.set("Compact (Package List)")



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
        
        apps_view_frame = ttk.LabelFrame(tab, text="Applications View Settings", padding=10)
        apps_view_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(apps_view_frame, text="View Mode:").grid(row=0, column=0, sticky=tk.W, pady=5, padx=(0, 10))
        self.apps_view_mode_var = tk.StringVar(value="Compact (Package List)")
        self.apps_view_mode_cb = ttk.Combobox(
            apps_view_frame,
            textvariable=self.apps_view_mode_var,
            values=["Compact (Package List)", "Detailed (Icon, Name, Package, Size)"],
            state="readonly",
            width=32
        )
        self.apps_view_mode_cb.grid(row=0, column=1, sticky=tk.W, pady=5)

        info_frame = ttk.LabelFrame(tab, text="Application Information", padding=10)
        info_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(info_frame, text="Version: 0.1.0").pack(anchor=tk.W, pady=2)
        
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
        try:
            val_str = self.query_interval_var.get()
            interval_sec = int(val_str.split()[0])
            self.config.set('general', 'query_interval', interval_sec)
        except Exception:
            pass

        apps_mode_str = self.apps_view_mode_var.get()
        apps_mode_val = 'detailed' if 'Detailed' in apps_mode_str else 'compact'
        self.config.set('general', 'apps_view_mode', apps_mode_val)

        self.config.set('paths', 'adb', adb_path)
        self.config.set('paths', 'scrcpy', scrcpy_path)
        self.config.set('file_manager', 'show_hidden', self.show_hidden_var.get())
        self.config.set('file_manager', 'use_exact_sizes', self.exact_sizes_var.get())
        self.config.set('file_manager', 'confirm_rename', self.confirm_rename_var.get())
        self.config.save()

        if self.on_preferences_changed:
            self.on_preferences_changed()
        
        self.dialog.destroy()

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

    
    def _download_adb(self):
        import platform, webbrowser
        if platform.system() == 'Linux':
            LinuxInstallDialog(self.dialog, tool_name="ADB")
        else:
            webbrowser.open("https://developer.android.com/tools/releases/platform-tools")

    def _download_scrcpy(self):
        import platform, webbrowser
        if platform.system() == 'Linux':
            LinuxInstallDialog(self.dialog, tool_name="scrcpy")
        else:
            webbrowser.open("https://github.com/Genymobile/scrcpy/releases")

    def show(self):
        self.dialog.wait_window()


class LinuxInstallDialog(tk.Toplevel):
    def __init__(self, parent, tool_name="ADB"):
        super().__init__(parent)
        self.title(f"Install {tool_name} on Linux")
        self.geometry("600x480")
        self.minsize(550, 400)
        self.transient(parent)

        self.tool_name = tool_name
        self._create_widgets()

        # Center dialog relative to parent window
        self.update_idletasks()
        try:
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            dw = 600
            dh = 480
            cx = px + (pw // 2) - (dw // 2)
            cy = py + (ph // 2) - (dh // 2)
            self.geometry(f"+{max(0, cx)}+{max(0, cy)}")
        except Exception:
            pass

        self.wait_visibility()
        self.grab_set()
        self.bind('<Escape>', lambda e: self.destroy())


    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        header = tk.Label(
            main_frame,
            text=f"Install {self.tool_name} on Linux",
            font=('Arial', 14, 'bold'),
            fg='#2196F3'
        )
        header.pack(anchor=tk.W, pady=(0, 5))

        desc = ttk.Label(
            main_frame,
            text=f"Select your Linux distribution below and copy the terminal command to install {self.tool_name} via your system package manager:",
            font=('Arial', 9),
            wraplength=540
        )
        desc.pack(anchor=tk.W, pady=(0, 10))

        if self.tool_name.upper() == "ADB":
            commands = [
                ("Ubuntu / Debian / Mint / Pop!_OS", "sudo apt update && sudo apt install -y android-tools-adb"),
                ("Fedora / RHEL / CentOS", "sudo dnf install -y android-tools"),
                ("Arch Linux / Manjaro / EndeavourOS", "sudo pacman -S --noconfirm android-tools"),
                ("openSUSE (Leap / Tumbleweed)", "sudo zypper install -y android-tools"),
                ("Alpine Linux", "sudo apk add android-tools"),
                ("Gentoo Linux", "sudo emerge --ask dev-util/android-tools"),
            ]
            web_url = "https://developer.android.com/tools/releases/platform-tools"
        else:
            commands = [
                ("Ubuntu / Debian / Mint / Pop!_OS", "sudo apt update && sudo apt install -y scrcpy"),
                ("Fedora / RHEL", "sudo dnf install -y scrcpy"),
                ("Arch Linux / Manjaro / EndeavourOS", "sudo pacman -S --noconfirm scrcpy"),
                ("openSUSE (Leap / Tumbleweed)", "sudo zypper install -y scrcpy"),
                ("Alpine Linux", "sudo apk add scrcpy"),
                ("Gentoo Linux", "sudo emerge --ask app-mobilephone/scrcpy"),
                ("Snap (Universal Linux)", "sudo snap install scrcpy"),
            ]
            web_url = "https://github.com/Genymobile/scrcpy"

        container = ttk.Frame(main_frame)
        container.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        for distro, cmd in commands:
            item_frame = ttk.LabelFrame(scroll_frame, text=distro, padding=8)
            item_frame.pack(fill=tk.X, expand=True, pady=4, padx=2)

            cmd_entry = ttk.Entry(item_frame, font=('Consolas', 9))
            cmd_entry.insert(0, cmd)
            cmd_entry.configure(state='readonly')
            cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

            copy_btn = ttk.Button(item_frame, text="Copy", width=10)
            copy_btn.configure(command=lambda c=cmd, b=copy_btn: self._copy_command(c, b))
            copy_btn.pack(side=tk.RIGHT)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

        ttk.Button(btn_frame, text="Close", command=self.destroy, width=12).pack(side=tk.RIGHT)

        import webbrowser
        ttk.Button(
            btn_frame,
            text="Open Web Page",
            command=lambda: webbrowser.open(web_url)
        ).pack(side=tk.RIGHT, padx=5)

    def _copy_command(self, cmd_text, button):
        self.clipboard_clear()
        self.clipboard_append(cmd_text)
        button.config(text="Copied!")
        self.after(2000, lambda: button.config(text="Copy") if button.winfo_exists() else None)

