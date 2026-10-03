"""Settings cards (animations, toggles, theme, display) for the Developer Options tab."""

import tkinter as tk
from tkinter import ttk


class MiscCardsMixin:
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
        toggles_card = ttk.LabelFrame(self.scroll_content, text=" System Toggles", padding=12)
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

        # 4. Display Density & Font Scale Card (grid-aligned rows)
        display_card = ttk.LabelFrame(self.scroll_content, text=" Display & Font Density", padding=12)
        display_card.pack(fill=tk.X, expand=True, pady=(0, 10))

        disp = ttk.Frame(display_card)
        disp.pack(fill=tk.X)
        disp.columnconfigure(4, weight=1)

        # Row 0: font presets
        ttk.Label(disp, text="Font Scale:", font=('Segoe UI', 9, 'bold')).grid(row=0, column=0, sticky='w', pady=4)
        font_presets = ttk.Frame(disp)
        font_presets.grid(row=0, column=1, columnspan=4, sticky='w', padx=10, pady=4)
        for label, val in [("Small (0.85)", "0.85"), ("Default (1.0)", "1.0"),
                           ("Large (1.15)", "1.15"), ("Largest (1.30)", "1.30")]:
            ttk.Button(font_presets, text=label, command=lambda v=val: self._apply_font_scale(v)).pack(side=tk.LEFT, padx=2)

        # Row 1: custom font scale
        ttk.Label(disp, text="Custom Font Scale:").grid(row=1, column=0, sticky='w', pady=4)
        ttk.Entry(disp, textvariable=self.font_scale_var, width=14).grid(row=1, column=1, sticky='w', padx=10, pady=4)
        ttk.Button(disp, text="Apply Font Scale", command=lambda: self._apply_font_scale(self.font_scale_var.get())).grid(row=1, column=2, sticky='w', padx=2, pady=4)

        ttk.Separator(display_card, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        # Rows 2-3: density and size share entry/button columns so they line up
        disp2 = ttk.Frame(display_card)
        disp2.pack(fill=tk.X)
        disp2.columnconfigure(4, weight=1)

        ttk.Label(disp2, text="Display Density (wm density):").grid(row=0, column=0, sticky='w', pady=4)
        ttk.Entry(disp2, textvariable=self.density_var, width=20).grid(row=0, column=1, sticky='w', padx=10, pady=4)
        ttk.Button(disp2, text="Apply Density", command=self._apply_density).grid(row=0, column=2, sticky='w', padx=2, pady=4)
        ttk.Button(disp2, text="Reset Default", command=lambda: self._apply_option('density', 'reset')).grid(row=0, column=3, sticky='w', padx=2, pady=4)
        self.density_lbl = ttk.Label(disp2, text="", font=('Segoe UI', 8, 'italic'), foreground="#666666")
        self.density_lbl.grid(row=0, column=4, sticky='w', padx=10, pady=4)

        ttk.Label(disp2, text="Display Size (wm size):").grid(row=1, column=0, sticky='w', pady=4)
        ttk.Entry(disp2, textvariable=self.size_var, width=20).grid(row=1, column=1, sticky='w', padx=10, pady=4)
        ttk.Button(disp2, text="Apply Size", command=self._apply_size).grid(row=1, column=2, sticky='w', padx=2, pady=4)
        ttk.Button(disp2, text="Reset Default", command=lambda: self._apply_option('size', 'reset')).grid(row=1, column=3, sticky='w', padx=2, pady=4)
        self.size_lbl = ttk.Label(disp2, text="", font=('Segoe UI', 8, 'italic'), foreground="#666666")
        self.size_lbl.grid(row=1, column=4, sticky='w', padx=10, pady=4)

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
