"""Session gallery of every screenshot saved while droidmgr runs.

The module keeps a process-wide list of saved screenshots
(register_screenshot is called by capture_screenshot on every disk save),
and ScreenshotGalleryDialog shows them as a scrollable thumbnail grid with
save-all, upload-to-device and file actions.
"""

import ctypes
import os
import shutil
import struct
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
from typing import Callable, Dict, List, Optional

from .capture_utils import _unique_path, open_path
from .dpi import setup_window_dpi
from .tile_assets import load_scaled_icon


THUMB_WIDTH = 160     # Screenshot thumbnails are scaled to roughly this width.
GALLERY_COLUMNS = 4   # Thumbnails per row at the default dialog width.

# Device states that cannot take an uploaded file right away.
_SKIP_STATUSES = {'offline', 'unauthorized', 'bootloader', 'recovery',
                  'sideload', 'fastboot'}


# -- session list -----------------------------------------------------------

_session_items: List[Dict[str, object]] = []   # newest first
_registered_paths = set()
_session_lock = threading.Lock()


def register_screenshot(path, device_id: str = '') -> None:
    """Record a saved screenshot in this run's session list.

    Idempotent: the same file path is registered only once, so a screenshot
    landing in the gallery twice keeps a single entry. Newest entries go first.
    """
    try:
        key = os.path.abspath(str(path))
    except Exception:
        key = str(path or '')
    if not key or key == os.path.abspath(os.sep):
        return
    with _session_lock:
        if key in _registered_paths:
            return
        _registered_paths.add(key)
        _session_items.insert(0, {
            'path': key,
            'device_id': str(device_id or ''),
            'time': datetime.now(),
        })


def session_screenshots() -> List[Dict[str, object]]:
    """Snapshot of the session entries, newest first."""
    with _session_lock:
        return [dict(item) for item in _session_items]


# -- dialog -----------------------------------------------------------------

class ScreenshotGalleryDialog(tk.Toplevel):
    """Modal grid of the screenshots taken during this run of the app."""

    def __init__(self, parent, device_manager, selected_device: str = '',
                 set_status: Optional[Callable[[str], None]] = None,
                 show_error: Optional[Callable[[str, str], None]] = None):
        super().__init__(parent)
        self.title("Session Screenshot Gallery")
        self.device_manager = device_manager
        self.selected_device = selected_device or ''

        self._set_status = set_status or (lambda message: None)
        if show_error is not None:
            self._show_error = show_error
        else:
            def _default_error(title, message):
                messagebox.showerror(title, message, parent=self)
            self._show_error = _default_error

        self._items = session_screenshots()
        self._selected_index = 0
        self._thumbs: List[Optional[tk.PhotoImage]] = []
        self._labels: List[tk.Label] = []

        self.resizable(True, True)
        self.transient(parent)

        self._create_widgets()
        self._populate_gallery()

        setup_window_dpi(self, base_width=800, base_height=560,
                         min_width=520, min_height=380, parent=parent)

        self.wait_visibility()
        self.grab_set()
        self.bind('<Escape>', lambda e: self._close())
        self.protocol('WM_DELETE_WINDOW', self._close)

    # -- construction -------------------------------------------------------

    def _create_widgets(self):
        toolbar = ttk.Frame(self, padding=(10, 10, 10, 0))
        toolbar.pack(fill=tk.X)

        ttk.Button(toolbar, text="Save All...",
                   command=self._save_all).pack(side=tk.LEFT, padx=(0, 6))

        device_ids = self._lookup_device_ids()
        self._device_combo = ttk.Combobox(toolbar, state='readonly', width=18,
                                          values=device_ids,
                                          textvariable=tk.StringVar())
        if device_ids:
            self._device_combo.current(0)
        self._device_combo.pack(side=tk.LEFT, padx=(0, 6))

        self._send_btn = ttk.Button(toolbar, text="Send to Device...",
                                    command=self._send_to_device,
                                    state='normal' if device_ids else 'disabled')
        self._send_btn.pack(side=tk.LEFT, padx=(0, 6))

        ttk.Button(toolbar, text="Close",
                   command=self._close).pack(side=tk.RIGHT)

        container = ttk.Frame(self, padding=(10, 8))
        container.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(container, highlightthickness=0)
        vsb = ttk.Scrollbar(container, orient='vertical',
                            command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._inner = ttk.Frame(self.canvas, padding=4)
        self.canvas.create_window((0, 0), window=self._inner,
                                  anchor='nw', tags='inner')
        self._inner.bind(
            '<Configure>',
            lambda event: self.canvas.configure(
                scrollregion=self.canvas.bbox('all')))
        self.canvas.bind(
            '<Configure>',
            lambda event: self.canvas.itemconfigure(
                'inner', width=event.width))
        self.canvas.bind(
            '<Enter>', lambda e: self.canvas.bind_all(
                '<MouseWheel>',
                lambda event: self.canvas.yview_scroll(
                    -1 * (event.delta // 120), 'units')))
        self.canvas.bind('<Leave>', lambda e: self.canvas.unbind_all('<MouseWheel>'))

        self._menu = tk.Menu(self, tearoff=0)
        self._menu.add_command(label="Copy Image", command=self._copy_selected)
        self._menu.add_command(label="Open", command=self._open_selected)
        self._menu.add_command(label="Reveal in Folder", command=self._reveal_selected)

        self._status_text = tk.StringVar(
            self, f"{len(self._items)} screenshot(s) taken this session"
            if self._items else "")
        ttk.Label(self, textvariable=self._status_text,
                  padding=(10, 4), anchor='center').pack(side=tk.BOTTOM, fill=tk.X)

    def _lookup_device_ids(self) -> List[str]:
        """Best-effort adb devices for the Send to Device picker."""
        ids: List[str] = []
        if self.device_manager is None:
            return ids
        try:
            for info in self.device_manager.get_devices():
                device_id = str(info.get('id', ''))
                if not device_id:
                    continue
                if str(info.get('status', 'device')).lower() in _SKIP_STATUSES:
                    continue
                ids.append(device_id)
        except Exception:
            pass
        # The device the user was working with leads the list if still there.
        if self.selected_device and self.selected_device in ids:
            ids.remove(self.selected_device)
            ids.insert(0, self.selected_device)
        return ids

    def _populate_gallery(self):
        self._thumbs = []
        self._labels = []
        for col in range(GALLERY_COLUMNS):
            self._inner.columnconfigure(col, weight=1, uniform='gallery')

        if not self._items:
            tk.Label(self._inner, text="No screenshots taken this session",
                     fg='#808080', font=('Segoe UI', 10)).grid(
                row=0, column=0, columnspan=GALLERY_COLUMNS, pady=(40, 60))
            return

        for index, item in enumerate(self._items):
            thumb = load_scaled_icon(str(item['path']), THUMB_WIDTH, self)
            self._thumbs.append(thumb)
            device = str(item['device_id']) or 'unknown device'
            caption = f"{Path(str(item['path'])).name}\n{device}"
            label = tk.Label(
                self._inner,
                compound='top',
                image=thumb,
                text=caption if thumb else f"{caption}\n(thumbnail unavailable)",
                wraplength=THUMB_WIDTH + 16,
                justify='center',
                font=('Segoe UI', 8),
                borderwidth=1,
                relief='flat')
            row, col = divmod(index, GALLERY_COLUMNS)
            label.grid(row=row, column=col, padx=6, pady=6, sticky='nsew')
            label.bind('<Button-1>',
                       lambda event, idx=index: self._select(idx))
            label.bind('<Double-Button-1>',
                       lambda event, idx=index: self._open_item(idx))
            label.bind('<Button-3>',
                       lambda event, idx=index: self._show_item_menu(event, idx))
            self._labels.append(label)

        self._select(0)

    def _select(self, index: int):
        if not (0 <= index < len(self._labels)):
            return
        self._selected_index = index
        for idx, label in enumerate(self._labels):
            label.config(relief='solid' if idx == index else 'flat')

    def _selected_path(self) -> Optional[str]:
        if 0 <= self._selected_index < len(self._items):
            return str(self._items[self._selected_index]['path'])
        return None

    # -- actions ------------------------------------------------------------

    def _close(self):
        self.destroy()

    def _set_status_text(self, message: str):
        self._status_text.set(message)
        try:
            self._set_status(message)
        except Exception:
            pass

    def _open_path(self, path: str) -> bool:
        if open_path(path):
            return True
        self._show_error(
            "Open Error", f"Could not open the file:\n{path}")
        return False

    def _open_item(self, index: int):
        path = str(self._items[index]['path'])
        self._select(index)
        if not Path(path).is_file():
            self._show_error(
                "Open Error", "The file is no longer at its saved location:\n" + path)
            return
        self._open_path(path)

    def _open_selected(self):
        path = self._selected_path()
        if path:
            self._open_item(self._selected_index)

    def _reveal_selected(self):
        path = self._selected_path()
        if not path:
            return
        self._open_path(str(Path(path).parent))

    def _copy_selected(self):
        path = self._selected_path()
        if not path:
            return
        if _copy_image_to_clipboard(self, path):
            self._set_status_text(
                f"Image copied to clipboard: {Path(path).name}")
        else:
            self._show_error(
                "Copy Image",
                f"Could not copy the image to the clipboard:\n{path}")

    def _show_item_menu(self, event, index: int):
        self._select(index)
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()

    def _save_all(self):
        """Copy every session screenshot into one folder the user picks."""
        folder = filedialog.askdirectory(
            parent=self, title="Save All Screenshots")
        if not folder:
            return
        dest_root = Path(folder)
        copied = 0
        missing = 0
        failed: List[str] = []
        for item in self._items:
            src = Path(str(item['path']))
            if not src.is_file():
                missing += 1
                continue
            dest = dest_root / src.name
            if dest.exists():
                dest = _unique_path(dest_root, src.stem, src.suffix)
            try:
                shutil.copy2(src, dest)
                copied += 1
            except OSError as exc:
                failed.append(f"{src.name}: {exc}")

        if failed:
            self._show_error(
                "Save All",
                f"Copied {copied} of {len(self._items)} screenshots to:\n{dest_root}\n\n"
                "Failed:\n" + "\n".join(failed[:5]))
        elif missing:
            messagebox.showinfo(
                "Save All",
                f"Copied {copied} screenshots to:\n{dest_root}\n\n"
                f"{missing} file(s) no longer exist on disk.",
                parent=self)
        else:
            self._set_status_text(f"Saved {copied} screenshot(s) to {dest_root}")

    def _send_to_device(self):
        device = self._device_combo.get()
        path = self._selected_path()
        if not path:
            return
        if not device:
            messagebox.showinfo(
                "Send to Device", "Select a device in the picker.", parent=self)
            return
        name = Path(path).name
        remote_dir = '/sdcard/Pictures'
        remote = f"{remote_dir}/{name}"
        self._send_btn.config(state='disabled')
        self._set_status_text(f"Uploading {name} to {device}...")

        def task():
            try:
                try:
                    # Destination folder normally exists; mkdir only best-effort.
                    self.device_manager.make_directory(device, remote_dir)
                except Exception:
                    pass
                self.device_manager.upload_file(device, path, remote)
                error = None
            except Exception as exc:
                error = str(exc)

            def done():
                if not self.winfo_exists():
                    return
                self._send_btn.config(state='normal')
                if error is None:
                    self._set_status_text(
                        f"Uploaded {name} to {device}:{remote}")
                else:
                    self._show_error(
                        "Send to Device",
                        f"Could not upload {name} to {device}:\n{error}")

            try:
                self.after(0, done)
            except Exception:
                pass

        threading.Thread(target=task, daemon=True).start()


# -- clipboard image copy ---------------------------------------------------

_RGB_TO_DIB_HEADER = struct.Struct('<IiiHHIIiiII')
_CF_DIB = 8
_GMEM_MOVEABLE = 0x0002


def _p6_to_dib(ppm: bytes) -> Optional[bytes]:
    """Turn a binary PPM (P6) picture into a Windows CF_DIB byte block.

    Tk's PhotoImage decodes PNG for us and re-releases the pixels as P6, so
    no image library is needed; rows become bottom-up BGR per the DIB format.
    """
    if not ppm.startswith(b'P6'):
        return None
    pos = 2
    tokens = []
    while len(tokens) < 3:
        while pos < len(ppm) and ppm[pos] in b' \t\r\n':
            pos += 1
        if ppm[pos:pos + 1] == b'#':
            while pos < len(ppm) and ppm[pos] not in b'\r\n':
                pos += 1
            continue
        start = pos
        while pos < len(ppm) and ppm[pos] not in b' \t\r\n':
            pos += 1
        if start == pos:
            return None
        tokens.append(ppm[start:pos])
    try:
        width, height, maxval = (int(t) for t in tokens)
    except ValueError:
        return None
    if width <= 0 or height <= 0 or maxval != 255:
        return None
    pos += 1  # the single whitespace byte after maxval
    row_bytes = width * 3
    pad = (4 - row_bytes % 4) % 4
    pixels_start = pos
    pixels_end = pixels_start + height * row_bytes
    if pixels_end > len(ppm):
        return None
    pixels = ppm[pixels_start:pixels_end]
    rows = []
    for y in range(height - 1, -1, -1):  # DIB rows run bottom-up
        src = pixels[y * row_bytes:(y + 1) * row_bytes]
        dst = bytearray(row_bytes)
        dst[0::3] = src[2::3]  # B
        dst[1::3] = src[1::3]  # G
        dst[2::3] = src[0::3]  # R
        if pad:
            dst.extend(b'\x00' * pad)
        rows.append(bytes(dst))
    data = b''.join(rows)
    header = _RGB_TO_DIB_HEADER.pack(
        40, width, height, 1, 24, 0, len(data), 2835, 2835, 0, 0)
    return header + data


def _set_clipboard_dib(dib: bytes) -> bool:
    """Put raw DIB bytes on the Windows clipboard (pasteable as a bitmap)."""
    if os.name != 'nt':
        return False
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.restype = ctypes.c_int
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [
            ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            hmem = kernel32.GlobalAlloc(_GMEM_MOVEABLE,
                                        ctypes.c_size_t(len(dib)))
            if not hmem:
                return False
            ptr = kernel32.GlobalLock(hmem)
            if not ptr:
                kernel32.GlobalFree(hmem)
                return False
            try:
                ctypes.memmove(ptr, dib, ctypes.c_size_t(len(dib)))
            finally:
                kernel32.GlobalUnlock(hmem)
            if not user32.SetClipboardData(_CF_DIB, hmem):
                kernel32.GlobalFree(hmem)
                return False
            return True
        finally:
            user32.CloseClipboard()
    except Exception:
        return False


def _copy_image_to_clipboard(master, path: str) -> bool:
    """Copy a PNG file to the clipboard as a bitmap image."""
    try:
        img = tk.PhotoImage(master=master, file=path)
    except Exception:
        return False
    try:
        ppm = img.data(format='ppm')
    except Exception:
        ppm = None
    finally:
        img.destroy()
    if not ppm:
        return False
    if isinstance(ppm, str):
        ppm = ppm.encode('latin-1', 'replace')
    dib = _p6_to_dib(ppm)
    if dib is None:
        return False
    return _set_clipboard_dib(dib)
