import posixpath
import copy
import tkinter as tk
from collections import OrderedDict
from pathlib import Path
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading
from core import ConfigManager, ADBDeviceOfflineError, ADBDeviceNotFoundError
from .dpi import scale_size, setup_window_dpi
from .tile_grid import TileGrid
from .file_dialogs import FileDetailsDialog
from .file_listing import _FileListingMixin
from .file_gridview import _FileGridMixin
from .file_ops import _FileOpsMixin

# Storage-bar fill colors by how much of the storage is already used.
_USAGE_COLORS = (
    (0.60, '#2e9e4f'),   # plenty free: green
    (0.85, '#e0a800'),   # getting tight: amber
    (1.01, '#d03a2b'),   # nearly full: red
)
_USAGE_TROUGH = '#e9edf3'
_USAGE_EDGE = '#c8cdd6'


def _usage_color(used_ratio: float) -> str:
    for limit, color in _USAGE_COLORS:
        if used_ratio < limit:
            return color
    return _USAGE_COLORS[-1][1]


class _UsageBar(tk.Canvas):
    """Thin one-row storage bar whose fill color matches the fill level.

    Drawn by hand on a canvas because the native ttk progressbar on Windows
    keeps theme-issued green regardless of any style color set.
    """

    def __init__(self, master, height: int = 12):
        super().__init__(master, height=height, highlightthickness=0, bd=0)
        self._ratio = 0.0
        self.bind('<Configure>', lambda event: self._redraw())
        self._redraw()

    def set_usage(self, used_ratio: float):
        """Set the used fraction of storage, clamped to 0..1."""
        self._ratio = max(0.0, min(1.0, used_ratio))
        self._redraw()

    def _redraw(self):
        self.delete('all')
        width = max(self.winfo_width(), 1)
        height = max(self.winfo_height(), 1)
        self.create_rectangle(0, 0, width, height,
                              outline=_USAGE_EDGE, fill=_USAGE_TROUGH)
        used_width = int(round(width * self._ratio))
        if used_width > 0:
            self.create_rectangle(0, 0, used_width, height,
                                  fill=_usage_color(self._ratio), outline='')


class FileManager(_FileListingMixin, _FileGridMixin, _FileOpsMixin):
    def __init__(self, parent_frame, device_manager, set_status_callback, show_error_callback, require_device_callback, view_mode_var=None):
        self.frame = parent_frame
        self.device_manager = device_manager
        self._set_status = set_status_callback
        self._show_error = show_error_callback
        self._require_device = require_device_callback

        self.current_path = "/sdcard/"
        self.selected_device = None
        self.previous_path = None
        self._permission_dialog_open = False
        self._loading = False
        self._skeleton_after = None
        self.files_data = {} # Map item_id -> file_info dict
        self.files_by_name = {} # Map name -> file_info dict (grid source of truth)
        self.current_files = [] # Ordered file listing for the current directory
        self.config = ConfigManager()
        # Shared with the View > Files menu so menu and toolbar stay in sync.
        self.view_mode_var = view_mode_var or tk.StringVar(value="list")
        self._folder_icon = None
        self._folder_empty_icon = None
        self._file_icon = None
        # (device, path) the cached empty-dir names below were computed for.
        self._empty_key = None
        self._empty_names = frozenset()
        # (device, path, flags) -> (files, writable); avoids re-listing the
        # same directory on tab switches and back/forward navigation.
        self._listing_cache = OrderedDict()
        # Bumped per refresh(); a background task whose seq is stale drops
        # its result instead of flashing another directory's listing.
        self._refresh_seq = 0
        # (device, remote_path) -> watcher entry, for files opened via Edit...
        self._edit_watches = {}
        # Path whose summary-strip numbers are currently showing.
        self._size_path = None

        self._create_widgets()

    def _create_widgets(self):
        # Summary strip: best-effort du/df stats for the current directory.
        strip = ttk.Frame(self.frame)
        strip.pack(fill=tk.X, padx=5, pady=(5, 0))

        folder_card = ttk.LabelFrame(strip, text='Folder', padding=(8, 2))
        folder_card.pack(side=tk.LEFT, padx=(0, 6))
        self._size_total_var = tk.StringVar(value='Total: —')
        ttk.Label(folder_card, textvariable=self._size_total_var,
                  font=('Segoe UI', 9, 'bold')).pack()

        storage_card = ttk.LabelFrame(strip, text='Storage', padding=(8, 2))
        # One row: the text, then the bar eating the strip's spare width.
        storage_card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        self._size_free_var = tk.StringVar(value='Free: —')
        ttk.Label(storage_card, textvariable=self._size_free_var,
                  font=('Segoe UI', 9, 'bold')).pack(side=tk.LEFT, padx=(0, 8))
        self._storage_bar = _UsageBar(storage_card)
        self._storage_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=2)

        # Navigation bar
        nav_frame = ttk.Frame(self.frame)
        nav_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Up button on the left
        self.up_btn = ttk.Button(nav_frame, text="↑ Up", command=self._go_up_level)
        self.up_btn.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(nav_frame, text="Path:").pack(side=tk.LEFT, padx=2)
        self.path_var = tk.StringVar(value=self.current_path)
        self.path_entry = ttk.Entry(nav_frame, textvariable=self.path_var)
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self.path_entry.bind('<Return>', lambda e: self._navigate_to_path())

        self.go_btn = ttk.Button(nav_frame, text="Go", command=self._navigate_to_path)
        self.go_btn.pack(side=tk.LEFT, padx=2)

        # Pin the current path, and a drop-down with favorites + history.
        self.pin_btn = ttk.Button(nav_frame, text='★ Pin', command=self._toggle_pin_current)
        self.pin_btn.pack(side=tk.LEFT, padx=2)
        self.path_menu_btn = ttk.Button(nav_frame, text='▾', width=3,
                                        command=self._show_path_menu)
        self.path_menu_btn.pack(side=tk.LEFT, padx=2)

        ttk.Radiobutton(nav_frame, text="List", variable=self.view_mode_var,
                        value="list", command=self.set_view_mode).pack(side=tk.RIGHT, padx=2)
        ttk.Radiobutton(nav_frame, text="Grid", variable=self.view_mode_var,
                        value="grid", command=self.set_view_mode).pack(side=tk.RIGHT, padx=2)

        # File list
        list_frame = ttk.LabelFrame(self.frame, text="Files")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.view_container = ttk.Frame(list_frame)
        self.view_container.pack(fill=tk.BOTH, expand=True)

        # 1. List view
        self.list_container = ttk.Frame(self.view_container)

        columns = ('Name', 'Size', 'Permissions')
        self.file_tree = ttk.Treeview(self.list_container, columns=columns, show='tree headings')
        
        self.file_tree.heading('#0', text='Type')
        self.file_tree.heading('Name', text='Name')
        self.file_tree.heading('Size', text='Size')
        self.file_tree.heading('Permissions', text='Permissions')
        
        self.file_tree.column('#0', width=scale_size(80, self.frame))
        self.file_tree.column('Name', width=scale_size(400, self.frame))
        self.file_tree.column('Size', width=scale_size(100, self.frame))
        self.file_tree.column('Permissions', width=scale_size(150, self.frame))
        
        scrollbar = ttk.Scrollbar(self.list_container, orient=tk.VERTICAL, command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=scrollbar.set)
        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.file_tree.bind('<Double-1>', self._on_file_double_click)
        self.file_tree.bind('<<TreeviewSelect>>', self._on_selection_change)
        self.file_tree.bind('<Button-3>', self._show_context_menu)
        self.file_tree.bind('<Button-2>', self._show_context_menu)

        # 2. Grid view (shared TileGrid, same behaviour as Applications)
        self.grid_container = ttk.Frame(self.view_container)
        self.file_grid = TileGrid(
            self.grid_container,
            on_select=self._on_grid_select,
            on_activate=self._on_grid_activate,
            on_context=self._on_grid_context,
            empty_text="This folder is empty",
        )
        self.file_grid.pack(fill=tk.BOTH, expand=True)
        self._load_grid_icons()

        # Honor the remembered view mode instead of always starting on list.
        self.set_view_mode(self.view_mode_var.get())

        
        # Buttons
        btn_frame = ttk.Frame(self.frame)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.refresh_btn = ttk.Button(btn_frame, text="Refresh", command=self.refresh)
        self.refresh_btn.pack(side=tk.LEFT, padx=2)
        
        self.download_btn = ttk.Button(btn_frame, text="Download", command=self._download_file)
        self.download_btn.pack(side=tk.LEFT, padx=2)
        
        self.upload_btn = ttk.Button(btn_frame, text="Upload", command=self._upload_file)
        self.upload_btn.pack(side=tk.LEFT, padx=2)

        self.new_folder_btn = ttk.Button(btn_frame, text="New Folder", command=self._create_folder)
        self.new_folder_btn.pack(side=tk.LEFT, padx=2)


        # Separator
        ttk.Separator(btn_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        
        self.rename_btn = ttk.Button(btn_frame, text="Rename", command=self._rename_file, state=tk.DISABLED)
        self.rename_btn.pack(side=tk.LEFT, padx=2)
        
        self.copy_btn = ttk.Button(btn_frame, text="Copy To", command=self._copy_file, state=tk.DISABLED)
        self.copy_btn.pack(side=tk.LEFT, padx=2)
        
        self.move_btn = ttk.Button(btn_frame, text="Move To", command=self._move_file, state=tk.DISABLED)
        self.move_btn.pack(side=tk.LEFT, padx=2)
        
        self.delete_btn = ttk.Button(btn_frame, text="Delete", command=self._delete_file, state=tk.DISABLED)
        self.delete_btn.pack(side=tk.LEFT, padx=2)

    def set_device(self, device_id, force_refresh=False):
        changed = (self.selected_device != device_id)
        if changed:
            self._last_rendered_path = None
            self._cancel_all_edit_watches()
            self._size_path = None
        self.selected_device = device_id
        if not device_id:
            self._finish_loading()
            self._clear_list()
            self._size_total_var.set('Total: —')
            self._size_free_var.set('Free: —')
            self.file_grid.set_empty_text("This folder is empty")
            self._update_selection_buttons()
            return

        if changed or force_refresh:
            self.refresh()
        else:
            self._update_selection_buttons()


    # -- grid view (shared TileGrid) -----------------------------------


    def _navigate_to_path(self):
        if getattr(self, '_loading', False):
            return
        new_path = self.path_var.get().strip()
        if not new_path:
            new_path = "/sdcard/"
            
        # Sanitize path: ensure it starts with / and doesn't contain relative '..'
        if not new_path.startswith('/'):
            new_path = '/' + new_path
            
        # Basic protection against path traversal in the entry box
        if '..' in new_path:
            messagebox.showwarning("Invalid Path", "Relative paths ('..') are not allowed in the navigation bar.")
            self.path_var.set(self.current_path)
            return

        if not new_path.endswith('/'):
            new_path += '/'

        if new_path != self.current_path:
            self.previous_path = self.current_path
        self.current_path = new_path
        self.path_var.set(self.current_path)
        self.refresh()

    def _go_up_level(self):
        if getattr(self, '_loading', False):
            return
        if not self.selected_device or self.current_path == "/":
            self._update_navigation_buttons()
            return
        
        try:
            path = self.current_path.rstrip('/')
            # Remember where we came from so a denied parent can bounce back.
            self.previous_path = self.current_path
            if '/' in path:
                parent = path.rsplit('/', 1)[0] + '/'
                if not parent: parent = "/"
                self.current_path = parent
                self.path_var.set(self.current_path)
                self.refresh()
                self._update_selection_buttons()  # Update bottom buttons
            else:
                self.current_path = "/"
                self.path_var.set(self.current_path)
                self.refresh()
                self._update_selection_buttons()  # Update bottom buttons
        except Exception as e:
            self._show_error("Navigation Error", f"Could not navigate up: {e}")

    def _update_navigation_buttons(self):
        if getattr(self, '_loading', False):
            self.up_btn.config(state=tk.DISABLED)
            return
        if self.current_path == "/":
            self.up_btn.config(state=tk.DISABLED)
        else:
            self.up_btn.config(state=tk.NORMAL)

    def _on_file_double_click(self, event):
        if getattr(self, '_loading', False):
            return
        selection = self.file_tree.selection()
        if not selection:
            return
            
        item_id = selection[0]
        item = self.file_tree.item(item_id)
        file_info = self.files_data.get(item_id)
        
        if 'directory' in item['tags']:
            name = item['values'][0]
            if name == "." or name == "..":
                return
            
            # Store previous path before navigating
            self.previous_path = self.current_path
            
            # Robust path joining
            current = self.current_path.rstrip('/')
            new_path = f"{current}/{name}/"
            
            self.current_path = new_path
            self.path_var.set(self.current_path)
            self.refresh()
        else:
            # Show file details dialog
            if file_info:
                FileDetailsDialog(self.frame.winfo_toplevel(), file_info)

    def _on_selection_change(self, event):
        if getattr(self, 'view_mode_var', None) and self.view_mode_var.get() == "grid":
            if hasattr(self, 'file_grid'):
                self.file_grid.set_selected(self._get_selected_names())
        self._update_selection_buttons()

    def _update_selection_buttons(self):
        if getattr(self, '_loading', False):
            for btn in (self.download_btn, self.upload_btn, self.new_folder_btn,
                        self.rename_btn, self.copy_btn, self.move_btn,
                        self.delete_btn):
                btn.config(state=tk.DISABLED)
            return
        has_selection = bool(self.file_tree.selection()) and self.selected_device is not None
        
        # Check dynamically if directory is writable, falling back to static path assumption
        is_writable = getattr(self, 'is_current_path_writable', None)
        if is_writable is None:
            # Fallback path-based assumption
            is_writable = self.current_path.startswith('/sdcard') or self.current_path.startswith('/storage')
            
        state = tk.NORMAL if has_selection else tk.DISABLED
        write_state = tk.NORMAL if (is_writable and has_selection) else tk.DISABLED
        upload_state = tk.NORMAL if is_writable else tk.DISABLED
        
        self.download_btn.config(state=state)
        self.rename_btn.config(state=write_state)
        self.copy_btn.config(state=state) # Copy to is allowed
        self.move_btn.config(state=write_state)
        self.delete_btn.config(state=write_state)
        self.upload_btn.config(state=upload_state)
        self.new_folder_btn.config(state=upload_state)


    def update_button_states(self, state):
        self.refresh_btn.config(state=state)
        self.download_btn.config(state=state)
        self.upload_btn.config(state=state)
        self.new_folder_btn.config(state=state)
        self._update_selection_buttons()

    # -- path favorites & history (ConfigManager section 'file_paths') ----------

    _PATH_HISTORY_LIMIT = 15

    def _read_path_list(self, kind):
        """Favorites/history paths for this device: deduped, order preserved."""
        data = self.config.get('file_paths', kind, {}) or {}
        if not isinstance(data, dict):
            return []
        entries = data.get(self.selected_device) if self.selected_device else None
        if not isinstance(entries, list):
            return []
        seen, result = set(), []
        for entry in entries:
            entry = str(entry).strip()
            if not entry or entry in seen:
                continue
            seen.add(entry)
            result.append(entry)
        return result[:self._PATH_HISTORY_LIMIT] if kind == 'history' else result

    def _write_path_list(self, kind, paths):
        if not self.selected_device:
            return
        data = self.config.get('file_paths', kind, {}) or {}
        if not isinstance(data, dict):
            data = {}
        data[self.selected_device] = list(paths)
        self.config.set('file_paths', kind, data)

    def _remember_path(self, path):
        """Record a successfully listed path as the device's most recent."""
        if not self.selected_device or not path:
            return
        history = self._read_path_list('history')
        if history and history[0] == path:
            return
        entries = [p for p in history if p != path]
        entries.insert(0, path)
        self._write_path_list('history', entries[:self._PATH_HISTORY_LIMIT])

    def _toggle_pin_current(self):
        if not self.selected_device:
            self._set_status('Connect a device to pin paths.')
            return
        path = self.current_path
        favorites = self._read_path_list('favorites')
        if path in favorites:
            self._write_path_list('favorites', [p for p in favorites if p != path])
            self._set_status(f'Unpinned {path}')
        else:
            self._write_path_list('favorites', [path] + favorites)
            self._set_status(f'Pinned {path}')

    def _show_path_menu(self):
        if not self.selected_device:
            self._set_status('Connect a device to browse saved paths.')
            return
        favorites = self._read_path_list('favorites')
        recent = [p for p in self._read_path_list('history') if p not in favorites]

        menu = tk.Menu(self.frame, tearoff=0)
        if favorites:
            for path in favorites:
                menu.add_command(label='★ ' + path,
                                 command=lambda p=path: self._goto_path(p))
        else:
            menu.add_command(label='No favorites yet', state=tk.DISABLED)

        menu.add_separator()
        if recent:
            for path in recent:
                menu.add_command(label=path, command=lambda p=path: self._goto_path(p))
        else:
            menu.add_command(label='No recent paths yet', state=tk.DISABLED)

        menu.add_separator()
        menu.add_command(label='Clear History', command=self._clear_path_history)

        self.path_menu_btn.update_idletasks()
        try:
            menu.tk_popup(self.path_menu_btn.winfo_rootx(),
                          self.path_menu_btn.winfo_rooty()
                          + self.path_menu_btn.winfo_height())
        finally:
            menu.grab_release()

    def _clear_path_history(self):
        if not self.selected_device:
            return
        self._write_path_list('history', [])
        self._set_status('Cleared path history.')

    def _goto_path(self, path):
        """Navigate to a favorite/history path via the path-bar flow."""
        path = (path or '').strip()
        if not path:
            return
        if not path.startswith('/'):
            path = '/' + path
        if '..' in path:
            messagebox.showwarning(
                "Invalid Path",
                "Relative paths ('..') are not allowed in the navigation bar.")
            return
        if not path.endswith('/'):
            path += '/'
        self.path_var.set(path)
        self._navigate_to_path()

    # -- summary strip size formatting ------------------------------------------

    @staticmethod
    def _format_bytes_display(amount):
        """Human-readable size ('12 B' / '12.4 MB'), matching core formatting."""
        try:
            size = float(amount)
        except (TypeError, ValueError):
            return '—'
        for unit in ('B', 'KB', 'MB', 'GB', 'TB', 'PB'):
            if size < 1024 or unit == 'PB':
                if unit == 'B':
                    return f"{int(size)} B"
                return f"{size:.1f} {unit}"
            size /= 1024
        return '—'


