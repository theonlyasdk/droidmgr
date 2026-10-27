"""MainWindow mixin: per-app actions (start/stop/clear/uninstall/APK)."""

import shutil
import tempfile
import threading
import time
import tkinter as tk
import zipfile
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
from typing import Dict, List, Optional
from .apk_extract import extract_apk, extract_many
from .app_info_dialog import AppInfoDialog
from .apk_install_options import APKInstallOptionsDialog
from .apk_install_progress import APKInstallProgressDialog, format_elapsed
from .uninstall_options import UninstallOptionsDialog
from .main_utils import (_is_clear_denied, _CLEAR_DENIED_MESSAGE,
    _looks_like_system_package)


def _extract_apk_container(container: Path, scratch: Path):
    """Pull the .apk members of an .xapk/.apks bundle out to scratch.

    The base APK is written first, so the resulting list is ready to hand to
    `install-multiple` in the required order.
    """
    with zipfile.ZipFile(container) as bundle:
        names = [name for name in bundle.namelist()
                 if name.lower().endswith('.apk')]
        if not names:
            raise ValueError("The bundle contains no .apk files.")
        ordered = sorted(names, key=lambda name: (
            0 if Path(name).name.lower() == 'base.apk' else 1, name.lower()))
        members = []
        for name in ordered:
            target = scratch / Path(name).name
            with bundle.open(name) as source, open(target, 'wb') as sink:
                shutil.copyfileobj(source, sink)
            members.append(target)
        return members


def _group_plain_apks(plain):
    """Chunk plain APKs into install sets plus singles.

    A dropped base.apk next to split_*.apk files is one app: the group is
    installed together with `install-multiple`. Everything else installs on
    its own, exactly as before.
    """
    lower = {path: path.name.lower() for path in plain}
    splits = [path for path in plain if lower[path].startswith('split_')]
    if any(name == 'base.apk' for name in lower.values()) and splits:
        ordered = sorted(plain, key=lambda path: (
            0 if lower[path] == 'base.apk' else 1, lower[path]))
        return [(ordered, True)]
    return [([path], False) for path in plain]


def _apk_package_name(apk_path: Path) -> str:
    """The package an APK declares, read offline; '' when it cannot be read."""
    try:
        from core.apk_inspect import inspect_apk
    except Exception:
        return ''
    try:
        return inspect_apk(str(apk_path)).get('package') or ''
    except Exception:
        return ''


def _grant_all_note(watcher, device_id: str, apk_path: Path) -> str:
    """One report line for the grant-all outcome of an installed APK.

    Runs on the background install thread; it only touches device_manager
    and reads local files, never Tk.
    """
    package = _apk_package_name(apk_path)
    if not package:
        return (f"Grant-all skipped: the package name inside '{apk_path.name}' "
                "could not be read from its manifest.")
    try:
        outcome = watcher.device_manager.adb.grant_all_runtime_permissions(
            device_id, package)
    except Exception as e:
        return f"Grant-all on {package} failed: {e}"

    granted_count = len(outcome['granted'])
    failed = outcome['failed']
    if not outcome['requested']:
        return f"Grant-all: {package} requests no permissions."
    if failed:
        first_name = next(iter(failed))
        return (f"Grant-all on {package}: {granted_count} of "
                f"{len(outcome['requested'])} permissions granted; {len(failed)} "
                f"failed, e.g. {first_name}: {failed[first_name]}")
    return (f"Grant-all: all {granted_count} runtime permissions of {package} "
            "granted (root).")


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

        options_dialog = UninstallOptionsDialog(self.root, packages)
        self.root.wait_window(options_dialog)
        options = options_dialog.result
        if not options:
            return
        keep_data = options['keep_data']
        all_users = options['all_users']

        if len(packages) > 1:
            if not self._confirm_bulk_uninstall(packages):
                return
        else:
            if not self._confirm_single_uninstall(device_id, packages[0]):
                return

        self._set_status(f"Uninstalling {len(packages)} "
                         f"application{'s' if len(packages) > 1 else ''}...")

        def task():
            failed = {}
            for package in packages:
                try:
                    self.device_manager.uninstall_app(device_id, package,
                                                      keep_data, all_users)
                except Exception as e:
                    failed[package] = str(e)
            self.root.after(0, self._refresh_apps)
            suffix = ' (data kept)' if keep_data else ''
            if failed:
                detail = '\n'.join(f"  - {pkg}: {msg}"
                                   for pkg, msg in list(failed.items())[:10])
                if len(failed) > 10:
                    detail += f"\n  ... and {len(failed) - 10} more"
                self.root.after(0, lambda: self._show_error(
                    "Uninstall Error",
                    f"{len(failed)} of {len(packages)} could not be "
                    f"uninstalled:\n{detail}"))
            elif len(packages) == 1:
                self.root.after(0, lambda: messagebox.showinfo(
                    "Success", f"Successfully uninstalled {packages[0]}{suffix}"))
            else:
                self.root.after(0, lambda: messagebox.showinfo(
                    "Success", f"Successfully uninstalled {len(packages)} "
                               f"applications{suffix}"))

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
        """Ask for APK files or an APK bundle and install them."""
        if not self._require_device():
            return

        apk_path = filedialog.askopenfilename(
            title="Select APK file or bundle",
            filetypes=[("APK files", "*.apk *.xapk *.apks"),
                       ("All files", "*.*")]
        )

        if apk_path:
            self._install_apk_paths([apk_path])

    def _install_apk_paths(self, paths):
        """Install APKs from the picker or a drop; bundles are opened first.

        Plain files install one by one, as before. An .xapk/.apks bundle, or
        a base.apk dropped beside its split_*.apk files, is installed as one
        set through `install-multiple`. Every gate waits for a click in a
        dialog: the options-and-confirm window, one indeterminate progress
        window, then the outcome with a copyable report.
        """
        if not self._require_device():
            return

        if getattr(self, '_apk_install_active', False):
            self._show_warning(
                "An APK installation is already running. Please wait for it to finish.")
            return

        raw = [Path(p) for p in paths]
        plain = [path for path in raw if path.suffix.lower() == '.apk']
        containers = [path for path in raw
                      if path.suffix.lower() in ('.xapk', '.apks')]
        if not plain and not containers:
            self._show_error("No APKs",
                             "None of the selected files are .apk, .xapk or .apks files.")
            return

        for path in plain:
            if not path.exists() or not path.is_file():
                self._show_error("Invalid File",
                                 f"This file does not exist or is invalid:\n{path}")
                return

        install_sets = []
        scratch = tempfile.TemporaryDirectory(prefix='droidmgr-apk-') if containers else None
        try:
            if scratch is not None:
                scratch_path = Path(scratch.name)
                for container in containers:
                    try:
                        members = _extract_apk_container(container, scratch_path)
                    except Exception as e:
                        raise ValueError(f"'{container.name}' could not be "
                                         f"opened as an APK bundle:\n{e}")
                    if not members:
                        raise ValueError(f"'{container.name}' holds no APKs.")
                    total_mb = sum(m.stat().st_size for m in members) / (1024 * 1024)
                    install_sets.append({
                        'label': f"{container.name} ({len(members)} APKs)",
                        'paths': members,
                        'is_set': True,
                        'size_mb': total_mb,
                    })
        except Exception as e:
            if scratch is not None:
                scratch.cleanup()
            self._show_error("Bad APK Bundle", str(e))
            return

        for group_paths, is_set in _group_plain_apks(plain):
            total_mb = sum(path.stat().st_size for path in group_paths) / (1024 * 1024)
            label = (f"{group_paths[0].name} (+{len(group_paths) - 1} splits)"
                     if is_set else group_paths[0].name)
            install_sets.append({
                'label': label,
                'paths': group_paths,
                'is_set': is_set,
                'size_mb': total_mb,
            })

        entries = [(item['label'], item['size_mb']) for item in install_sets]
        biggest_mb = max(item['size_mb'] for item in install_sets)
        big_note = ''
        if biggest_mb > 500:
            big_note = (f"Note: the largest file is {biggest_mb:.1f} MB. Installing "
                        "large applications over ADB may take several minutes.")

        dialog = APKInstallOptionsDialog(self.root, self.selected_device, entries,
                                         big_note=big_note)
        self.root.wait_window(dialog)
        options = dialog.result
        if not options:
            if scratch is not None:
                scratch.cleanup()
            return

        label = install_sets[0]['label'] if len(install_sets) == 1 \
            else f"{len(install_sets)} install set(s)"
        total_mb = sum(item['size_mb'] for item in install_sets)
        progress_dialog = APKInstallProgressDialog(self.root, label, total_mb)
        device_id = self.selected_device
        self._apk_install_active = True
        self._apk_install_scratch = scratch
        grant_all = options.get('grant_all')

        def task():
            installed, failures, notes = [], [], []
            started = time.monotonic()
            for item in install_sets:
                label = item['label']
                try:
                    if item['is_set']:
                        self.device_manager.adb.install_apk_set(
                            device_id, [str(path) for path in item['paths']], options)
                    else:
                        self.device_manager.adb.install_apk(
                            device_id, str(item['paths'][0]), options)
                    installed.append(label)

                    if grant_all:
                        notes.append(_grant_all_note(
                            self, device_id, item['paths'][0]))
                except Exception as e:
                    failures.append(f"{label}: {e}")
            elapsed = time.monotonic() - started
            self.root.after(0, lambda: self._finish_apk_install(
                progress_dialog, label, elapsed, installed, failures, notes))

        self._set_status(f"Installing {label}...")
        threading.Thread(target=task, daemon=True).start()

    def _finish_apk_install(self, progress_dialog, label, elapsed, installed,
                            failures, notes=None):
        """Report the finished install in the install dialog and refresh the list."""
        self._apk_install_active = False
        scratch = getattr(self, '_apk_install_scratch', None)
        self._apk_install_scratch = None
        if scratch is not None:
            scratch.cleanup()
        progress_dialog.finish(elapsed, installed, failures, notes)
        if failures:
            self._set_status(f"Install Error: {len(failures)} of "
                             f"{len(installed) + len(failures)} install(s) failed")
        else:
            self._set_status(f"Installed '{label}' in {format_elapsed(elapsed)}")
        self._refresh_apps()

    def _extract_apk(self):
        """Applications > Extract APK: pull the selected package(s) off the device."""
        if not self._require_device():
            return
        packages = self._get_selected_packages()
        if not packages:
            self._show_warning("Please select an application first")
            return
        if len(packages) == 1:
            extract_apk(self.root, self.device_manager, self.selected_device,
                        packages[0], self._set_status, self._show_error,
                        self._show_info)
            return
        extract_many(self.root, self.device_manager, self.selected_device,
                     packages, self._set_status, self._show_error,
                     self._show_info)



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

