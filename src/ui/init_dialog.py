"""Initialization dialog for downloading dependencies."""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
from pathlib import Path

from core import DependencyManager


class InitDialog:
    """Dialog for initializing dependencies with progress bars."""
    
    def __init__(self, parent=None):
        """Initialize the dialog.
        
        Args:
            parent: Parent window (optional)
        """
        self.dialog = tk.Toplevel() if parent else tk.Tk()
        self.dialog.title("droidmgr - Initializing Dependencies")
        self.dialog.geometry("500x400")
        self.dialog.minsize(450, 400)
        
        self.dep_manager = DependencyManager()
        self.adb_path = None
        self.scrcpy_path = None
        self.success = False
        self.adb_needs_download = False
        self.scrcpy_needs_download = False
        
        self._create_widgets()
    
    def _create_widgets(self):
        main_container = ttk.Frame(self.dialog, padding=20)
        main_container.pack(fill=tk.BOTH, expand=True)
        
        title_label = tk.Label(
            main_container,
            text="Checking Dependencies",
            font=('Arial', 14, 'bold')
        )
        title_label.pack(pady=(0, 20))
        
        adb_frame = ttk.LabelFrame(main_container, text="Android Debug Bridge (ADB)", padding=15)
        adb_frame.pack(fill=tk.X, pady=10)
        
        self.adb_status_label = tk.Label(adb_frame, text="Checking...", anchor=tk.W)
        self.adb_status_label.pack(fill=tk.X, pady=(0, 8))
        
        self.adb_progress = ttk.Progressbar(adb_frame, mode='determinate', length=450)
        self.adb_progress.pack(fill=tk.X, pady=(0, 5))
        
        scrcpy_frame = ttk.LabelFrame(main_container, text="scrcpy", padding=15)
        scrcpy_frame.pack(fill=tk.X, pady=10)
        
        self.scrcpy_status_label = tk.Label(scrcpy_frame, text="Checking...", anchor=tk.W)
        self.scrcpy_status_label.pack(fill=tk.X, pady=(0, 8))
        
        self.scrcpy_progress = ttk.Progressbar(scrcpy_frame, mode='determinate', length=450)
        self.scrcpy_progress.pack(fill=tk.X, pady=(0, 5))
        
        self.button_frame = ttk.Frame(main_container)
        self.button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(25, 0))
        
        self.continue_button = ttk.Button(
            self.button_frame,
            text="OK",
            command=self._on_continue,
            state=tk.DISABLED,
            width=12
        )
        self.continue_button.pack(side=tk.RIGHT, padx=5)
        
        self.cancel_button = ttk.Button(
            self.button_frame,
            text="Cancel",
            command=self._on_cancel,
            width=12
        )
        self.cancel_button.pack(side=tk.RIGHT, padx=5)
    
    def _check_dependencies(self):
        """Check which dependencies are available."""
        # Check ADB synchronously
        try:
            self.adb_path = self.dep_manager.get_adb_path()
            self._update_adb_status("✓ Found", "green")
            self.adb_progress.configure(value=100)
        except RuntimeError:
            self.adb_needs_download = True
            self._update_adb_status("✗ Not found", "orange")
        
        # Check scrcpy synchronously
        try:
            self.scrcpy_path = self.dep_manager.get_scrcpy_path()
            self._update_scrcpy_status("✓ Found", "green")
            self.scrcpy_progress.configure(value=100)
        except RuntimeError:
            self.scrcpy_needs_download = True
            self._update_scrcpy_status("✗ Not found", "orange")
        
        # Ask user for permission to download
        self.dialog.after(100, self._ask_download_permission)
    
    def _update_adb_status(self, text, color="black"):
        self.adb_status_label.config(text=text, fg=color)
    
    def _update_scrcpy_status(self, text, color="black"):
        self.scrcpy_status_label.config(text=text, fg=color)
    
    def _ask_download_permission(self):
        missing = []
        if self.adb_needs_download:
            missing.append("ADB")
        if self.scrcpy_needs_download:
            missing.append("scrcpy")
        
        if not missing:
            self.success = True
            self.cancel_button.pack_forget()
            self.continue_button.config(state=tk.NORMAL)
            return
        
        message = (
            f"The following dependencies are missing:\n\n"
            f"{chr(10).join(f'  • {dep}' for dep in missing)}\n\n"
            f"Would you like to download and install them automatically?\n\n"
            f"They will be installed to: ~/.droidmgr/bin"
        )
        
        if messagebox.askyesno("Download Dependencies?", message, parent=self.dialog):
            self._download_dependencies()
        else:
            self._show_manual_instructions()
    
    def _download_dependencies(self):
        def download():
            try:
                if self.adb_needs_download:
                    def adb_progress(current, total, msg):
                        self.dialog.after(0, lambda m=msg, c=current: (
                            self._update_adb_status(m, "blue"),
                            self.adb_progress.configure(value=c)
                        ))
                    
                    self.adb_path = self.dep_manager.get_adb_path(
                        auto_download=True,
                        progress_callback=adb_progress
                    )
                    self.dialog.after(0, lambda: self._update_adb_status("✓ Installed", "green"))
                
                if self.scrcpy_needs_download:
                    def scrcpy_progress(current, total, msg):
                        self.dialog.after(0, lambda m=msg, c=current: (
                            self._update_scrcpy_status(m, "blue"),
                            self.scrcpy_progress.configure(value=c)
                        ))
                    
                    self.scrcpy_path = self.dep_manager.get_scrcpy_path(
                        auto_download=True,
                        progress_callback=scrcpy_progress
                    )
                    self.dialog.after(0, lambda: self._update_scrcpy_status("✓ Installed", "green"))
                
                self.dialog.after(0, self._on_download_success)
                
            except Exception as e:
                self.dialog.after(0, lambda err=str(e): self._on_download_error(err))
        
        self.cancel_button.config(state=tk.DISABLED)
        self.continue_button.config(state=tk.DISABLED)
        threading.Thread(target=download, daemon=True).start()
    
    def _on_download_success(self):
        self.success = True
        self.cancel_button.pack_forget()
        self.continue_button.config(state=tk.NORMAL)
        messagebox.showinfo(
            "Success",
            "All dependencies installed successfully!",
            parent=self.dialog
        )
    
    def _on_download_error(self, error_msg):
        self.cancel_button.config(state=tk.NORMAL)
        messagebox.showerror(
            "Download Error",
            f"Failed to download dependencies:\n\n{error_msg}\n\nPlease install manually.",
            parent=self.dialog
        )
        self._show_manual_instructions()
    
    def _show_manual_instructions(self):
        import platform
        system = platform.system().lower()
        
        install_commands = {
            'linux': {
                'ADB': 'sudo apt install android-tools-adb',
                'scrcpy': 'sudo apt install scrcpy'
            },
            'darwin': {
                'ADB': 'brew install android-platform-tools',
                'scrcpy': 'brew install scrcpy'
            },
            'windows': {
                'ADB': 'Download from: https://developer.android.com/tools/releases/platform-tools',
                'scrcpy': 'Download from: https://github.com/Genymobile/scrcpy/releases'
            }
        }
        
        instructions = "Manual Installation:\n\n"
        for dep in ['ADB', 'scrcpy']:
            if (dep == 'ADB' and self.adb_needs_download) or (dep == 'scrcpy' and self.scrcpy_needs_download):
                cmd = install_commands.get(system, install_commands['windows']).get(dep, '')
                instructions += f"{dep}:\n  {cmd}\n\n"
        
        messagebox.showinfo("Manual Installation", instructions, parent=self.dialog)
    
    def _on_cancel(self):
        """Handle cancel button."""
        self.success = False
        self.dialog.destroy()
    
    def _on_continue(self):
        """Handle continue button."""
        self.dialog.destroy()
    
    def run(self):
        """Run the dialog and return success status.
        
        Returns:
            Tuple of (success, adb_path, scrcpy_path)
        """
        # Start check after dialog is shown
        self.dialog.after(100, self._check_dependencies)
        self.dialog.wait_window()
        return self.success, self.adb_path, self.scrcpy_path
