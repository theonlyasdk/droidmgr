"""Misc tab for Developer Options and Quick Toggles for QA engineers."""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import os
from typing import Optional, Dict, Any


class MiscTab(ttk.Frame):
    """Tab containing developer options, animation scales, font/display density, and quick toggles."""

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

        ttk.Label(toolbar, text="Developer Options & QA Quick Toggles", font=('Segoe UI', 11, 'bold')).pack(side=tk.LEFT)

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

    def _build_cards(self):
        # 1. Animation Scales Card
        anim_card = ttk.LabelFrame(self.scroll_content, text=" Animation Scales", padding=12)
        anim_card.pack(fill=tk.X, expand=True, pady=(0, 10))

        preset_frame = ttk.Frame(anim_card)
        preset_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(preset_frame, text="Quick Presets (All):", font=('Segoe UI', 9, 'bold')).pack(side=tk.LEFT, padx=(0, 8))

        presets = [("Off (0x)", "0.0"), ("0.5x", "0.5"), ("1.0x (Default)", "1.0"), ("1.5x", "1.5"), ("2.0x", "2.0"), ("5.0x", "5.0")]
        for label, val in presets:
            ttk.Button(preset_frame, text=label, command=lambda v=val: self._apply_all_animations(v)).pack(side=tk.LEFT, padx=2)

        anim_grid = ttk.Frame(anim_card)
        anim_grid.pack(fill=tk.X)
        anim_grid.columnconfigure(1, weight=1)

        anim_options = ["0.0", "0.5", "1.0", "1.5", "2.0", "5.0", "10.0"]

        ttk.Label(anim_grid, text="Window Animation Scale:").grid(row=0, column=0, sticky='w', pady=4)
        self.win_anim_combo = ttk.Combobox(anim_grid, textvariable=self.window_anim_var, values=anim_options, width=10, state="readonly")
        self.win_anim_combo.grid(row=0, column=1, sticky='w', padx=10, pady=4)
        self.win_anim_combo.bind("<<ComboboxSelected>>", lambda _: self._apply_option('window_animation_scale', self.window_anim_var.get()))

        ttk.Label(anim_grid, text="Transition Animation Scale:").grid(row=1, column=0, sticky='w', pady=4)
        self.trans_anim_combo = ttk.Combobox(anim_grid, textvariable=self.trans_anim_var, values=anim_options, width=10, state="readonly")
        self.trans_anim_combo.grid(row=1, column=1, sticky='w', padx=10, pady=4)
        self.trans_anim_combo.bind("<<ComboboxSelected>>", lambda _: self._apply_option('transition_animation_scale', self.trans_anim_var.get()))

        ttk.Label(anim_grid, text="Animator Duration Scale:").grid(row=2, column=0, sticky='w', pady=4)
        self.animator_combo = ttk.Combobox(anim_grid, textvariable=self.animator_var, values=anim_options, width=10, state="readonly")
        self.animator_combo.grid(row=2, column=1, sticky='w', padx=10, pady=4)
        self.animator_combo.bind("<<ComboboxSelected>>", lambda _: self._apply_option('animator_duration_scale', self.animator_var.get()))

        # 2. System Toggles Card (Taps, Pointer, Stay Awake)
        toggles_card = ttk.LabelFrame(self.scroll_content, text=" System Toggles (QA)", padding=12)
        toggles_card.pack(fill=tk.X, expand=True, pady=(0, 10))

        ttk.Checkbutton(
            toggles_card, text="Show Taps / Touches (show_touches)",
            variable=self.show_taps_var,
            command=lambda: self._apply_option('show_touches', self.show_taps_var.get())
        ).pack(anchor='w', pady=3)

        ttk.Checkbutton(
            toggles_card, text="Pointer Location Overlay (pointer_location)",
            variable=self.pointer_loc_var,
            command=lambda: self._apply_option('pointer_location', self.pointer_loc_var.get())
        ).pack(anchor='w', pady=3)

        ttk.Checkbutton(
            toggles_card, text="Stay Awake While Charging (stay_on_while_plugged_in)",
            variable=self.stay_awake_var,
            command=lambda: self._apply_option('stay_awake', self.stay_awake_var.get())
        ).pack(anchor='w', pady=3)

        # 3. Dark Mode / Theme Card
        theme_card = ttk.LabelFrame(self.scroll_content, text=" Theme / Night Mode", padding=12)
        theme_card.pack(fill=tk.X, expand=True, pady=(0, 10))

        theme_frame = ttk.Frame(theme_card)
        theme_frame.pack(fill=tk.X)
        ttk.Label(theme_frame, text="Dark Mode:", font=('Segoe UI', 9, 'bold')).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(theme_frame, text="Light (Day)", command=lambda: self._apply_option('night_mode', 'light')).pack(side=tk.LEFT, padx=3)
        ttk.Button(theme_frame, text="Dark (Night)", command=lambda: self._apply_option('night_mode', 'dark')).pack(side=tk.LEFT, padx=3)
        ttk.Button(theme_frame, text="Auto (System)", command=lambda: self._apply_option('night_mode', 'auto')).pack(side=tk.LEFT, padx=3)

        # 4. Display Density & Font Scale Card
        display_card = ttk.LabelFrame(self.scroll_content, text=" Display & Font Density", padding=12)
        display_card.pack(fill=tk.X, expand=True, pady=(0, 10))

        # Font Scale
        font_frame = ttk.Frame(display_card)
        font_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(font_frame, text="Font Scale:", font=('Segoe UI', 9, 'bold'), width=14).pack(side=tk.LEFT)

        font_presets = [("Small (0.85)", "0.85"), ("Default (1.0)", "1.0"), ("Large (1.15)", "1.15"), ("Largest (1.30)", "1.30")]
        for label, val in font_presets:
            ttk.Button(font_frame, text=label, command=lambda v=val: self._apply_font_scale(v)).pack(side=tk.LEFT, padx=2)

        font_custom = ttk.Frame(display_card)
        font_custom.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(font_custom, text="Custom Font Scale:", width=18).pack(side=tk.LEFT)
        ttk.Entry(font_custom, textvariable=self.font_scale_var, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(font_custom, text="Apply Font Scale", command=lambda: self._apply_font_scale(self.font_scale_var.get())).pack(side=tk.LEFT, padx=5)

        # Display Density (DPI)
        density_frame = ttk.Frame(display_card)
        density_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(density_frame, text="Display Density (wm density):", width=26).pack(side=tk.LEFT)
        ttk.Entry(density_frame, textvariable=self.density_var, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(density_frame, text="Apply Density", command=self._apply_density).pack(side=tk.LEFT, padx=2)
        ttk.Button(density_frame, text="Reset Default", command=lambda: self._apply_option('density', 'reset')).pack(side=tk.LEFT, padx=2)
        self.density_lbl = ttk.Label(density_frame, text="", font=('Segoe UI', 8, 'italic'), foreground="#666666")
        self.density_lbl.pack(side=tk.LEFT, padx=10)

        # Display Size (Resolution)
        size_frame = ttk.Frame(display_card)
        size_frame.pack(fill=tk.X)
        ttk.Label(size_frame, text="Display Size (wm size):", width=26).pack(side=tk.LEFT)
        ttk.Entry(size_frame, textvariable=self.size_var, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(size_frame, text="Apply Size", command=self._apply_size).pack(side=tk.LEFT, padx=2)
        ttk.Button(size_frame, text="Reset Default", command=lambda: self._apply_option('size', 'reset')).pack(side=tk.LEFT, padx=2)
        self.size_lbl = ttk.Label(size_frame, text="", font=('Segoe UI', 8, 'italic'), foreground="#666666")
        self.size_lbl.pack(side=tk.LEFT, padx=10)

        # 5. Multi-User Manager Card
        user_card = ttk.LabelFrame(self.scroll_content, text=" Multi-User Manager (Personal / Work / Guest)", padding=12)
        user_card.pack(fill=tk.X, expand=True, pady=(0, 10))

        user_toolbar = ttk.Frame(user_card)
        user_toolbar.pack(fill=tk.X, pady=(0, 6))

        ttk.Button(user_toolbar, text="Switch to Selected User", command=self._switch_selected_user).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(user_toolbar, text="Create User...", command=self._show_create_user_dialog).pack(side=tk.LEFT, padx=4)
        ttk.Button(user_toolbar, text="Remove User", command=self._remove_selected_user).pack(side=tk.LEFT, padx=4)
        ttk.Button(user_toolbar, text="Refresh Users", command=self._refresh_users).pack(side=tk.RIGHT)

        tree_frame = ttk.Frame(user_card)
        tree_frame.pack(fill=tk.X, expand=True)

        cols = ('id', 'name', 'status', 'flags')
        self.user_tree = ttk.Treeview(tree_frame, columns=cols, show='headings', height=4, selectmode='browse')
        self.user_tree.heading('id', text='User ID')
        self.user_tree.heading('name', text='Name')
        self.user_tree.heading('status', text='Status')
        self.user_tree.heading('flags', text='Flags')

        self.user_tree.column('id', width=70, stretch=False)
        self.user_tree.column('name', width=160)
        self.user_tree.column('status', width=140)
        self.user_tree.column('flags', width=90)

        user_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.user_tree.yview)
        self.user_tree.configure(yscrollcommand=user_scroll.set)
        self.user_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        user_scroll.pack(side=tk.RIGHT, fill=tk.Y)

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

    def _refresh_users(self):
        device_id = self.get_selected_device()
        if not device_id:
            for item in self.user_tree.get_children():
                self.user_tree.delete(item)
            return

        def bg_task():
            try:
                users = self.device_manager.adb.get_users(device_id)
                def update_ui():
                    if getattr(self, '_closing', False):
                        return
                    for item in self.user_tree.get_children():
                        self.user_tree.delete(item)
                    for u in users:
                        status_parts = []
                        if u.get('current'):
                            status_parts.append("ACTIVE / CURRENT")
                        elif u.get('running'):
                            status_parts.append("Running")
                        else:
                            status_parts.append("Stopped")
                        status_str = " | ".join(status_parts)
                        self.user_tree.insert('', tk.END, iid=u['id'], values=(u['id'], u['name'], status_str, u.get('flags', '')))
                self.after(0, update_ui)
            except Exception:
                pass

        threading.Thread(target=bg_task, daemon=True).start()

    def _switch_selected_user(self):
        sel = self.user_tree.selection()
        if not sel:
            messagebox.showinfo("Switch User", "Please select a user profile to switch to.", parent=self)
            return
        user_id = sel[0]
        device_id = self.get_selected_device()
        if not device_id:
            return

        self.status_lbl.config(text=f"Switching to user {user_id}...")
        def bg_task():
            ok, msg = self.device_manager.adb.switch_user(device_id, user_id)
            def update_ui():
                if ok:
                    self.set_status(f"Switched to user {user_id}")
                    self.status_lbl.config(text=f"Switched to user {user_id}")
                    self.after(1000, self._refresh_users)
                else:
                    messagebox.showerror("Switch User Failed", msg, parent=self)
            self.after(0, update_ui)
        threading.Thread(target=bg_task, daemon=True).start()

    def _show_create_user_dialog(self):
        device_id = self.get_selected_device()
        if not device_id:
            messagebox.showwarning("No Device", "Please select a connected device.", parent=self)
            return

        dlg = tk.Toplevel(self)
        dlg.title("Create User Profile")
        dlg.transient(self)
        dlg.resizable(False, False)
        dlg.grab_set()

        frame = ttk.Frame(dlg, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="User / Profile Name:").grid(row=0, column=0, sticky='w', pady=4)
        name_var = tk.StringVar(value="TestUser")
        ttk.Entry(frame, textvariable=name_var, width=24).grid(row=0, column=1, sticky='w', padx=6, pady=4)

        ttk.Label(frame, text="Profile Type:").grid(row=1, column=0, sticky='w', pady=4)
        type_var = tk.StringVar(value="Standard User")
        type_combo = ttk.Combobox(frame, textvariable=type_var, values=["Standard User", "Guest", "Managed (Work Profile)"], state="readonly", width=22)
        type_combo.grid(row=1, column=1, sticky='w', padx=6, pady=4)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=2, column=0, columnspan=2, pady=(12, 0), sticky='e')

        def on_create():
            u_name = name_var.get().strip()
            if not u_name:
                messagebox.showwarning("Empty Name", "Please enter a user name.", parent=dlg)
                return
            t_sel = type_var.get()
            u_type = 'standard'
            if 'Guest' in t_sel:
                u_type = 'guest'
            elif 'Work' in t_sel or 'Managed' in t_sel:
                u_type = 'managed'
            dlg.destroy()

            self.status_lbl.config(text=f"Creating user '{u_name}'...")
            def bg_task():
                ok, msg = self.device_manager.adb.create_user(device_id, u_name, u_type)
                def on_done():
                    if ok:
                        self.set_status(f"Created user: {u_name}")
                        self.status_lbl.config(text=f"Created user '{u_name}'")
                        self._refresh_users()
                    else:
                        messagebox.showerror("Create User Failed", msg, parent=self)
                self.after(0, on_done)
            threading.Thread(target=bg_task, daemon=True).start()

        ttk.Button(btn_row, text="Create", command=on_create).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_row, text="Cancel", command=dlg.destroy).pack(side=tk.RIGHT, padx=4)

    def _remove_selected_user(self):
        sel = self.user_tree.selection()
        if not sel:
            messagebox.showinfo("Remove User", "Please select a user profile to remove.", parent=self)
            return
        user_id = sel[0]
        if str(user_id) == '0':
            messagebox.showwarning("Cannot Remove Owner", "User 0 is the primary device owner and cannot be removed.", parent=self)
            return

        device_id = self.get_selected_device()
        if not device_id:
            return

        if not messagebox.askyesno("Confirm Removal", f"Are you sure you want to remove user {user_id} and all its data?", parent=self):
            return

        self.status_lbl.config(text=f"Removing user {user_id}...")
        def bg_task():
            ok, msg = self.device_manager.adb.remove_user(device_id, user_id)
            def update_ui():
                if ok:
                    self.set_status(f"Removed user {user_id}")
                    self.status_lbl.config(text=f"Removed user {user_id}")
                    self._refresh_users()
                else:
                    messagebox.showerror("Remove User Failed", msg, parent=self)
            self.after(0, update_ui)
        threading.Thread(target=bg_task, daemon=True).start()

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
