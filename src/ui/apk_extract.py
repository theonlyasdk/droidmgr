"""Pull an installed package's APK off the device, split APKs included."""

import threading
from tkinter import filedialog

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


def _on_apk_extracted(root, result, package, config, set_status, show_info) -> None:
    note = ''
    if result['is_split']:
        note = (f"\n\n{package} is a split app. Its {len(result['members'])} APKs were "
                f"bundled into one .apks file:\n{', '.join(result['members'])}\n"
                "Install it with a split-aware installer such as SAI.")
    remember_folder(root, config, 'apk_dir', 'APK', result['path'], set_status, show_info, note)
