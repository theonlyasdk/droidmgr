"""Window behaviour and recording settings for the scrcpy settings dialog."""

import tkinter as tk
from tkinter import filedialog, ttk


class WindowSettingsMixin:
    def _create_window_settings(self):
        self.window_tab.columnconfigure(1, weight=1)
        row = 0
        ttk.Label(self.window_tab, text="Window Title:").grid(row=row, column=0, sticky='w', pady=5)
        self.window_title_var = tk.StringVar(value=self.config.get('scrcpy', 'window_title', 'Droidmgr Mirroring'))
        title_ent = ttk.Entry(self.window_tab, textvariable=self.window_title_var)
        title_ent.grid(row=row, column=1, sticky='ew', pady=5, padx=5)
        self._add_tooltip(title_ent, "Custom title for the mirroring window.")
        row += 1
        
        # Angle
        ttk.Label(self.window_tab, text="Angle (0-360):").grid(row=row, column=0, sticky='w', pady=5)
        self.angle_var = tk.StringVar(value=str(self.config.get('scrcpy', 'angle', 0)))
        angle_spin = ttk.Spinbox(self.window_tab, from_=0, to=360, textvariable=self.angle_var)
        angle_spin.grid(row=row, column=1, sticky='ew', pady=5, padx=5)
        self._add_tooltip(angle_spin, "Set the rotation angle in degrees.")
        row += 1

        check_frame = ttk.Frame(self.window_tab)
        check_frame.grid(row=row, column=0, columnspan=2, sticky='ew', pady=10)

        checks = [
            ("Fullscreen", "fullscreen", "Start scrcpy in fullscreen mode."),
            ("Always on Top", "always_on_top", "Keep the scrcpy window always on top."),
            ("Borderless Window", "window_borderless", "Remove window decorations."),
            ("Stay Awake", "stay_awake", "Prevent the device from sleeping."),
            ("Turn off device screen", "turn_screen_off", "Turn off the hardware screen during mirroring."),
            ("Show physical touches", "show_touches", "Visually highlight touches on the screen."),
            ("Power off device on close", "power_off_on_close", "Power off the device when scrcpy is closed."),
            ("Print FPS in logs", "print_fps", "Log the frame rate to the console.")
        ]
        
        self.check_vars = {}
        for text, key, tooltip in checks:
            var = tk.BooleanVar(value=self.config.get('scrcpy', key, False))
            self.check_vars[key] = var
            cb = ttk.Checkbutton(check_frame, text=text, variable=var)
            cb.pack(anchor='w', pady=2)
            self._add_tooltip(cb, tooltip)

        row += 1

        # Recording
        rec_frame = ttk.LabelFrame(self.window_tab, text="Recording", padding=10)
        rec_frame.grid(row=row, column=0, columnspan=2, sticky='ew', pady=10)
        rec_frame.columnconfigure(0, weight=1)
        
        self.record_var = tk.BooleanVar(value=self.config.get('scrcpy', 'record', False))
        cr = ttk.Checkbutton(rec_frame, text="Record to file", variable=self.record_var, command=self._toggle_record_settings)
        cr.grid(row=0, column=0, sticky='w')
        
        path_frame = ttk.Frame(rec_frame)
        path_frame.grid(row=1, column=0, sticky='ew', pady=5)
        path_frame.columnconfigure(0, weight=1)
        
        self.record_path_var = tk.StringVar(value=self.config.get('scrcpy', 'record_path', ''))
        self.record_path_ent = ttk.Entry(path_frame, textvariable=self.record_path_var)
        self.record_path_ent.grid(row=0, column=0, sticky='ew')
        
        # Placeholder logic
        self.placeholder = "e.g. /path/to/recording.mp4"
        self.record_path_ent.bind("<FocusIn>", self._on_path_focus_in)
        self.record_path_ent.bind("<FocusOut>", self._on_path_focus_out)
        self._on_path_focus_out(None) # Initial state

        self.record_browse_btn = ttk.Button(path_frame, text="Browse...", width=10, command=self._browse_record_path)
        self.record_browse_btn.grid(row=0, column=1, padx=(5, 0))

    def _on_path_focus_in(self, event):
        if self.record_path_var.get() == self.placeholder:
            self.record_path_var.set("")
            self.record_path_ent.config(foreground='black')

    def _on_path_focus_out(self, event):
        if not self.record_path_var.get():
            self.record_path_var.set(self.placeholder)
            self.record_path_ent.config(foreground='gray')

    def _toggle_record_settings(self):
        state = tk.NORMAL if self.record_var.get() else tk.DISABLED
        self.record_path_ent.config(state=state)
        self.record_browse_btn.config(state=state)

    def _browse_record_path(self):
        filename = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[("MP4 Video", "*.mp4"), ("MKV Video", "*.mkv"), ("All Files", "*.*")]
        )
        if filename:
            self.record_path_var.set(filename)
            self.record_var.set(True)
            self.record_path_ent.config(foreground='black')
