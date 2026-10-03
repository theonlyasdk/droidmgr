"""MainWindow mixin: Applications tab, filter, TileGrid view, sorting."""

import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Dict, List, Optional
from .dpi import scale_size
from .tile_grid import TileGrid
from .file_drop import enable_file_drop
from .main_utils import _format_bytes


class _AppsTabMixin:
    """_AppsTabMixin for MainWindow (see main_window.py)."""

    def _create_apps_tab(self):
        tab = ttk.Frame(self.notebook)

        self._apps_data = []
        self._filtered_apps = []
        self._app_tree_items = {}
        self._app_icon_cache = {}
        self._app_icon_cache_device = None
        self._app_icon_loading = set()
        self._default_app_icon = None
        self._icon_pending_packages = []
        self._icon_lock = threading.Lock()
        self._icon_worker_active = False

        # Applications filter and view switch toolbar
        app_toolbar = ttk.Frame(tab)
        app_toolbar.pack(fill=tk.X, padx=5, pady=(5, 2))

        ttk.Label(app_toolbar, text="Filter:").pack(side=tk.LEFT, padx=(0, 4))
        self.app_filter_var = tk.StringVar()
        self.app_filter_entry = ttk.Entry(app_toolbar, textvariable=self.app_filter_var, width=20)
        self.app_filter_entry.pack(side=tk.LEFT, padx=(0, 8))
        self.app_filter_var.trace_add('write', lambda *_: self._apply_app_filter())

        self.app_system_var = tk.BooleanVar(value=True)
        self.app_system_cb = ttk.Checkbutton(
            app_toolbar, text="System packages", variable=self.app_system_var,
            command=self._apply_app_filter)
        self.app_system_cb.pack(side=tk.LEFT, padx=(0, 8))

        self.app_count_label = ttk.Label(app_toolbar, text="", foreground="gray")
        self.app_count_label.pack(side=tk.LEFT, padx=4)

        # Right-aligned view switcher and actions
        self.refresh_apps_btn = ttk.Button(app_toolbar, text="Refresh", command=self._refresh_apps, width=8)
        self.refresh_apps_btn.pack(side=tk.RIGHT, padx=(4, 0))

        self.install_apk_btn = ttk.Button(app_toolbar, text="+ Install APK", command=self._install_apk)
        self.install_apk_btn.pack(side=tk.RIGHT, padx=4)

        if not hasattr(self, 'app_view_mode_var') or self.app_view_mode_var is None:
            self.app_view_mode_var = tk.StringVar(
                value=self.config.get('applications', 'view_mode', 'grid'))
        self.app_list_mode_btn = ttk.Radiobutton(
            app_toolbar, text="List", variable=self.app_view_mode_var,
            value="list", command=self._switch_app_view_mode)
        self.app_list_mode_btn.pack(side=tk.RIGHT, padx=2)

        self.app_grid_mode_btn = ttk.Radiobutton(
            app_toolbar, text="Grid", variable=self.app_view_mode_var,
            value="grid", command=self._switch_app_view_mode)
        self.app_grid_mode_btn.pack(side=tk.RIGHT, padx=2)

        # Container for List and Grid views
        list_frame = ttk.LabelFrame(tab, text="Installed Applications")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=4)

        self.app_view_container = ttk.Frame(list_frame)
        self.app_view_container.pack(fill=tk.BOTH, expand=True)

        # 1. List View (Treeview)
        self.app_list_container = ttk.Frame(self.app_view_container)

        self.app_sort_col = 'Name'
        self.app_sort_reverse = False
        columns = ('Name', 'Package', 'Type', 'Size')
        self.app_tree = ttk.Treeview(self.app_list_container, columns=columns, show='headings',
                                     selectmode='extended')
        for col in columns:
            self.app_tree.heading(col, text=col,
                                  command=lambda c=col: self._sort_apps_by_column(c))
        self.app_tree.column('Name', width=scale_size(200, self.root))
        self.app_tree.column('Package', width=scale_size(300, self.root))
        self.app_tree.column('Type', width=scale_size(80, self.root), anchor='center')
        self.app_tree.column('Size', width=scale_size(100, self.root), anchor='e')

        scrollbar_tv = ttk.Scrollbar(self.app_list_container, orient=tk.VERTICAL, command=self.app_tree.yview)
        self.app_tree.configure(yscrollcommand=scrollbar_tv.set)
        self.app_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_tv.pack(side=tk.RIGHT, fill=tk.Y)
        self.app_tree.bind('<<TreeviewSelect>>', self._on_app_selection_change)
        self.app_tree.bind('<Double-1>', self._show_app_info)
        self.app_tree.bind('<Return>', self._show_app_info)
        self.app_tree.bind('<Button-3>', self._show_app_context_menu)

        # 2. Grid View (shared TileGrid, also used by the Files tab)
        self.app_grid_container = ttk.Frame(self.app_view_container)

        self.app_grid = TileGrid(
            self.app_grid_container,
            on_select=self._on_grid_select,
            on_activate=self._on_grid_activate,
            on_context=self._on_grid_context,
            on_visible=self._on_grid_visible,
            empty_text="No applications found",
        )
        self.app_grid.pack(fill=tk.BOTH, expand=True)

        # Show whichever view the View menu / toolbar currently selects.
        if self.app_view_mode_var.get() == "grid":
            self.app_grid_container.pack(fill=tk.BOTH, expand=True)
        else:
            self.app_list_container.pack(fill=tk.BOTH, expand=True)

        # Dropping APKs from Explorer installs them, when the platform supports it.
        self.drop_supported = enable_file_drop(list_frame, self._on_files_dropped)
        if self.drop_supported:
            self.drop_hint = ttk.Label(
                self.app_tree,
                text="No applications found.\nDrop .apk files here to install them.",
                foreground='gray',
                anchor='center',
                justify='center'
            )
            self.drop_hint.place(relx=0.5, rely=0.5, anchor='center')
            self.app_tree.bind('<Configure>', self._on_drop_hint_configure)

        # Bottom action buttons
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)

        self.extract_apk_btn = ttk.Button(btn_frame, text="Extract APK", command=self._extract_apk)
        self.extract_apk_btn.pack(side=tk.LEFT, padx=2)

        self.start_app_btn = ttk.Button(btn_frame, text="Start App", command=self._start_app)
        self.start_app_btn.pack(side=tk.LEFT, padx=2)

        self.stop_app_btn = ttk.Button(btn_frame, text="Stop App", command=self._stop_app)
        self.stop_app_btn.pack(side=tk.LEFT, padx=2)

        self.uninstall_app_btn = ttk.Button(btn_frame, text="Uninstall App", command=self._uninstall_app)
        self.uninstall_app_btn.pack(side=tk.LEFT, padx=2)

        self.clear_cache_btn = ttk.Button(btn_frame, text="Clear Cache", command=self._clear_app_cache)
        self.clear_cache_btn.pack(side=tk.LEFT, padx=2)

        return tab

    def _is_apps_tab_visible(self) -> bool:
        try:
            sel = self.notebook.select()
            return self.notebook.tab(sel, 'text') == 'Applications' if sel else False
        except Exception:
            return False

    def _switch_app_view_mode(self):
        mode = self.app_view_mode_var.get()
        self.config.set('applications', 'view_mode', mode)
        if mode == "grid":
            self.app_list_container.pack_forget()
            self.app_grid_container.pack(fill=tk.BOTH, expand=True)
            self._render_app_grid()
        else:
            self.app_grid_container.pack_forget()
            self.app_list_container.pack(fill=tk.BOTH, expand=True)

    def _switch_file_view_mode(self):
        if hasattr(self, 'file_manager'):
            self.file_manager.set_view_mode(self.file_view_mode_var.get())

    def _apply_app_filter(self, restore_selected=None, restore_yview=None):
        query = getattr(self, 'app_filter_var', None)
        q_text = query.get().strip().lower() if query else ""
        show_sys = getattr(self, 'app_system_var', None)
        is_sys = show_sys.get() if show_sys is not None else True

        apps = getattr(self, '_apps_data', [])
        filtered = []
        for app in apps:
            if not is_sys and app.get('is_system'):
                continue
            if q_text:
                name = (app.get('name') or '').lower()
                pkg = (app.get('package') or '').lower()
                if q_text not in name and q_text not in pkg:
                    continue
            filtered.append(app)

        self._filtered_apps = filtered

        # Update count badge
        total = len(apps)
        showing = len(filtered)
        if hasattr(self, 'app_count_label'):
            if q_text or not is_sys:
                self.app_count_label.config(text=f"{showing} of {total} packages")
            else:
                self.app_count_label.config(text=f"{total} total packages")

        # Update Treeview
        for item in self.app_tree.get_children():
            self.app_tree.delete(item)

        target_ids = []
        self._app_tree_items.clear()
        for app in filtered:
            item_id = self.app_tree.insert(
                '', tk.END,
                values=(app['name'], app['package'], app['type'],
                        _format_bytes(app.get('size_bytes', 0)))
            )
            self._app_tree_items[app['package']] = item_id
            if restore_selected and app['package'] in restore_selected:
                target_ids.append(item_id)

        self._update_drop_hint()

        if target_ids:
            self.app_tree.selection_set(target_ids)
            self.app_tree.focus(target_ids[0])

        if restore_yview:
            try:
                self.app_tree.yview_moveto(restore_yview[0])
            except Exception:
                pass

        # Update Grid View
        if getattr(self, 'app_view_mode_var', None) and self.app_view_mode_var.get() == "grid":
            self._render_app_grid()


    def _on_files_dropped(self, paths):
        """Install APKs dropped from Explorer onto the applications list."""
        self._install_apk_paths(paths)

    def _on_drop_hint_configure(self, event):
        """Wrap the drop hint to the width the applications list currently has."""
        available = event.width - scale_size(16, self.root)
        if available > scale_size(80, self.root):
            self.drop_hint.configure(wraplength=available)

    def _update_drop_hint(self):
        """Show the drop hint only while the applications list is empty."""
        if not getattr(self, 'drop_supported', False):
            return
        if self.app_tree.get_children():
            self.drop_hint.place_forget()
        else:
            self.drop_hint.place(relx=0.5, rely=0.5, anchor='center')

