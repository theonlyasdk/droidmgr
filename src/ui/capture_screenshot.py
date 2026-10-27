"""One-click PNG screenshot capture."""

import threading
from pathlib import Path
from tkinter import filedialog
from typing import Optional
from core import ConfigManager
from .capture_utils import (
    _default_dir, _existing_dir, _timestamp, _unique_path, remember_folder,
)
from .screenshot_gallery import register_screenshot


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
    - If the screenshot is completely black or white, ask the user for confirmation before saving.
    - If ask_everytime is enabled, ask if user wants to save to the default folder or choose another.
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

        # Smart checks for completely black or completely white screenshots
        color = detect_uniform_color(data)

        def on_captured():
            from tkinter import messagebox

            if color == 'black':
                if not messagebox.askyesno(
                    "Black Screenshot",
                    "The captured screenshot is completely black (the screen may be off or showing protected content).\n\n"
                    "Do you want to save it anyway?",
                    parent=root,
                    default=messagebox.NO
                ):
                    set_status("Screenshot cancelled")
                    return

            elif color == 'white':
                if not messagebox.askyesno(
                    "White Screenshot",
                    "The captured screenshot is completely white (empty or blank screen).\n\n"
                    "Do you want to save it anyway?",
                    parent=root,
                    default=messagebox.NO
                ):
                    set_status("Screenshot cancelled")
                    return

            config = ConfigManager()
            _handle_screenshot_save(root, data, config, set_status, show_error, show_info,
                                    device_id)

        root.after(0, on_captured)

    threading.Thread(target=task, daemon=True).start()


def _handle_screenshot_save(root, data: bytes, config: ConfigManager, set_status, show_error, show_info,
                            device_id: str = '') -> None:
    from tkinter import messagebox

    dest_dir = Path(_existing_dir(
        config.get('capture', 'screenshot_dir', ''),
        _default_dir('screenshot'),
    ))
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    ask_everytime = config.get('capture', 'screenshot_ask_everytime', True)
    target_path = _unique_path(dest_dir, f"screenshot-{_timestamp()}", ".png")

    if ask_everytime:
        choice = messagebox.askyesnocancel(
            "Save Screenshot",
            f"Save screenshot here?\n\n{dest_dir}\n\n"
            f"File: {target_path.name}\n\n"
            f"• Yes: Save here\n"
            f"• No: Choose another location\n"
            f"• Cancel: Do not save",
            parent=root,
        )
        if choice is None:
            set_status("Screenshot cancelled")
            return
        if choice is False:
            _save_screenshot_dialog(
                root, data, config, set_status, show_error, show_info,
                initial_dir=str(dest_dir), initial_file=target_path.name,
                device_id=device_id,
            )
            return

    # Direct save when ask_everytime is False or user confirmed Yes
    try:
        target_path.write_bytes(data)
    except OSError as exc:
        show_error("Screenshot Error", f"Could not write the file:\n{exc}")
        return

    folder = str(target_path.parent)
    config.set('capture', 'screenshot_dir', folder)
    _on_screenshot_saved(root, str(target_path), config, set_status, show_info, device_id)


def _save_screenshot_dialog(root, data: bytes, config: ConfigManager, set_status, show_error, show_info,
                            initial_dir: Optional[str] = None, initial_file: Optional[str] = None,
                            device_id: str = '') -> None:
    if not initial_dir:
        initial_dir = _existing_dir(
            config.get('capture', 'screenshot_dir', ''),
            _default_dir('screenshot'),
        )
    if not initial_file:
        initial_file = f"screenshot-{_timestamp()}.png"

    path = filedialog.asksaveasfilename(
        parent=root,
        title="Save Screenshot",
        initialdir=initial_dir,
        initialfile=initial_file,
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
    _on_screenshot_saved(root, path, config, set_status, show_info, device_id)


def _on_screenshot_saved(root, path, config, set_status, show_info, device_id: str = '') -> None:
    # Every screenshot that reached disk joins this run's session gallery.
    register_screenshot(path, device_id)
    remember_folder(root, config, 'screenshot_dir', 'Screenshot', path, set_status, show_info)
