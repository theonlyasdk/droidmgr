"""MainWindow mixin: applications grid view and listing refresh."""

import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Dict, List, Optional
from core import ADBDeviceOfflineError, ADBDeviceNotFoundError
from .main_utils import _app_sort_key, _is_offline_error


class _AppGridMixin:
    """_AppGridMixin for MainWindow (see main_window.py)."""

    def _render_app_grid(self):
        """Push the filtered app list into the shared TileGrid."""
        if not hasattr(self, 'app_grid'):
            return
        if not getattr(self, '_default_app_icon', None):
            self._default_app_icon = self._create_default_app_icon()
        items = []
        icons = {}
        for app in getattr(self, '_filtered_apps', []):
            pkg = app['package']
            name = app.get('name') or pkg.split('.')[-1]
            items.append((pkg, name))
            icon = self._app_icon_cache.get(pkg, self._default_app_icon)
            if icon is not None:
                icons[pkg] = icon
        self.app_grid.set_default_icon(self._default_app_icon)
        self.app_grid.set_icons(icons)
        self.app_grid.set_items(items)
        selected = self._get_selected_packages()
        if selected:
            self.app_grid.set_selected(selected)
        self._load_visible_grid_icons()

    def _visible_grid_packages(self):
        """Return only tiles in or immediately beside the viewport."""
        if hasattr(self, 'app_grid'):
            return self.app_grid.get_visible_keys()
        return []

    def _load_visible_grid_icons(self):
        if not getattr(self, '_filtered_apps', None):
            return
        visible = self._visible_grid_packages()
        to_load = [p for p in visible if p not in self._app_icon_cache and p not in self._app_icon_loading]
        if to_load:
            self._load_app_icons_async(to_load)

    def _on_grid_visible(self, keys):
        if self.app_view_mode_var.get() == "grid" and self._is_apps_tab_visible():
            to_load = [p for p in keys
                       if p not in self._app_icon_cache and p not in self._app_icon_loading]
            if to_load:
                self._load_app_icons_async(to_load)

    def _on_grid_select(self, packages):
        if packages:
            self._select_grid_tiles(packages)
        else:
            try:
                self.app_tree.selection_remove(self.app_tree.selection())
            except Exception:
                pass
            self._update_app_button_states()

    def _on_grid_activate(self, package):
        if package:
            self._select_grid_tiles([package])
            self._show_app_info()
        return "break"

    def _on_grid_context(self, event, package):
        if package and package not in self._get_selected_packages():
            self._select_grid_tiles([package])
        if self._get_selected_package():
            self._show_app_context_menu(event)

    def _sync_grid_selection(self):
        if not hasattr(self, 'app_grid'):
            return
        try:
            if not self.app_grid.winfo_exists():
                return
        except Exception:
            return
        self.app_grid.set_selected(self._get_selected_packages())

    def _select_grid_tiles(self, packages):
        items = [self._app_tree_items[p] for p in packages
                 if p in self._app_tree_items]
        if items:
            self.app_tree.selection_set(items)
            self.app_tree.focus(items[-1])
        if getattr(self, 'app_view_mode_var', None) and self.app_view_mode_var.get() == "grid":
            if hasattr(self, 'app_grid'):
                self.app_grid.set_selected(packages)
                try:
                    self.app_grid.canvas.focus_set()
                except Exception:
                    pass
        self._update_app_button_states()

    def _open_grid_app_info(self, event=None):
        if self._get_selected_package():
            self._show_app_info()
        return "break"

    def _on_app_selection_change(self, event):
        self._update_app_button_states()
        self._sync_grid_selection()
        count = len(self._get_selected_packages())
        if count > 1:
            self._set_status(f"{count} applications selected")

    def _refresh_apps(self):
        if not self.selected_device:
            return
        if self._app_icon_cache_device != self.selected_device:
            self._app_icon_cache.clear()
            self._app_icon_loading.clear()
            if hasattr(self, '_icon_pending_packages'):
                with self._icon_lock:
                    self._icon_pending_packages.clear()
            self._app_icon_cache_device = self.selected_device
            self._icon_extract_generation = getattr(self, '_icon_extract_generation', 0) + 1
        
        # Check device readiness before querying
        try:
            if not self.device_manager.is_device_ready(self.selected_device):
                status = None
                if hasattr(self.device_manager, 'get_device_status'):
                    status = self.device_manager.get_device_status(self.selected_device)
                status_str = status.lower() if status else 'offline'
                self._apps_data = []
                for item in self.app_tree.get_children():
                    self.app_tree.delete(item)
                if hasattr(self, 'app_grid'):
                    self.app_grid.clear()
                tag_text = f"[Device is {status_str}]"
                self.app_tree.insert('', tk.END, values=(tag_text, "", "", ""))
                if hasattr(self, 'app_count_label'):
                    self.app_count_label.config(text="")
                self._update_drop_hint()
                self._update_app_button_states()
                self._set_status(f"Device '{self.selected_device}' is {status_str}.")
                return
        except Exception:
            pass

        selected_packages = set(self._get_selected_packages())
        yview = self.app_tree.yview()

        def task():
            try:
                apps_details = self.device_manager.get_installed_apps_details(self.selected_device)

                # Re-apply the column sort so a refresh does not snap back to name order
                sort_col = getattr(self, 'app_sort_col', None)
                if sort_col:
                    apps_details.sort(key=lambda app: _app_sort_key(app, sort_col),
                                      reverse=self.app_sort_reverse)

                def update():
                    if not self.notebook.winfo_exists():
                        return
                    cur_sel = self.notebook.select()
                    if cur_sel and self.notebook.tab(cur_sel, 'text') != 'Applications':
                        return
                    self._apps_data = apps_details
                    self._apply_app_filter(restore_selected=selected_packages, restore_yview=yview)
                    self._update_app_button_states()
                    self._set_status(f"Found {len(apps_details)} applications")
                self.root.after(0, update)
            except (ADBDeviceOfflineError, ADBDeviceNotFoundError):
                def handle_offline():
                    self._apps_data = []
                    for item in self.app_tree.get_children():
                        self.app_tree.delete(item)
                    if hasattr(self, 'app_grid'):
                        self.app_grid.clear()
                    self.app_tree.insert('', tk.END, values=("[Device is offline]", "", "", ""))
                    if hasattr(self, 'app_count_label'):
                        self.app_count_label.config(text="")
                    self._update_drop_hint()
                    self._update_app_button_states()
                    self._set_status(f"Device '{self.selected_device}' is offline or disconnected.")
                self.root.after(0, handle_offline)
            except Exception as e:
                msg = str(e)
                lower_msg = msg.lower()
                if _is_offline_error(msg):
                    def handle_offline():
                        self._apps_data = []
                        for item in self.app_tree.get_children():
                            self.app_tree.delete(item)
                        if hasattr(self, 'app_grid'):
                            self.app_grid.clear()
                        tag = "[Device is unauthorized]" if "unauthorized" in lower_msg else "[Device is offline]"
                        self.app_tree.insert('', tk.END, values=(tag, "", "", ""))
                        if hasattr(self, 'app_count_label'):
                            self.app_count_label.config(text="")
                        self._update_drop_hint()
                        self._update_app_button_states()
                        self._set_status(f"Device '{self.selected_device}' is offline or disconnected.")
                    self.root.after(0, handle_offline)
                else:
                    self.root.after(0, lambda: self._show_error("App Refresh Error", msg))
        
        threading.Thread(target=task, daemon=True).start()

