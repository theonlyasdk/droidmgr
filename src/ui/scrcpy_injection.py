"""UHID keyboard injection with ADB fallback for the overlay toolbar."""

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Optional

from .scrcpy_keys import KEYEVENTF_KEYUP, VK_LMENU


class ScrcpyInjectionMixin:
    """Key/mouse injection methods for ScrcpyOverlayToolbar."""


    # --- Actions: UHID Scrcpy Injection + ADB Fallback ----------------------

    def _run_async(self, fn, *args):
        threading.Thread(target=fn, args=args, daemon=True).start()

    def _send_scrcpy_shortcut(
        self,
        vk_key: int,
        use_alt: bool = True,
        extra_vk: Optional[int] = None
    ) -> bool:
        """Send a real hardware keyboard shortcut into the scrcpy SDL window for UHID mode."""
        hwnd = self.scrcpy_hwnd
        user32 = ctypes.windll.user32

        if not hwnd or not user32.IsWindow(hwnd):
            hwnd = self._find_scrcpy_hwnd()
            if hwnd:
                self.scrcpy_hwnd = hwnd

        if not hwnd or not user32.IsWindow(hwnd):
            return False

        kernel32 = ctypes.windll.kernel32
        cur_thread = kernel32.GetCurrentThreadId()
        fg_hwnd = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)

        try:
            if target_thread and cur_thread != target_thread:
                user32.AttachThreadInput(cur_thread, target_thread, True)
            if fg_thread and fg_thread != target_thread:
                user32.AttachThreadInput(fg_thread, target_thread, True)

            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd)
        except Exception:
            pass

        time.sleep(0.02)

        try:
            if use_alt:
                user32.keybd_event(VK_LMENU, 0, 0, 0)
                time.sleep(0.02)

            user32.keybd_event(vk_key, 0, 0, 0)
            time.sleep(0.03)
            user32.keybd_event(vk_key, 0, KEYEVENTF_KEYUP, 0)

            if use_alt:
                time.sleep(0.02)
                user32.keybd_event(VK_LMENU, 0, KEYEVENTF_KEYUP, 0)

            if extra_vk:
                time.sleep(0.03)
                user32.keybd_event(extra_vk, 0, 0, 0)
                time.sleep(0.03)
                user32.keybd_event(extra_vk, 0, KEYEVENTF_KEYUP, 0)

            # Backup SDL message post
            WM_KEYDOWN = 0x0100
            WM_KEYUP = 0x0101
            WM_SYSKEYDOWN = 0x0104
            WM_SYSKEYUP = 0x0105
            msg_down = WM_SYSKEYDOWN if use_alt else WM_KEYDOWN
            msg_up = WM_SYSKEYUP if use_alt else WM_KEYUP
            lParam = 0x20000001 if use_alt else 0x00000001
            user32.PostMessageW(hwnd, msg_down, vk_key, lParam)
            user32.PostMessageW(hwnd, msg_up, vk_key, lParam)
            return True
        except Exception:
            return False
        finally:
            try:
                if target_thread and cur_thread != target_thread:
                    user32.AttachThreadInput(cur_thread, target_thread, False)
                if fg_thread and fg_thread != target_thread:
                    user32.AttachThreadInput(fg_thread, target_thread, False)
            except Exception:
                pass

    def _post_mouse_click(self, right: bool = False, middle: bool = False):
        """Send simulated right/middle click to scrcpy SDL window."""
        hwnd = self.scrcpy_hwnd
        if not hwnd or not ctypes.windll.user32.IsWindow(hwnd):
            return
        try:
            user32 = ctypes.windll.user32
            rect = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rect))
            cx = (rect.right - rect.left) // 2
            cy = (rect.bottom - rect.top) // 2
            lParam = (cy << 16) | (cx & 0xFFFF)
            if right:
                user32.PostMessageW(hwnd, 0x0204, 0x0002, lParam)  # WM_RBUTTONDOWN
                time.sleep(0.04)
                user32.PostMessageW(hwnd, 0x0205, 0, lParam)       # WM_RBUTTONUP
            elif middle:
                user32.PostMessageW(hwnd, 0x0207, 0x0010, lParam)  # WM_MBUTTONDOWN
                time.sleep(0.04)
                user32.PostMessageW(hwnd, 0x0208, 0, lParam)       # WM_MBUTTONUP
        except Exception:
            pass

    def _send_key(
        self,
        keycode: int,
        vk_shortcut: Optional[int] = None,
        use_alt: bool = True,
        extra_vk: Optional[int] = None,
        mouse_action: Optional[str] = None
    ):
        """Dispatch control action via Scrcpy UHID keyboard injection with ADB fallback."""
        def task():
            # 1. Primary: UHID hardware key injection via scrcpy window
            if vk_shortcut:
                self._send_scrcpy_shortcut(vk_shortcut, use_alt=use_alt, extra_vk=extra_vk)

            if mouse_action == "right":
                self._post_mouse_click(right=True)
            elif mouse_action == "middle":
                self._post_mouse_click(middle=True)

            # 2. Companion/Fallback: ADB keyevent
            dev_id = self._get_device_id()
            if dev_id and self.device_manager:
                try:
                    self.device_manager.send_keyevent(dev_id, keycode)
                except Exception:
                    try:
                        self.device_manager.adb._run_command(
                            ['shell', 'input', 'keyevent', str(keycode)],
                            device_id=dev_id,
                            timeout=6
                        )
                    except Exception:
                        pass

        self._run_async(task)
