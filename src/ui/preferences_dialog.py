"""Preferences dialog for droidmgr."""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import shutil
from pathlib import Path
from core import DependencyManager, ConfigManager
from .dpi import setup_window_dpi

from .preferences_backup import PreferencesBackupMixin
from .preferences_tools import PreferencesToolsMixin
from .preferences_capture import PreferencesCaptureMixin
from .preferences_interface import PreferencesInterfaceMixin


class PreferencesDialog(PreferencesBackupMixin, PreferencesToolsMixin,
                        PreferencesCaptureMixin, PreferencesInterfaceMixin):
    def __init__(self, parent, on_preferences_changed=None):
        self.parent = parent
        self.on_preferences_changed = on_preferences_changed
        self.dep_manager = DependencyManager()
        self.config = ConfigManager()
        
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Preferences")
        self.dialog.transient(parent)
        
        self._create_widgets()
        self._load_settings()
        
        setup_window_dpi(self.dialog, base_width=600, base_height=480, min_width=550, min_height=450, parent=parent)
            
        self.dialog.wait_visibility()
        self.dialog.grab_set()
        self.dialog.bind('<Escape>', lambda e: self.dialog.destroy())

    def _create_widgets(self):
        notebook = ttk.Notebook(self.dialog)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        general_tab = self._create_general_tab()
        file_manager_tab = self._create_file_manager_tab()
        backup_tab = self._create_backup_tab()
        tools_tab = self._create_tools_tab()
        capture_tab = self._create_capture_tab()

        notebook.add(general_tab, text="General")
        notebook.add(file_manager_tab, text="File Manager")
        notebook.add(backup_tab, text="Backup")
        notebook.add(tools_tab, text="External Tools")
        notebook.add(capture_tab, text="Capture")
        notebook.add(self._create_interface_tab(), text="Interface")
        
        button_frame = ttk.Frame(self.dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        ttk.Button(button_frame, text="OK", command=self._on_ok, width=15).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=self.dialog.destroy, width=15).pack(side=tk.RIGHT)

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
        self.backup_exclusions.delete(0, tk.END)
        self.backup_scope_var.set("Internal storage + system storage" if self.config.get('backup', 'scope', 0) == 1 else "Internal storage")
        self.backup_parallelism_var.set(str(self.config.get('backup', 'parallelism', 4)))
        self.backup_verify_var.set(bool(self.config.get('backup', 'verify_checksums', False)))
        exclusions = self.config.get('backup', 'exclude_paths', ['/storage/emulated/0/Android'])
        if isinstance(exclusions, list):
            for path in exclusions:
                if isinstance(path, str):
                    self.backup_exclusions.insert(tk.END, path)
        
        # Load General settings
        interval = self.config.get('general', 'query_interval', 5)
        self.query_interval_var.set(f"{interval} second{'s' if int(interval) > 1 else ''}")

        # Load Capture settings
        self._load_capture_settings()

        # Load Interface settings
        self._load_interface_settings()

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

        self.config.set('paths', 'adb', adb_path)
        self.config.set('paths', 'scrcpy', scrcpy_path)
        self.config.set('file_manager', 'show_hidden', self.show_hidden_var.get())
        self.config.set('file_manager', 'use_exact_sizes', self.exact_sizes_var.get())
        self.config.set('file_manager', 'confirm_rename', self.confirm_rename_var.get())
        self.config.set('backup', 'exclude_paths', list(self.backup_exclusions.get(0, tk.END)))
        self.config.set('backup', 'scope', 1 if self.backup_scope_var.get().startswith('Internal storage +') else 0)
        try:
            parallelism = int(self.backup_parallelism_var.get())
            self.config.set('backup', 'parallelism', parallelism if parallelism in (1, 2, 4, 8) else 4)
        except ValueError:
            self.config.set('backup', 'parallelism', 4)
        self.config.set('backup', 'verify_checksums', self.backup_verify_var.get())
        if not self._save_capture_settings():
            return
        if not self._save_interface_settings():
            return
        self.config.save()

        if self.on_preferences_changed:
            self.on_preferences_changed()
        
        self.dialog.destroy()

    def show(self):
        self.dialog.wait_window()


        # Load paths
        # Load File Manager settings
        # Load General settings
        # Save to config
class LinuxInstallDialog(tk.Toplevel):
    def __init__(self, parent, tool_name="ADB"):
        super().__init__(parent)
        self.title(f"Install {tool_name} on Linux")
        self.transient(parent)

        self.tool_name = tool_name
        self._create_widgets()
        setup_window_dpi(self, base_width=600, base_height=480, min_width=550, min_height=400, parent=parent)
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


__all__ = ['PreferencesDialog', 'LinuxInstallDialog']
