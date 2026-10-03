"""FileManager mixin: grid view mode on the shared TileGrid."""

import threading
import tkinter as tk
from tkinter import ttk
from .dpi import scale_size
from .tile_assets import find_asset, load_scaled_icon
from .file_dialogs import FileDetailsDialog


class _FileGridMixin:
    """_FileGridMixin (see file_manager.py)."""

    def _load_grid_icons(self):
        """Load folder/file/empty-folder icons once; tiles share the images."""
        size = scale_size(48, self.frame)
        self._folder_icon = load_scaled_icon(find_asset('folder-256.png'), size, self.frame)
        self._folder_empty_icon = load_scaled_icon(find_asset('folder-empty.png'), size, self.frame)
        self._file_icon = load_scaled_icon(find_asset('file-256.png'), size, self.frame)

    def _grid_icon_for(self, file_info):
        if file_info.get('is_dir'):
            if file_info.get('is_empty') and self._folder_empty_icon is not None:
                return self._folder_empty_icon
            return self._folder_icon
        return self._file_icon

    def set_view_mode(self, mode=None):
        """Switch between list and grid; the tree stays the selection owner."""
        if mode is None:
            mode = self.view_mode_var.get()
        else:
            self.view_mode_var.set(mode)
        self.config.set('file_manager', 'view_mode', mode)
        if mode == "grid":
            self.list_container.pack_forget()
            self.grid_container.pack(fill=tk.BOTH, expand=True)
            self._render_file_grid()
            self._fill_empty_icons_bg()
        else:
            self.grid_container.pack_forget()
            self.list_container.pack(fill=tk.BOTH, expand=True)

    def _fill_empty_icons_bg(self):
        """Batched emptiness check for the current dir, then swap folder icons.

        Runs when entering grid mode with unknown emptiness (a refresh in
        grid mode already attaches the flags, so this is usually a no-op).
        One adb round trip; stale results are discarded if the user moved on.
        """
        device, path = self.selected_device, self.current_path
        if not device or self._empty_key == (device, path):
            return
        if not any(f['is_dir'] for f in self.current_files):
            return
        empty_icon = self._folder_empty_icon
        if empty_icon is None:
            return

        def task():
            try:
                names = frozenset(self.device_manager.get_empty_dirs(device, path))
            except Exception:
                return

            def apply():
                if self.selected_device != device or self.current_path != path:
                    return
                self._empty_key = (device, path)
                self._empty_names = names
                if not hasattr(self, 'file_grid'):
                    return
                for f in self.current_files:
                    if f['is_dir'] and f['name'] in names:
                        f['is_empty'] = True
                        self.file_grid.update_icon(f['name'], empty_icon)
            self.frame.after(0, apply)

        threading.Thread(target=task, daemon=True).start()

    def _render_file_grid(self):
        if not hasattr(self, 'file_grid'):
            return
        items = [(f['name'], f['name']) for f in self.current_files]
        icons = {}
        for f in self.current_files:
            icon = self._grid_icon_for(f)
            if icon is not None:
                icons[f['name']] = icon
        self.file_grid.set_icons(icons)
        self.file_grid.set_items(items)
        selected = self._get_selected_names()
        if selected:
            self.file_grid.set_selected(selected)

    def _get_selected_name(self):
        names = self._get_selected_names()
        return names[0] if names else None

    def _get_selected_names(self):
        """Selected file names in tree order."""
        selected = set(self.file_tree.selection())
        names = []
        for item_id in self.file_tree.get_children(''):
            if item_id in selected:
                values = self.file_tree.item(item_id, 'values')
                if values:
                    names.append(values[0])
        return names

    def _select_tree_row(self, name):
        return self._select_tree_rows([name])

    def _select_tree_rows(self, names):
        """Select tree rows for names; returns how many matched."""
        wanted = set(names)
        found = []
        for item_id in self.file_tree.get_children(''):
            values = self.file_tree.item(item_id, 'values')
            if values and values[0] in wanted:
                found.append(item_id)
        if found:
            self.file_tree.selection_set(found)
            self.file_tree.focus(found[-1])
        return len(found)

    def _on_grid_select(self, names):
        if names:
            if not self._select_tree_rows(names):
                self.file_grid.set_selected([])
        else:
            try:
                self.file_tree.selection_remove(self.file_tree.selection())
            except Exception:
                pass
        self._update_selection_buttons()

    def _on_grid_activate(self, name):
        if getattr(self, '_loading', False):
            return
        if not name:
            return
        info = self.files_by_name.get(name)
        if info is None:
            return
        if info['is_dir']:
            self.previous_path = self.current_path
            current = self.current_path.rstrip('/')
            self.current_path = f"{current}/{name}/"
            self.path_var.set(self.current_path)
            self.refresh()
        else:
            FileDetailsDialog(self.frame.winfo_toplevel(), info)

    def _on_grid_context(self, event, name):
        if getattr(self, '_loading', False):
            return
        if name and name not in self._get_selected_names():
            self._select_tree_row(name)
            self._update_selection_buttons()
        if self.file_tree.selection():
            self._popup_context_menu(event.x_root, event.y_root)

