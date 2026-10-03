"""Developer Options tab for droidmgr."""

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict, Optional
from .misc_cards import MiscCardsMixin
from .misc_users import MiscUsersMixin


__all__ = [
    'MiscTab',
]


class MiscTab(MiscCardsMixin, MiscUsersMixin, ttk.Frame):
    def __init__(self, parent, device_manager, get_selected_device_func, set_status_func=None):
        super().__init__(parent)
        self.device_manager = device_manager
        self.get_selected_device = get_selected_device_func
        self.set_status = set_status_func or (lambda msg: None)

        self._loading = False
        self._opts = {}

        # Form variables
        self.window_anim_var = tk.StringVar(value="1.0")
        self.trans_anim_var = tk.StringVar(value="1.0")
        self.animator_var = tk.StringVar(value="1.0")

        self.show_taps_var = tk.BooleanVar(value=False)
        self.pointer_loc_var = tk.BooleanVar(value=False)
        self.stay_awake_var = tk.BooleanVar(value=False)

        self.font_scale_var = tk.StringVar(value="1.0")
        self.density_var = tk.StringVar(value="")
        self.size_var = tk.StringVar(value="")

        self._build_ui()

    def _build_ui(self):
        # Header Toolbar
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=10, pady=(10, 5))

        ttk.Label(toolbar, text="Developer Options", font=('Segoe UI', 11, 'bold')).pack(side=tk.LEFT)

        self.status_lbl = ttk.Label(toolbar, text="", font=('Segoe UI', 9, 'italic'), foreground="#555555")
        self.status_lbl.pack(side=tk.LEFT, padx=15)

        self.refresh_btn = ttk.Button(toolbar, text="Refresh Status", command=self.refresh)
        self.refresh_btn.pack(side=tk.RIGHT)

        # Scrollable canvas container
        canvas_frame = ttk.Frame(self)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.canvas = tk.Canvas(canvas_frame, borderwidth=0, highlightthickness=0, bg="#ffffff")
        scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.scroll_content = ttk.Frame(self.canvas, padding=10)

        self.scroll_content.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scroll_content, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas.bind('<Configure>', self._on_canvas_configure)

        def _on_wheel(event):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.canvas.bind("<MouseWheel>", _on_wheel)

        self._build_cards()

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def set_device(self, device_id: Optional[str]):
        """Called when active device changes."""
        self.refresh()

    def refresh(self):
        device_id = self.get_selected_device()
        if not device_id or self._loading:
            return

        self._loading = True
        self.status_lbl.config(text="Querying device settings...")
        self.refresh_btn.config(state=tk.DISABLED)

        def bg_task():
            try:
                opts = self.device_manager.adb.get_dev_options(device_id)
                def update_ui():
                    self._loading = False
                    self.refresh_btn.config(state=tk.NORMAL)
                    if getattr(self, '_closing', False):
                        return
                    self._apply_opts_to_ui(opts)
                    self.status_lbl.config(text=f"Loaded from '{device_id}'")
                self.after(0, update_ui)
            except Exception:
                def handle_err():
                    self._loading = False
                    self.refresh_btn.config(state=tk.NORMAL)
                    self.status_lbl.config(text="Failed to query settings")
                self.after(0, handle_err)

        threading.Thread(target=bg_task, daemon=True).start()
        self._refresh_users()

    def _apply_opts_to_ui(self, opts: Dict[str, Any]):
        self._opts = opts
        self.window_anim_var.set(opts.get('window_animation_scale', '1.0'))
        self.trans_anim_var.set(opts.get('transition_animation_scale', '1.0'))
        self.animator_var.set(opts.get('animator_duration_scale', '1.0'))

        self.show_taps_var.set(opts.get('show_touches', False))
        self.pointer_loc_var.set(opts.get('pointer_location', False))
        self.stay_awake_var.set(opts.get('stay_awake', False))

        self.font_scale_var.set(opts.get('font_scale', '1.0'))

        density_curr = opts.get('density_override') or opts.get('density') or ''
        self.density_var.set(density_curr)
        if opts.get('density_override'):
            self.density_lbl.config(text=f"(Physical: {opts.get('density')}, Override: {opts.get('density_override')})")
        else:
            self.density_lbl.config(text=f"(Physical: {opts.get('density')})")

        size_curr = opts.get('size_override') or opts.get('size') or ''
        self.size_var.set(size_curr)
        if opts.get('size_override'):
            self.size_lbl.config(text=f"(Physical: {opts.get('size')}, Override: {opts.get('size_override')})")
        else:
            self.size_lbl.config(text=f"(Physical: {opts.get('size')})")

    def _apply_all_animations(self, value: str):
        self.window_anim_var.set(value)
        self.trans_anim_var.set(value)
        self.animator_var.set(value)
        self._apply_option('all_animation_scales', value)

    def _apply_font_scale(self, value: str):
        self.font_scale_var.set(value)
        self._apply_option('font_scale', value)

    def _apply_density(self):
        val = self.density_var.get().strip()
        if not val:
            return
        self._apply_option('density', val)

    def _apply_size(self):
        val = self.size_var.get().strip()
        if not val:
            return
        self._apply_option('size', val)

    def _apply_option(self, key: str, value: Any):
        device_id = self.get_selected_device()
        if not device_id:
            messagebox.showwarning("No Device Selected", "Please select a connected device first.", parent=self)
            return

        self.status_lbl.config(text=f"Applying '{key}'...")
        def bg_task():
            ok, msg = self.device_manager.adb.set_dev_option(device_id, key, value)
            def update_ui():
                if ok:
                    self.set_status(f"Applied '{key}' -> {value} on {device_id}")
                    self.status_lbl.config(text=f"Applied: {key} -> {value}")
                    self.after(400, self.refresh)
                else:
                    self.set_status(f"Failed to set '{key}': {msg}")
                    self.status_lbl.config(text="Permission / Command Error")
                    messagebox.showerror(
                        "Setting Change Error",
                        f"Failed to apply setting on device:\n\n{msg}",
                        parent=self
                    )
            self.after(0, update_ui)

        threading.Thread(target=bg_task, daemon=True).start()
