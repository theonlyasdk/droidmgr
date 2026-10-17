"""One-click PNG screenshot capture."""

import threading
from pathlib import Path
from tkinter import filedialog
from typing import Optional
from core import ConfigManager
from .capture_utils import (
    _default_dir, _existing_dir, _timestamp, remember_folder,
)


def detect_uniform_color(png_bytes: bytes) -> Optional[str]:
    """Check if the PNG image is solid black or solid white.

    Returns 'black', 'white', or None.
    """
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(png_bytes))
        extrema = img.getextrema()
        if img.mode in ('RGB', 'RGBA'):
            r, g, b = extrema[0], extrema[1], extrema[2]
            if r[1] == 0 and g[1] == 0 and b[1] == 0:
                return 'black'
            if r[0] == 255 and g[0] == 255 and b[0] == 255:
                return 'white'
        elif img.mode == 'L':
            if extrema[1] == 0:
                return 'black'
            if extrema[0] == 255:
                return 'white'
    except Exception:
        try:
            import zlib, struct
            pos = 8
            idat_parts = []
            while pos < len(png_bytes):
                length, ctype = struct.unpack('>I4s', png_bytes[pos:pos+8])
                if ctype == b'IDAT':
                    idat_parts.append(png_bytes[pos+8:pos+8+length])
                elif ctype == b'IEND':
                    break
                pos += 8 + length + 4
            raw = zlib.decompress(b''.join(idat_parts))
            if not any(b != 0 for b in raw):
                return 'black'
            if not any(b != 255 for b in raw):
                return 'white'
        except Exception:
            pass
    return None


def take_screenshot(root, device_manager, device_id, set_status, show_error, show_info,
                    show_warning=None) -> None:
    """Screenshot current screen with ADB and open save dialog remembering last location.

    Smart checks:
    - If the screen is off (or black), alert the user and do not save a blank screen.
    - If completely white, warn only and open save dialog.
    """
    if show_warning is None:
        def show_warning(msg):
            from tkinter import messagebox
            messagebox.showwarning("Warning", msg, parent=root)
            set_status(f"Warning: {msg}")

    set_status("Capturing screenshot...")

    def task():
        try:
            data = device_manager.capture_screenshot(device_id)
        except Exception as exc:
            message = str(exc)
            root.after(0, lambda: show_error("Screenshot Error", message))
            return

        # Smart checks for screen off (black) and all-white edge case
        color = detect_uniform_color(data)
        screen_on = True
        if color == 'black':
            try:
                if hasattr(device_manager, 'is_screen_on'):
                    screen_on = device_manager.is_screen_on(device_id)
            except Exception:
                pass

        def on_captured():
            from tkinter import messagebox

            if color == 'black' or not screen_on:
                if not screen_on:
                    show_error(
                        "Screenshot Error",
                        "The device screen is off (the screenshot is completely black).\n"
                        "Please turn on the device screen and try again."
                    )
                    set_status("Screenshot failed: device screen is off")
                    return
                # Screen was reported on, but the captured image is solid black (e.g. DRM/FLAG_SECURE or dark app)
                if not messagebox.askyesno(
                    "Black Screenshot",
                    "The captured screenshot is completely black (the screen may be off or showing protected content).\n\n"
                    "Do you want to save it anyway?",
                    parent=root,
                    default=messagebox.NO
                ):
                    set_status("Screenshot cancelled: black screenshot")
                    return

            elif color == 'white':
                # Edge case: completely white (warn only)
                show_warning("The captured screenshot is completely white (empty or blank screen).")

            _save_screenshot_dialog(root, data, set_status, show_error, show_info)

        root.after(0, on_captured)

    threading.Thread(target=task, daemon=True).start()


def _save_screenshot_dialog(root, data, set_status, show_error, show_info) -> None:
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


def _on_screenshot_saved(root, path, config, set_status, show_info) -> None:
    remember_folder(root, config, 'screenshot_dir', 'Screenshot', path, set_status, show_info)
