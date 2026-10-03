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

        self._create_widgets()

    def _create_widgets(self):
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
        self.selected_device = device_id
        if not device_id:
            self._finish_loading()
            self._clear_list()
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


