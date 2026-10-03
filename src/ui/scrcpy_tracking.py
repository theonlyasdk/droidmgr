"""Scrcpy window tracking and pinning for the overlay toolbar."""

import ctypes
from ctypes import wintypes
from typing import Optional

from .scrcpy_keys import (
    HWND_TOPMOST,
    HWND_NOTOPMOST,
    SWP_NOMOVE,
    SWP_NOSIZE,
    SWP_NOACTIVATE,
)


class ScrcpyTrackingMixin:
    """Window tracking methods for ScrcpyOverlayToolbar."""


    # --- Window Tracking & Pinning ------------------------------------------

    def _find_scrcpy_hwnd(self) -> Optional[int]:
        """Locate the scrcpy SDL window by title, PID, or partial title match."""
        user32 = ctypes.windll.user32

        # 1. Search by exact window title if set
        if self.target_window_title:
            hwnd = user32.FindWindowW(None, self.target_window_title)
            if hwnd and user32.IsWindowVisible(hwnd):
                return hwnd

        # 2. Search by process PID
        if self.process and self.process.pid:
            pid = self.process.pid
            found = []

            def enum_cb(hwnd, _):
                if user32.IsWindowVisible(hwnd):
                    w_pid = ctypes.c_ulong()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(w_pid))
                    if w_pid.value == pid:
                        rect = wintypes.RECT()
                        user32.GetWindowRect(hwnd, ctypes.byref(rect))
                        w = rect.right - rect.left
                        h = rect.bottom - rect.top
                        if w > 80 and h > 80:
                            found.append(hwnd)
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
            if found:
                return found[0]

        # 3. Fallback: Search top-level window by title keywords (e.g. scrcpy or device id)
        found_by_title = []
        target_words = []
        if self.device_id:
            target_words.append(self.device_id.lower())
        if self.target_window_title:
            target_words.append(self.target_window_title.lower())
        target_words.append("scrcpy")

        my_id = int(self.winfo_id()) if self.winfo_exists() else 0

        def enum_title_cb(hwnd, _):
            if user32.IsWindowVisible(hwnd) and hwnd != my_id:
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title_lower = buf.value.lower()
                    if any(w in title_lower for w in target_words):
                        found_by_title.append(hwnd)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(WNDENUMPROC(enum_title_cb), 0)
        if found_by_title:
            return found_by_title[0]

        return None

    def _track_scrcpy_window(self):
        """Periodically sync position with scrcpy and check if process is alive."""
        if not self._is_alive:
            return

        # Check process state
        if self.process and self.process.poll() is not None:
            self._close_toolbar()
            return

        user32 = ctypes.windll.user32
        if not self.scrcpy_hwnd or not user32.IsWindow(self.scrcpy_hwnd):
            self.scrcpy_hwnd = self._find_scrcpy_hwnd()

        if self.scrcpy_hwnd and user32.IsWindow(self.scrcpy_hwnd):
            # Check if scrcpy is minimized
            if user32.IsIconic(self.scrcpy_hwnd):
                if self.winfo_viewable():
                    self.withdraw()
            else:
                if not self.winfo_viewable():
                    self.deiconify()

                # Follow scrcpy window if snap/dock is enabled
                if self._following:
                    rect = wintypes.RECT()
                    user32.GetWindowRect(self.scrcpy_hwnd, ctypes.byref(rect))
                    cur = (rect.left, rect.top, rect.right, rect.bottom)
                    if cur != self._last_rect:
                        self._last_rect = cur
                        self._position_over_scrcpy(rect)

        self.after(150, self._track_scrcpy_window)

    def _position_over_scrcpy(self, rect: wintypes.RECT):
        """Align the vertical toolbar along the right edge of the scrcpy window."""
        self.update_idletasks()
        tb_width = self.winfo_reqwidth() or 46
        tb_height = self.winfo_reqheight() or 540

        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()

        # Stick to the right edge of the scrcpy window
        x = rect.right + 2
        # If right edge exceeds screen, dock just inside the right edge of scrcpy
        if x + tb_width > screen_w:
            x = max(rect.left, rect.right - tb_width - 4)

        # Vertically align with the top of the scrcpy window content
        y = rect.top + 28
        if y + tb_height > screen_h - 40:
            y = max(10, screen_h - tb_height - 40)
        if y < 10:
            y = 10

        self.geometry(f"+{x}+{y}")

    def _on_snap_window(self):
        """Snap toolbar back to the right edge of the scrcpy window."""
        self._following = True
        self._last_rect = None
        if self.scrcpy_hwnd:
            rect = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(self.scrcpy_hwnd, ctypes.byref(rect))
            self._position_over_scrcpy(rect)

    def _on_toggle_pin(self):
        """Toggle always-on-top for both scrcpy and this toolbar."""
        self._is_pinned = not self._is_pinned
        self.attributes("-topmost", self._is_pinned)

        if self.scrcpy_hwnd:
            pos = HWND_TOPMOST if self._is_pinned else HWND_NOTOPMOST
            ctypes.windll.user32.SetWindowPos(
                self.scrcpy_hwnd, pos, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

        pin_btn = self.btn_widgets.get("📌")
        if pin_btn:
            pin_btn.config(background="#0e639c" if self._is_pinned else "#252525")
