"""MainWindow mixin: per-app actions (start/stop/clear/uninstall/APK)."""

import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
from typing import Dict, List, Optional
from .apk_extract import extract_apk
from .app_info_dialog import AppInfoDialog
from .apk_install_progress import APKInstallProgressDialog
from .main_utils import (_is_clear_denied, _CLEAR_DENIED_MESSAGE,
    _looks_like_system_package)


class _AppActionsMixin:
    """_AppActionsMixin for MainWindow (see main_window.py)."""

    def _show_app_info(self, event=None):
        package = self._get_selected_package()
        if not package:
            return
            
        def task():
            try:
                info = self.device_manager.adb.get_app_info(self.selected_device, package)
                self.root.after(0, lambda: AppInfoDialog(self.root, info, self.selected_device, self.device_manager))

            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_error("App Info Error", msg))
                
        threading.Thread(target=task, daemon=True).start()

    def _start_app(self):
        if not self._require_device():
            return
        
        package = self._get_selected_package()
        if not package:
            self._show_warning("Please select an app to start")
            return
        
        def task():
            try:
                self.device_manager.start_app(self.selected_device, package)
                self.root.after(0, lambda: self._show_info(f"Started {package}"))
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_error("Start App Error", msg))
        
        self._set_status(f"Starting {package}...")
        threading.Thread(target=task, daemon=True).start()

    def _stop_app(self):
        if not self._require_device():
            return
        
        package = self._get_selected_package()
        if not package:
            self._show_warning("Please select an app to stop")
            return
        
        try:
            self.device_manager.stop_app(self.selected_device, package)
            self._show_info(f"Stopped {package}")
        except Exception as e:
            self._show_error("Stop App Error", str(e))

    def _clear_app_cache(self):
        if not self._require_device():
            return

        packages = self._get_selected_packages()
        if not packages:
            self._show_warning("Please select one or more applications to clear")
            return

        if not self._confirm_clear_cache(packages):
            return

        device_id = self.selected_device
        self._set_status(f"Clearing data for {len(packages)} "
                         f"application{'s' if len(packages) > 1 else ''}...")

        def task():
            cleared = []
            failed = {}
            for package in packages:
                try:
                    self.device_manager.clear_app_data(device_id, package)
                    cleared.append(package)
                except Exception as e:
                    failed[package] = str(e)
            self.root.after(0, self._refresh_apps)
            self.root.after(0, lambda: self._report_clear_cache(cleared, failed))

        threading.Thread(target=task, daemon=True).start()

    def _confirm_clear_cache(self, packages: List[str]) -> bool:
        """Confirm a clear, spelling out that an app's data goes with its cache."""
        listed = '\n'.join(f"  - {pkg}" for pkg in packages[:10])
        if len(packages) > 10:
            listed += f"\n  ... and {len(packages) - 10} more"
        count = len(packages)
        return messagebox.askyesno(
            "Confirm Clear Cache",
            "Android cannot clear one app's cache on its own: its cache sits inside "
            "the app's own data directory, which only this operation can reach.\n\n"
            f"So the {count} selected application{'s' if count != 1 else ''} will also "
            "lose their stored data. Each will be signed out, its settings reset and "
            "anything it downloaded removed. What is not held by an account is lost.\n\n"
            f"{listed}\n\nClear data now?",
            icon=messagebox.WARNING)

    def _report_clear_cache(self, cleared: List[str], failed: Dict[str, str]):
        """Say what was cleared, and give the reason for anything that was not."""
        total = len(cleared) + len(failed)
        if not failed:
            self._show_info(f"Cleared data for {total} "
                            f"application{'s' if total != 1 else ''}")
            return
        if not cleared and all(_is_clear_denied(msg) for msg in failed.values()):
            self._show_error("Clear Cache Denied", _CLEAR_DENIED_MESSAGE)
            return
        detail = '\n'.join(f'  - {pkg}: {msg}'
                           for pkg, msg in list(failed.items())[:10])
        if len(failed) > 10:
            detail += f"\n  ... and {len(failed) - 10} more"
        self._show_error("Clear Cache Error",
                         f"{len(failed)} of {total} could not be cleared:\n{detail}")

    def _uninstall_app(self):
        if not self._require_device():
            return

        packages = self._get_selected_packages()
        if not packages:
            self._show_warning("Please select an application to uninstall")
            return

        device_id = self.selected_device

        if len(packages) > 1:
            self._confirm_bulk_uninstall(packages)
        else:
            if not self._confirm_single_uninstall(device_id, packages[0]):
                return

        self._set_status(f"Uninstalling {len(packages)} "
                         f"application{'s' if len(packages) > 1 else ''}...")

        def task():
            failed = []
            for package in packages:
                try:
                    self.device_manager.uninstall_app(device_id, package)
                except Exception:
                    failed.append(package)
            self.root.after(0, self._refresh_apps)
            if failed:
                detail = '\n'.join(failed)
                self.root.after(0, lambda: self._show_error(
                    "Uninstall Error",
                    f"{len(failed)} of {len(packages)} could not be uninstalled:\n{detail}"))
            elif len(packages) == 1:
                self.root.after(0, lambda: messagebox.showinfo(
                    "Success", f"Successfully uninstalled {packages[0]}"))
            else:
                self.root.after(0, lambda: messagebox.showinfo(
                    "Success", f"Successfully uninstalled {len(packages)} applications"))

        threading.Thread(target=task, daemon=True).start()

    def _confirm_bulk_uninstall(self, packages: List[str]) -> bool:
        """One confirmation for a multi-app uninstall, with a system-app warning."""
        # A listed app is judged by the install path the device reports, which
        # catches vendor system apps the name heuristic would miss. The name
        # check stays on as a floor for core packages.
        types = self._get_visible_app_types()
        risky = [pkg for pkg in packages
                 if types.get(pkg) == 'System' or _looks_like_system_package(pkg)]
        if risky:
            listed = '\n'.join(risky[:10])
            if len(risky) > 10:
                listed += f"\n  ... and {len(risky) - 10} more"
            if not messagebox.askyesno(
                    "Warning - System Applications",
                    f"{len(risky)} of the {len(packages)} selected applications look like "
                    f"system or core apps:\n\n{listed}\n\n"
                    "Uninstalling them can break core functionality, cause boot loops, "
                    "or disable system services.\n\nDo you want to proceed?",
                    icon=messagebox.WARNING):
                return False
            if not messagebox.askyesno(
                    "Critical Confirmation",
                    "You selected system or core applications. Your device may become "
                    "unusable.\n\nAre you ABSOLUTELY sure you want to proceed?",
                    icon=messagebox.WARNING):
                return False

        listed = '\n'.join(f"  - {pkg}" for pkg in packages[:10])
        if len(packages) > 10:
            listed += f"\n  ... and {len(packages) - 10} more"
        return messagebox.askyesno(
            "Confirm Uninstall",
            f"Are you sure you want to uninstall {len(packages)} applications?\n\n{listed}")

    def _confirm_single_uninstall(self, device_id: str, package: str) -> bool:
        """The original per-app checks, including the exact install path."""
        app_path = ""
        try:
            info = self.device_manager.adb.get_app_info(device_id, package)
            app_path = info.get('path', '')
        except Exception:
            pass

        is_system_app = _looks_like_system_package(package, app_path)
        app_type = "System Application" if is_system_app else "User Application"
        path_display = app_path if app_path else "Unknown"

        if is_system_app:
            msg1 = (
                f"Warning: '{package}' is a System Application.\n\n"
                f"Package: {package}\n"
                f"Type: {app_type}\n"
                f"Install Path: {path_display}\n\n"
                "Uninstalling system applications can break core functionality, cause boot loops, or disable system services.\n\n"
                "Do you want to proceed?"
            )
            if not messagebox.askyesno("Warning - System Application", msg1, icon=messagebox.WARNING):
                return False

            msg2 = (
                f"This is a system application ({package}).\n\n"
                "Uninstalling it may cause system instability or render your device unusable.\n\n"
                "Are you ABSOLUTELY sure you want to proceed and uninstall this application?"
            )
            if not messagebox.askyesno("Critical Confirmation", msg2, icon=messagebox.WARNING):
                return False
        else:
            msg = (
                f"Are you sure you want to uninstall this application?\n\n"
                f"Package: {package}\n"
                f"Type: {app_type}\n"
                f"Install Path: {path_display}"
            )
            if not messagebox.askyesno("Confirm Uninstall", msg):
                return False
        return True

    def _install_apk(self):
        """Ask for an APK file and install it."""
        if not self._require_device():
            return

        apk_path = filedialog.askopenfilename(
            title="Select APK file",
            filetypes=[("APK files", "*.apk"), ("All files", "*.*")]
        )

        if apk_path:
            self._install_apk_paths([apk_path])

    def _install_apk_paths(self, paths):
        """Install one or more APK files in turn, from the picker or a drop."""
        if not self._require_device():
            return

        apks = [Path(p) for p in paths if Path(p).suffix.lower() == '.apk']
        if not apks:
            self._show_error("No APKs", "None of the selected files are .apk files.")
            return

        sizes = []
        for path in apks:
            if not path.exists() or not path.is_file():
                self._show_error("Invalid File", f"This file does not exist or is invalid:\n{path}")
                return
            sizes.append(path.stat().st_size / (1024 * 1024))

        biggest_index = sizes.index(max(sizes))
        if sizes[biggest_index] > 500:
            msg = (
                f"{apks[biggest_index].name} is very large ({sizes[biggest_index]:.1f} MB).\n\n"
                "Installing large applications over ADB may take several minutes.\n\n"
                "Do you want to proceed with the installation?"
            )
            if not messagebox.askyesno("Large File Warning", msg, icon=messagebox.WARNING):
                return

        total_mb = sum(sizes)
        label = apks[0].name if len(apks) == 1 else f"{len(apks)} APKs"
        progress_dialog = None
        if total_mb > 50:
            progress_dialog = APKInstallProgressDialog(self.root, label, total_mb)
        device_id = self.selected_device

        def task():
            installed, failures = [], []
            for path, size_mb in zip(apks, sizes):
                try:
                    self.device_manager.adb.install_apk(device_id, str(path))
                    installed.append(path.name)
                except Exception as e:
                    failures.append(f"{path.name}: {e}")
            if progress_dialog:
                self.root.after(0, progress_dialog.close)
            self.root.after(0, lambda: self._on_apks_installed(installed, failures))

        self._set_status(f"Installing {label}...")
        threading.Thread(target=task, daemon=True).start()

    def _on_apks_installed(self, installed, failures):
        """Report the outcome of a batch install."""
        if failures:
            details = '\n'.join(failures)
            if installed:
                succeeded = '\n'.join(f'  {name}' for name in installed)
                details = f"Installed:\n{succeeded}\n\nFailed:\n{details}"
            self._show_error("Install APK Error", details)
        elif len(installed) > 1:
            names = '\n'.join(installed)
            self._show_info(f"Installed {len(installed)} APKs:\n{names}")
        else:
            self._show_info("APK installed successfully")
        self._refresh_apps()

    def _extract_apk(self):
        """Applications > Extract APK: pull the selected package off the device."""
        if not self._require_device():
            return
        package = self._get_selected_package()
        if not package:
            self._show_warning("Please select an application first")
            return
        extract_apk(self.root, self.device_manager, self.selected_device, package,
                    self._set_status, self._show_error, self._show_info)



    def _show_app_context_menu(self, event):
        pkgs = self._get_selected_packages()
        if not pkgs:
            return
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="App Details", command=self._show_app_info)
        menu.add_separator()
        menu.add_command(label="Start App", command=self._start_app)
        menu.add_command(label="Stop App", command=self._stop_app)
        menu.add_command(label="Extract APK...", command=self._extract_apk)
        menu.add_command(label="Save App Icon...", command=self._save_app_icon)
        menu.add_command(label="Clear Cache", command=self._clear_app_cache)
        menu.add_separator()
        menu.add_command(label="Uninstall App", command=self._uninstall_app)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

