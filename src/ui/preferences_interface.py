"""Preferences interface tab: view modes and grid animation tuning."""

import tkinter as tk
from tkinter import ttk, messagebox


class PreferencesInterfaceMixin:
    """Default views for Applications/Files plus grid animation controls."""

    def _create_interface_tab(self):
        tab = ttk.Frame(self.dialog)

        views = ttk.LabelFrame(tab, text="Default Views", padding=10)
        views.pack(fill=tk.X, padx=10, pady=10)
        views.columnconfigure(1, weight=1)

        ttk.Label(views, text="Applications:").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.apps_view_var = tk.StringVar(value="grid")
        ttk.Radiobutton(views, text="Grid", variable=self.apps_view_var,
                        value="grid").grid(row=0, column=1, sticky=tk.W, padx=5)
        ttk.Radiobutton(views, text="List", variable=self.apps_view_var,
                        value="list").grid(row=0, column=2, sticky=tk.W, padx=5)

        ttk.Label(views, text="Files:").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.files_view_var = tk.StringVar(value="list")
        ttk.Radiobutton(views, text="Grid", variable=self.files_view_var,
                        value="grid").grid(row=1, column=1, sticky=tk.W, padx=5)
        ttk.Radiobutton(views, text="List", variable=self.files_view_var,
                        value="list").grid(row=1, column=2, sticky=tk.W, padx=5)

        anim = ttk.LabelFrame(tab, text="Grid Animations", padding=10)
        anim.pack(fill=tk.X, padx=10, pady=10)

        self.grid_anims_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(anim, text="Skeleton shimmer + crossfade",
                        variable=self.grid_anims_var).pack(anchor=tk.W, pady=3)

        delay_row = ttk.Frame(anim)
        delay_row.pack(fill=tk.X, pady=3)
        ttk.Label(delay_row, text="Skeleton delay (ms, 0 = instant):").pack(side=tk.LEFT)
        self.skeleton_delay_var = tk.StringVar(value="150")
        ttk.Spinbox(delay_row, textvariable=self.skeleton_delay_var,
                    from_=0, to=1000, increment=50, width=8).pack(side=tk.LEFT, padx=8)

        return tab

    def _load_interface_settings(self):
        get = self.config.get
        self.apps_view_var.set(get('applications', 'view_mode', 'grid') or 'grid')
        self.files_view_var.set(get('file_manager', 'view_mode', 'list') or 'list')
        self.grid_anims_var.set(bool(get('file_manager', 'grid_animations', True)))
        self.skeleton_delay_var.set(str(get('file_manager', 'skeleton_delay_ms', 150)))

    def _save_interface_settings(self):
        if self.apps_view_var.get() not in ('grid', 'list'):
            messagebox.showerror("Error", "Applications view must be Grid or List.",
                                 parent=self.dialog)
            return False
        if self.files_view_var.get() not in ('grid', 'list'):
            messagebox.showerror("Error", "Files view must be Grid or List.",
                                 parent=self.dialog)
            return False
        try:
            delay = max(0, min(1000, int(self.skeleton_delay_var.get().strip() or 150)))
        except (TypeError, ValueError):
            messagebox.showerror("Error", "Skeleton delay must be 0-1000 ms.",
                                 parent=self.dialog)
            return False
        self.config.set('applications', 'view_mode', self.apps_view_var.get())
        self.config.set('file_manager', 'view_mode', self.files_view_var.get())
        self.config.set('file_manager', 'grid_animations', self.grid_anims_var.get())
        self.config.set('file_manager', 'skeleton_delay_ms', delay)
        return True
