"""Pull installed packages' APKs off the device, split APKs included."""

import threading
import time
import zipfile
from tkinter import filedialog, messagebox
from pathlib import Path

from core import ConfigManager
from .capture import _default_dir, _existing_dir, remember_folder


def extract_apk(root, device_manager, device_id, package, set_status,
                show_error, show_info) -> None:
    """Pick a destination folder, pull the APK, then offer to remember the folder."""
    config = ConfigManager()
    folder = filedialog.askdirectory(
        parent=root,
        title=f"Select folder for {package}",
        initialdir=_existing_dir(config.get('capture', 'apk_dir', ''), _default_dir('apk')),
    )
    if not folder:
        return

    set_status(f"Extracting {package}...")

    def task():
        try:
            result = device_manager.extract_apk(device_id, package, folder)
        except Exception as exc:
            message = str(exc)
            root.after(0, lambda: show_error("APK Extraction Error", message))
            return
        root.after(0, lambda: _on_apk_extracted(root, result, package, config,
                                                set_status, show_info))

    threading.Thread(target=task, daemon=True).start()


def extract_many(root, device_manager, device_id, packages, set_status,
                 show_error, show_info) -> None:
    """Extract every selected package into one folder, then offer to zip them.

    Each package ends up as its own file (.apk, or .apks for split apps),
    just like the single-package flow; the zip step is optional and only
    bundles those files.
    """
    config = ConfigManager()
    folder = filedialog.askdirectory(
        parent=root,
        title=f"Select folder for {len(packages)} applications",
        initialdir=_existing_dir(config.get('capture', 'apk_dir', ''), _default_dir('apk')),
    )
    if not folder:
        return

    set_status(f"Extracting {len(packages)} packages...")

    def task():
        results, failures = [], []
        for package in packages:
            try:
                results.append((package, device_manager.extract_apk(device_id,
                                                                    package, folder)))
            except Exception as exc:
                failures.append(f"{package}: {exc}")
        if failures and not results:
            message = '\n'.join(failures)
            root.after(0, lambda: show_error("APK Extraction Error", message))
            return
        root.after(0, lambda: _on_many_extracted(root, device_id, folder, results,
                                                 failures, config, set_status,
                                                 show_info))

    threading.Thread(target=task, daemon=True).start()


def _on_many_extracted(root, device_id, folder, results, failures, config,
                       set_status, show_info) -> None:
    paths = [result['path'] for _, result in results]
    if failures:
        set_status(f"Extraction finished with {len(failures)} failure(s)")
        show_error("Some extractions failed", '\n'.join(failures))
    count = len(paths)
    if not count:
        return

    if not messagebox.askyesno(
            "Bundle Extracted APKs?",
            f"{count} file{'s' if count != 1 else ''} extracted to:\n{folder}\n\n"
            "Zip them all into one archive as well?", parent=root):
        remember_folder(root, config, 'apk_dir', 'APK', paths[0], set_status,
                        show_info,
                        note=f"Extracted {count} applications to {folder}")
        return

    zip_path = Path(folder) / f"apks_{device_id}_{time.strftime('%Y%m%d-%H%M%S')}.zip"
    set_status("Zipping extracted APKs...")

    def task():
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as archive:
                for path in paths:
                    archive.write(path, arcname=Path(path).name)
        except Exception as exc:
            message = f"Zipping failed: {exc}"
            root.after(0, lambda: set_status(message))
            return
        root.after(0, lambda: remember_folder(root, config, 'apk_dir', 'APK',
                                              str(zip_path), set_status,
                                              show_info,
                                              note=(f"Extracted {count} applications "
                                                    f"and packed them into\n{zip_path}")))

    threading.Thread(target=task, daemon=True).start()


def _on_apk_extracted(root, result, package, config, set_status, show_info) -> None:
    note = ''
    if result['is_split']:
        note = (f"\n\n{package} is a split app. Its {len(result['members'])} APKs were "
                f"bundled into one .apks file:\n{', '.join(result['members'])}\n"
                "Install it with a split-aware installer such as SAI.")
    remember_folder(root, config, 'apk_dir', 'APK', result['path'], set_status, show_info, note)
