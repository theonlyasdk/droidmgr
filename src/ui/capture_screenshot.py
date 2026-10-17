"""One-click PNG screenshot capture."""

import threading
from pathlib import Path
from tkinter import filedialog
from core import ConfigManager
from .capture_utils import (
    _default_dir, _existing_dir, _timestamp, remember_folder,
)


def take_screenshot(root, device_manager, device_id, set_status, show_error, show_info) -> None:
    """Screenshot current screen with ADB and open save dialog remembering last location."""
    set_status("Capturing screenshot...")

    def task():
        try:
            data = device_manager.capture_screenshot(device_id)
        except Exception as exc:
            message = str(exc)
            root.after(0, lambda: show_error("Screenshot Error", message))
            return

        def on_captured():
            config = ConfigManager()
            initial_dir = _existing_dir(
                config.get('capture', 'screenshot_dir', ''),
                _default_dir('screenshot'),
            )
            path = filedialog.asksaveasfilename(
                parent=root,
                title="Save Screenshot",
                initialdir=initial_dir,
                initialfile=f"screenshot-{_timestamp()}.png",
                defaultextension=".png",
                filetypes=[("PNG image", "*.png"), ("All files", "*.*")],
            )
            if not path:
                set_status("Screenshot cancelled")
                return

            try:
                Path(path).write_bytes(data)
            except OSError as exc:
                show_error("Screenshot Error", f"Could not write the file:\n{exc}")
                return

            folder = str(Path(path).parent)
            config.set('capture', 'screenshot_dir', folder)
            _on_screenshot_saved(root, path, config, set_status, show_info)

        root.after(0, on_captured)

    threading.Thread(target=task, daemon=True).start()


def _on_screenshot_saved(root, path, config, set_status, show_info) -> None:
    remember_folder(root, config, 'screenshot_dir', 'Screenshot', path, set_status, show_info)
