"""One-click action handlers for the scrcpy overlay toolbar."""

import tkinter as tk
from tkinter import ttk, messagebox

from .scrcpy_keys import (
    KEYCODE_APP_SWITCH,
    KEYCODE_BACK,
    KEYCODE_HOME,
    KEYCODE_PASTE,
    KEYCODE_POWER,
    KEYCODE_VOLUME_DOWN,
    KEYCODE_VOLUME_UP,
    KEYCODE_WAKEUP,
    VK_B,
    VK_DOWN,
    VK_ESCAPE,
    VK_H,
    VK_HOME,
    VK_P,
    VK_R,
    VK_S,
    VK_UP,
    VK_V,
)


class ScrcpyActionsMixin:
    """Button action methods for ScrcpyOverlayToolbar."""


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
