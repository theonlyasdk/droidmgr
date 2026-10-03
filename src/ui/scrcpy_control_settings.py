"""Keyboard/mouse control settings for the scrcpy settings dialog."""

import tkinter as tk
from tkinter import ttk


class ControlSettingsMixin:
    def _create_control_settings(self):
        self.control_tab.columnconfigure(1, weight=1)
        row = 0
        # Mouse Mode
        ttk.Label(self.control_tab, text="Mouse Mode:").grid(row=row, column=0, sticky='w', pady=5)
        self.mouse_mode_var = tk.StringVar(value=self.config.get('scrcpy', 'mouse_mode', 'sdk'))
        self.mouse_mode_cb = ttk.Combobox(self.control_tab, textvariable=self.mouse_mode_var, values=['sdk', 'uhid', 'aoa', 'disabled'], state='readonly')
        self.mouse_mode_cb.grid(row=row, column=1, sticky='ew', pady=5, padx=5)
        self._add_tooltip(self.mouse_mode_cb, "Select mouse input method. 'uhid' and 'aoa' simulate a physical mouse.")
        row += 1

        # Keyboard Mode
        ttk.Label(self.control_tab, text="Keyboard Mode:").grid(row=row, column=0, sticky='w', pady=5)
        self.keyboard_mode_var = tk.StringVar(value=self.config.get('scrcpy', 'keyboard_mode', 'sdk'))
        self.keyboard_mode_cb = ttk.Combobox(self.control_tab, textvariable=self.keyboard_mode_var, values=['sdk', 'uhid', 'aoa', 'disabled'], state='readonly')
        self.keyboard_mode_cb.grid(row=row, column=1, sticky='ew', pady=5, padx=5)
        self._add_tooltip(self.keyboard_mode_cb, "Select keyboard input method. 'uhid' and 'aoa' simulate a physical keyboard.")
        row += 1

        # Checkboxes
        check_frame = ttk.Frame(self.control_tab)
        check_frame.grid(row=row, column=0, columnspan=2, sticky='ew', pady=10)
        
        self.no_control_var = tk.BooleanVar(value=self.config.get('scrcpy', 'no_control', False))
        c1 = ttk.Checkbutton(check_frame, text="Read-only mode (No control)", variable=self.no_control_var)
        c1.pack(anchor='w', pady=2)
        self._add_tooltip(c1, "Disable device control (mirror only).")
        
        self.no_clipboard_autosync_var = tk.BooleanVar(value=self.config.get('scrcpy', 'no_clipboard_autosync', False))
        c2 = ttk.Checkbutton(check_frame, text="Disable Clipboard Autosync", variable=self.no_clipboard_autosync_var)
        c2.pack(anchor='w', pady=2)
        self._add_tooltip(c2, "Disable automatic clipboard synchronization between computer and device.")
        
        self.no_key_repeat_var = tk.BooleanVar(value=self.config.get('scrcpy', 'no_key_repeat', False))
        c3 = ttk.Checkbutton(check_frame, text="Disable Key Repeat", variable=self.no_key_repeat_var)
        c3.pack(anchor='w', pady=2)
        self._add_tooltip(c3, "Do not forward repeated key events when a key is held down.")
        
        self.no_mouse_hover_var = tk.BooleanVar(value=self.config.get('scrcpy', 'no_mouse_hover', False))
        c4 = ttk.Checkbutton(check_frame, text="Disable Mouse Hover", variable=self.no_mouse_hover_var)
        c4.pack(anchor='w', pady=2)
        self._add_tooltip(c4, "Do not forward mouse hover (motion without clicks) events.")
        
        self.no_power_on_var = tk.BooleanVar(value=self.config.get('scrcpy', 'no_power_on', False))
        c5 = ttk.Checkbutton(check_frame, text="Do Not Power On on Start", variable=self.no_power_on_var)
        c5.pack(anchor='w', pady=2)
        self._add_tooltip(c5, "Do not power on the device screen when scrcpy starts.")
        
        self.otg_var = tk.BooleanVar(value=self.config.get('scrcpy', 'otg', False))
        c6 = ttk.Checkbutton(check_frame, text="OTG Mode", variable=self.otg_var)
        c6.pack(anchor='w', pady=2)
        self._add_tooltip(c6, "Simulate physical HID devices. Requires USB and often no ADB.")
