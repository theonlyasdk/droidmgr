"""Overlay navigation and control toolbar for scrcpy screen mirroring sessions.

Floats vertically along the right edge of the scrcpy mirror window, providing one-click controls for:
- Navigation: Power, Volume +/-, Back, Home, Recents, Lock/Wake
- Inputs: Quick text injection and clipboard sync
- Utilities: Display rotation, screenshot, screen recording, always-on-top pin
- Session: Settings and clean termination

Supports both Scrcpy UHID hardware key injection (for devices where SDK input injection
is blocked, such as Xiaomi/MIUI) and direct ADB input commands as fallback.
"""

import ctypes
from ctypes import wintypes
import os
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Callable, List, Dict, Any

# Android Keycodes
KEYCODE_HOME = 3
KEYCODE_BACK = 4
KEYCODE_VOLUME_UP = 24
KEYCODE_VOLUME_DOWN = 25
KEYCODE_POWER = 26
KEYCODE_APP_SWITCH = 187
KEYCODE_WAKEUP = 224
KEYCODE_SLEEP = 223
KEYCODE_PASTE = 279

# Win32 Virtual Key Codes
VK_LMENU = 0xA4       # Left Alt (Scrcpy MOD key)
VK_ESCAPE = 0x1B      # Escape (Scrcpy Back)
VK_HOME = 0x24        # Home (Scrcpy Home)
VK_UP = 0x26          # Up Arrow
VK_DOWN = 0x28        # Down Arrow
VK_B = 0x42           # B (MOD+b = Back)
VK_H = 0x48           # H (MOD+h = Home)
VK_P = 0x50           # P (MOD+p = Power)
VK_R = 0x52           # R (MOD+r = Rotate)
VK_S = 0x53           # S (MOD+s = Recents/App Switch)
VK_V = 0x56           # V (MOD+v = Paste computer clipboard)

KEYEVENTF_KEYUP = 0x0002

# Win32 Constants
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010


class _Tooltip:
    """Lightweight tooltip widget that floats to the left of the vertical toolbar."""

    def __init__(self, widget, text: str, side: str = "left"):
        self.widget = widget
        self.text = text
        self.side = side
        self.tip_window = None
        self.widget.bind("<Enter>", self.show)
        self.widget.bind("<Leave>", self.hide)

    def show(self, event=None):
        if self.tip_window or not self.text:
            return
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_attributes("-topmost", True)
        label = tk.Label(
            tw, text=self.text, justify=tk.LEFT,
            background="#252526", foreground="#e0e0e0",
            relief=tk.SOLID, borderwidth=1,
            font=("Segoe UI", 9), padx=8, pady=4
        )
        label.pack()
        tw.update_idletasks()

        tw_w = tw.winfo_reqwidth()
        tw_h = tw.winfo_reqheight()

        if self.side == "left":
            x = self.widget.winfo_rootx() - tw_w - 6
            y = self.widget.winfo_rooty() + (self.widget.winfo_height() - tw_h) // 2
        else:
            x = self.widget.winfo_rootx() + self.widget.winfo_width() + 6
            y = self.widget.winfo_rooty() + (self.widget.winfo_height() - tw_h) // 2

        if x < 0:
            x = 10
        if y < 0:
            y = 10
        tw.geometry(f"+{x}+{y}")

    def hide(self, event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


class ScrcpyOverlayToolbar(tk.Toplevel):
    """Vertical floating overlay control bar sticking to the right edge of scrcpy."""

    def __init__(
        self,
        parent: tk.Tk,
        process: subprocess.Popen,
        device_id: str,
        device_manager,
        stop_callback: Optional[Callable[[str], None]] = None,
        show_settings_callback: Optional[Callable[[], None]] = None,
        take_screenshot_callback: Optional[Callable[[], None]] = None,
        record_screen_callback: Optional[Callable[[], None]] = None,
        window_title: Optional[str] = None,
    ):
        super().__init__(parent)
        self.process = process
        self.device_id = device_id
        self.device_manager = device_manager
        self.stop_callback = stop_callback
        self.show_settings_callback = show_settings_callback
        self.take_screenshot_callback = take_screenshot_callback
        self.record_screen_callback = record_screen_callback
        self.target_window_title = window_title

        self.scrcpy_hwnd = None
        self._following = True
        self._is_pinned = False
        self._last_rect = None
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._is_alive = True

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.config(background="#1a1a1a", borderwidth=1, relief=tk.SOLID)

        self._create_widgets()
        self._bind_drag()

        # Start tracking thread / loop
        self.after(200, self._track_scrcpy_window)

    def _get_device_id(self) -> Optional[str]:
        if self.device_id:
            return self.device_id
        if self.device_manager:
            try:
                devs = self.device_manager.get_devices()
                if devs:
                    return devs[0].get('id')
            except Exception:
                pass
        return None

    def _create_widgets(self):
        container = tk.Frame(self, background="#1a1a1a")
        container.pack(fill=tk.BOTH, expand=True, padx=2, pady=4)

        # Drag grip handle at top
        grip = tk.Label(
            container, text="⋮", font=("Segoe UI", 11, "bold"),
            background="#1a1a1a", foreground="#777777", cursor="fleur"
        )
        grip.pack(side=tk.TOP, pady=(1, 3))
        self.grip = grip

        # Vertical Button definitions: (icon, command, tooltip, color)
        # Larger icon glyphs
        buttons = [
            ("⏻", self._on_power, "Power (Screen On/Off)", "#EF5350"),
            ("🔒", self._on_lock_wake, "Lock / Wake Device", "#FFA726"),
            ("🔊", self._on_vol_up, "Volume Up", "#eeeeee"),
            ("🔉", self._on_vol_down, "Volume Down", "#eeeeee"),
            ("---", None, None, None),
            ("◀", self._on_back, "Back (◁)", "#4FC3F7"),
            ("○", self._on_home, "Home (○)", "#81C784"),
            ("▢", self._on_recents, "Recents (▢)", "#FFD54F"),
            ("---", None, None, None),
            ("T", self._on_text_input, "Send Text / Clipboard", "#CE93D8"),
            ("🔄", self._on_rotate, "Rotate Screen", "#4DD0E1"),
            ("📷", self._on_screenshot, "Take Screenshot", "#66BB6A"),
            ("📹", self._on_record, "Record Screen", "#F06292"),
            ("---", None, None, None),
            ("📌", self._on_toggle_pin, "Always on Top (Pin)", "#FFB74D"),
            ("🧲", self._on_snap_window, "Snap to Right Edge", "#64B5F6"),
            ("⚙", self._on_settings, "Scrcpy Settings", "#B0BEC5"),
            ("---", None, None, None),
            ("✕", self._on_close, "Stop Mirroring", "#E57373"),
        ]

        self.btn_widgets = {}
        for icon, cmd, tip, fg in buttons:
            if icon == "---":
                sep = tk.Frame(container, height=1, background="#333333", width=32)
                sep.pack(side=tk.TOP, fill=tk.X, padx=4, pady=3)
                continue

            btn = tk.Button(
                container, text=icon, font=("Segoe UI", 12, "bold"),
                command=cmd, width=3, height=1, relief=tk.FLAT,
                background="#252525", foreground=fg or "#ffffff",
                activebackground="#0e639c", activeforeground="#ffffff",
                cursor="hand2", bd=0, padx=2, pady=2
            )
            btn.pack(side=tk.TOP, pady=1)
            self._add_hover(btn)
            if tip:
                _Tooltip(btn, tip, side="left")
            self.btn_widgets[icon] = btn

    def _add_hover(self, btn):
        orig_bg = btn.cget("background")
        btn.bind("<Enter>", lambda e: btn.config(background="#383838"))
        btn.bind("<Leave>", lambda e: btn.config(background=orig_bg))

    def _bind_drag(self):
        for widget in (self, self.grip):
            widget.bind("<Button-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._do_drag)

    def _start_drag(self, event):
        self._drag_start_x = event.x_root - self.winfo_x()
        self._drag_start_y = event.y_root - self.winfo_y()

    def _do_drag(self, event):
        self._following = False  # User manually positioned
        x = event.x_root - self._drag_start_x
        y = event.y_root - self._drag_start_y
        self.geometry(f"+{x}+{y}")

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

    def _on_power(self):
        # Scrcpy UHID: Alt+P toggles device screen
        self._send_key(KEYCODE_POWER, vk_shortcut=VK_P, use_alt=True)

    def _on_lock_wake(self):
        # Scrcpy UHID: Alt+P wakes or locks
        self._send_key(KEYCODE_WAKEUP, vk_shortcut=VK_P, use_alt=True)

    def _on_vol_down(self):
        # Scrcpy UHID: Alt+Down Arrow
        self._send_key(KEYCODE_VOLUME_DOWN, vk_shortcut=VK_DOWN, use_alt=True)

    def _on_vol_up(self):
        # Scrcpy UHID: Alt+Up Arrow
        self._send_key(KEYCODE_VOLUME_UP, vk_shortcut=VK_UP, use_alt=True)

    def _on_back(self):
        # Scrcpy UHID: Alt+B, Escape key, or Right Click
        self._send_key(KEYCODE_BACK, vk_shortcut=VK_B, use_alt=True, extra_vk=VK_ESCAPE, mouse_action="right")

    def _on_home(self):
        # Scrcpy UHID: Alt+H, Home key, or Middle Click
        self._send_key(KEYCODE_HOME, vk_shortcut=VK_H, use_alt=True, extra_vk=VK_HOME, mouse_action="middle")

    def _on_recents(self):
        # Scrcpy UHID: Alt+S
        self._send_key(KEYCODE_APP_SWITCH, vk_shortcut=VK_S, use_alt=True)

    def _on_rotate(self):
        def task():
            # Scrcpy UHID: Alt+R rotates display
            self._send_scrcpy_shortcut(VK_R, use_alt=True)
            dev_id = self._get_device_id()
            if dev_id and self.device_manager:
                try:
                    self.device_manager.rotate_display(dev_id)
                except Exception:
                    pass
        self._run_async(task)

    def _on_text_input(self):
        """Open text injection and clipboard sync dialog."""
        dlg = tk.Toplevel(self)
        dlg.title("Send Text to Device")
        dlg.geometry("380x160")
        dlg.attributes("-topmost", True)
        dlg.configure(background="#252526")

        lbl = tk.Label(
            dlg, text="Type text to type or paste on device:",
            background="#252526", foreground="#ffffff", font=("Segoe UI", 9)
        )
        lbl.pack(anchor="w", padx=12, pady=(12, 4))

        entry_var = tk.StringVar()
        entry = ttk.Entry(dlg, textvariable=entry_var, width=44)
        entry.pack(fill=tk.X, padx=12, pady=4)
        entry.focus_set()

        btn_row = tk.Frame(dlg, background="#252526")
        btn_row.pack(fill=tk.X, padx=12, pady=10)

        def do_send_keys():
            txt = entry_var.get()
            if txt:
                def task():
                    # Set clipboard in PC and trigger Alt+V in scrcpy for UHID paste
                    try:
                        self.clipboard_clear()
                        self.clipboard_append(txt)
                        self.update()
                        self._send_scrcpy_shortcut(VK_V, use_alt=True)
                    except Exception:
                        pass

                    dev_id = self._get_device_id()
                    if dev_id and self.device_manager:
                        try:
                            self.device_manager.send_text(dev_id, txt)
                        except Exception:
                            try:
                                escaped = txt.replace(' ', '%s').replace('&', '\\&').replace('"', '\\"').replace("'", "\\'")
                                self.device_manager.adb._run_command(['shell', 'input', 'text', escaped], dev_id)
                            except Exception:
                                pass
                self._run_async(task)
                dlg.destroy()

        def do_set_clip():
            txt = entry_var.get()
            if txt:
                def task():
                    try:
                        self.clipboard_clear()
                        self.clipboard_append(txt)
                        self.update()
                        self._send_scrcpy_shortcut(VK_V, use_alt=True)
                    except Exception:
                        pass

                    dev_id = self._get_device_id()
                    if dev_id and self.device_manager:
                        try:
                            self.device_manager.set_clipboard_text(dev_id, txt)
                            self._send_key(KEYCODE_PASTE, vk_shortcut=VK_V, use_alt=True)
                        except Exception:
                            pass
                self._run_async(task)
                dlg.destroy()

        def do_paste_pc():
            try:
                pc_clip = self.clipboard_get()
                if pc_clip:
                    def task():
                        # Scrcpy UHID Alt+V injects computer clipboard directly!
                        self._send_scrcpy_shortcut(VK_V, use_alt=True)
                        dev_id = self._get_device_id()
                        if dev_id and self.device_manager:
                            try:
                                self.device_manager.set_clipboard_text(dev_id, pc_clip)
                                self._send_key(KEYCODE_PASTE, vk_shortcut=VK_V, use_alt=True)
                            except Exception:
                                pass
                    self._run_async(task)
                    dlg.destroy()
            except Exception as e:
                messagebox.showerror("Clipboard Error", f"Could not read PC clipboard: {e}", parent=dlg)

        send_btn = ttk.Button(btn_row, text="Type Text", command=do_send_keys)
        send_btn.pack(side=tk.LEFT, padx=(0, 6))

        clip_btn = ttk.Button(btn_row, text="Paste via Clip", command=do_set_clip)
        clip_btn.pack(side=tk.LEFT, padx=(0, 6))

        pc_btn = ttk.Button(btn_row, text="Send PC Clipboard", command=do_paste_pc)
        pc_btn.pack(side=tk.LEFT)

        entry.bind("<Return>", lambda e: do_send_keys())
        dlg.bind("<Escape>", lambda e: dlg.destroy())

    def _on_screenshot(self):
        if self.take_screenshot_callback:
            self.take_screenshot_callback()

    def _on_record(self):
        if self.record_screen_callback:
            self.record_screen_callback()

    def _on_settings(self):
        if self.show_settings_callback:
            self.show_settings_callback()

    def _on_close(self):
        """Stop mirroring and close toolbar."""
        if self.stop_callback:
            dev_id = self._get_device_id()
            if dev_id:
                self.stop_callback(dev_id)
        self._close_toolbar()

    def _close_toolbar(self):
        self._is_alive = False
        try:
            self.destroy()
        except Exception:
            pass
