import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading
from pathlib import Path
from core import ConfigManager

class FileDetailsDialog(tk.Toplevel):
    def __init__(self, parent, file_info):
        super().__init__(parent)
        self.title(f"Details: {file_info['name']}")
        self.resizable(False, False)
        self.transient(parent)
        
        frame = tk.Frame(self, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)
        
        # Grid layout for details
        details = [
            ("Name:", file_info['name']),
            ("Path:", file_info.get('full_path', 'Unknown')),
            ("Type:", "Directory" if file_info['is_dir'] else "File"),
            ("Size:", file_info['size']),
            ("Permissions:", file_info['permissions']),
            ("Owner:", file_info.get('user', 'Unknown')),
            ("Group:", file_info.get('group', 'Unknown')),
            ("Modified:", file_info.get('date_time', 'Unknown')),
        ]
        
        for i, (label, value) in enumerate(details):
            ttk.Label(frame, text=label, font=('', 10, 'bold')).grid(row=i, column=0, sticky='nw', pady=5, padx=(0, 10))
            
            # Use Text widget for values that might be long (like path)
            val_label = tk.Text(frame, height=1, wrap='none', bd=0, bg=frame.cget('bg'), font=('', 10))
            if '\n' in str(value) or len(str(value)) > 40:
                val_label.config(height=2, wrap='char')
            val_label.insert('1.0', str(value))
            val_label.config(state='disabled')
            val_label.grid(row=i, column=1, sticky='new', pady=5)
            
        ttk.Button(frame, text="Close", command=self.destroy).grid(row=len(details), column=0, columnspan=2, pady=(20, 0))
        
        # Ensure window is visible before grabbing
        self.wait_visibility()
        self.grab_set()

class FolderSelectorDialog(tk.Toplevel):
    def __init__(self, parent, device_manager, initial_path="/sdcard/"):
        super().__init__(parent)
        self.title("Select Destination Folder")
        self.geometry("600x400")
        self.transient(parent)
        
        self.device_manager = device_manager
        self.initial_path = initial_path
        self.selected_path = None
        
        self.device_id = None # Will be set by parent
        self.config = ConfigManager()
        
        self._create_widgets()
        
        self.wait_visibility()
        self.grab_set()
        
    def _create_widgets(self):
        self.frame = ttk.Frame(self)
        self.frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Navigation bar
        nav_frame = ttk.Frame(self.frame)
        nav_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(nav_frame, text="↑ Up", command=self._go_up).pack(side=tk.LEFT, padx=2)
        self.path_var = tk.StringVar(value=self.initial_path)
        ttk.Entry(nav_frame, textvariable=self.path_var, state='readonly').pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.tree = ttk.Treeview(self.frame, columns=('Name',), show='tree headings')
        self.tree.heading('#0', text='Type')
        self.tree.heading('Name', text='Name')
        self.tree.pack(fill=tk.BOTH, expand=True)
        
        self.tree.bind('<Double-1>', self._on_double_click)
        
        btn_frame = ttk.Frame(self.frame)
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Button(btn_frame, text="Select Current Folder", command=self._on_select).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        
    def start(self, device_id):
        self.device_id = device_id
        self._refresh()
        
    def _refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        def task():
            try:
                show_hidden = self.config.get('file_manager', 'show_hidden', False)
                files = self.device_manager.list_files(self.device_id, self.path_var.get(), show_hidden)
                def update():
                    for f in files:
                        if f['is_dir']:
                            self.tree.insert('', tk.END, text="[DIR]", values=(f['name'],), tags=('dir',))
                self.after(0, update)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        
        threading.Thread(target=task, daemon=True).start()

    def _go_up(self):
        path = self.path_var.get().rstrip('/')
        if '/' in path:
            parent = path.rsplit('/', 1)[0] + '/'
            self.path_var.set(parent)
            self._refresh()

    def _on_double_click(self, event):
        selection = self.tree.selection()
        if selection:
            item = self.tree.item(selection[0])
            name = item['values'][0]
            current = self.path_var.get().rstrip('/')
            self.path_var.set(current + '/' + name + '/')
            self._refresh()
            
    def _on_select(self):
        self.selected_path = self.path_var.get()
        self.destroy()

class FileManager:
    def __init__(self, parent_frame, device_manager, set_status_callback, show_error_callback, require_device_callback):
        self.frame = parent_frame
        self.device_manager = device_manager
        self._set_status = set_status_callback
        self._show_error = show_error_callback
        self._require_device = require_device_callback
        
        self.current_path = "/sdcard/"
        self.selected_device = None
        self.files_data = {} # Map item_id -> file_info dict
        self.config = ConfigManager()
        
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
        path_entry = ttk.Entry(nav_frame, textvariable=self.path_var)
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        path_entry.bind('<Return>', lambda e: self._navigate_to_path())
        
        ttk.Button(nav_frame, text="Go", command=self._navigate_to_path).pack(side=tk.LEFT, padx=2)
        
        # File list
        list_frame = ttk.LabelFrame(self.frame, text="Files")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        columns = ('Name', 'Size', 'Permissions')
        self.file_tree = ttk.Treeview(list_frame, columns=columns, show='tree headings')
        
        self.file_tree.heading('#0', text='Type')
        self.file_tree.heading('Name', text='Name')
        self.file_tree.heading('Size', text='Size')
        self.file_tree.heading('Permissions', text='Permissions')
        
        self.file_tree.column('#0', width=80)
        self.file_tree.column('Name', width=400)
        self.file_tree.column('Size', width=100)
        self.file_tree.column('Permissions', width=150)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=scrollbar.set)
        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.file_tree.bind('<Double-1>', self._on_file_double_click)
        self.file_tree.bind('<<TreeviewSelect>>', self._on_selection_change)
        
        # Buttons
        btn_frame = ttk.Frame(self.frame)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.refresh_btn = ttk.Button(btn_frame, text="Refresh", command=self.refresh)
        self.refresh_btn.pack(side=tk.LEFT, padx=2)
        
        self.download_btn = ttk.Button(btn_frame, text="Download", command=self._download_file)
        self.download_btn.pack(side=tk.LEFT, padx=2)
        
        self.upload_btn = ttk.Button(btn_frame, text="Upload", command=self._upload_file)
        self.upload_btn.pack(side=tk.LEFT, padx=2)

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

    def set_device(self, device_id):
        self.selected_device = device_id
        if device_id:
            self.refresh()
        else:
            self._clear_list()
        self._update_selection_buttons()

    def _clear_list(self):
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)
        self.files_data.clear()

    def refresh(self):
        if not self.selected_device:
            return
            
        self._clear_list()
        
        def task():
            try:
                path = self.current_path
                if not path.endswith('/'):
                    path += '/'
                
                show_hidden = self.config.get('file_manager', 'show_hidden', False)
                use_exact = self.config.get('file_manager', 'use_exact_sizes', False)
                files = self.device_manager.list_files(self.selected_device, path, show_hidden, use_exact)
                
                def update():
                    for f in files:
                        icon = "[DIR]" if f['is_dir'] else "[FILE]"
                        item_id = self.file_tree.insert('', tk.END, text=icon,
                                            values=(f['name'], f['size'], f['permissions']),
                                            tags=('directory' if f['is_dir'] else 'file',))
                        self.files_data[item_id] = f
                    self._set_status(f"Browsing {self.current_path}")
                    self._update_navigation_buttons()
                self.frame.after(0, update)
            except Exception as e:
                msg = str(e)
                if "Permission denied" in msg:
                    # Navigate back to previous path on permission error
                    def go_back():
                        if hasattr(self, 'previous_path') and self.previous_path:
                            self.current_path = self.previous_path
                            self.path_var.set(self.current_path)
                            self.refresh()
                            messagebox.showerror("Permission Error", f"You do not have permission to access that directory.\n\nRoot access might be required.")
                        else:
                            messagebox.showerror("Permission Error", f"You do not have permission to access:\n{path}\n\nRoot access might be required.")
                    self.frame.after(0, go_back)
                else:
                    self.frame.after(0, lambda: self._show_error("File Refresh Error", msg))
        
        threading.Thread(target=task, daemon=True).start()

    def _navigate_to_path(self):
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
            
        self.current_path = new_path
        self.path_var.set(self.current_path)
        self.refresh()

    def _go_up_level(self):
        if not self.selected_device or self.current_path == "/":
            self._update_navigation_buttons()
            return
        
        try:
            path = self.current_path.rstrip('/')
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
        if self.current_path == "/":
            self.up_btn.config(state=tk.DISABLED)
        else:
            self.up_btn.config(state=tk.NORMAL)

    def _on_file_double_click(self, event):
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
        self._update_selection_buttons()

    def _update_selection_buttons(self):
        has_selection = bool(self.file_tree.selection()) and self.selected_device is not None
        
        # Check if we are in a read-only area (anything not starting with /sdcard or /storage)
        is_read_only_area = not (self.current_path.startswith('/sdcard') or self.current_path.startswith('/storage'))
        
        state = tk.NORMAL if has_selection else tk.DISABLED
        write_state = tk.DISABLED if is_read_only_area or not has_selection else tk.NORMAL
        upload_state = tk.DISABLED if is_read_only_area else tk.NORMAL
        
        self.download_btn.config(state=state)
        self.rename_btn.config(state=write_state)
        self.copy_btn.config(state=state) # Copy to is allowed
        self.move_btn.config(state=write_state)
        self.delete_btn.config(state=write_state)
        self.upload_btn.config(state=upload_state)

    def _rename_file(self):
        selection = self.file_tree.selection()
        if not selection: return
        
        item_id = selection[0]
        item = self.file_tree.item(item_id)
        old_name = item['values'][0]
        
        new_name = simpledialog.askstring("Rename", f"Enter new name for {old_name}:", initialvalue=old_name)
        if not new_name or new_name == old_name:
            return
            
        if self.config.get('file_manager', 'confirm_rename', True):
            if not messagebox.askyesno("Confirm Rename", f"Are you sure you want to rename '{old_name}' to '{new_name}'?"):
                return
            
        old_path = self.current_path.rstrip('/') + '/' + old_name
        new_path = self.current_path.rstrip('/') + '/' + new_name
        
        try:
            self.device_manager.rename_file(self.selected_device, old_path, new_path)
            self.refresh()
            self._set_status(f"Renamed to {new_name}")
        except Exception as e:
            self._show_error("Rename Error", str(e))

    def _copy_file(self):
        self._move_copy_operation(copy=True)

    def _move_file(self):
        self._move_copy_operation(copy=False)

    def _move_copy_operation(self, copy=True):
        selection = self.file_tree.selection()
        if not selection: return
        
        item_id = selection[0]
        item = self.file_tree.item(item_id)
        filename = item['values'][0]
        src_path = self.current_path.rstrip('/') + '/' + filename
        
        dialog = FolderSelectorDialog(self.frame.winfo_toplevel(), self.device_manager, self.current_path)
        dialog.start(self.selected_device)
        self.frame.wait_window(dialog)
        
        if dialog.selected_path:
            dest_path = dialog.selected_path.rstrip('/') + '/' + filename
            
            def task():
                try:
                    if copy:
                        self.device_manager.copy_file(self.selected_device, src_path, dest_path)
                    else:
                        self.device_manager.move_file(self.selected_device, src_path, dest_path)
                    
                    self.frame.after(0, self.refresh)
                    self.frame.after(0, lambda: messagebox.showinfo("Success", "Operation completed successfully"))
                except Exception as e:
                    msg = str(e)
                    self.frame.after(0, lambda: self._show_error("Operation Error", msg))
            
            self._set_status("Processing...")
            threading.Thread(target=task, daemon=True).start()

    def _download_file(self):
        if not self._require_device():
            return
            
        selection = self.file_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a file or directory to download")
            return
            
        item_id = selection[0]
        item = self.file_tree.item(item_id)
        is_directory = 'directory' in item['tags']
        filename = item['values'][0]
        
        if is_directory:
            # For directories, let user choose a folder location
            local_path = filedialog.askdirectory(title=f"Select destination for '{filename}'")
            if local_path:
                # adb pull will create the directory inside the selected location
                local_path = str(Path(local_path) / filename)
        else:
            local_path = filedialog.asksaveasfilename(initialfile=filename)
        
        if not local_path:
            return
            
        remote_path = self.current_path.rstrip('/') + '/' + filename
        
        def task():
            try:
                if is_directory:
                    self.frame.after(0, lambda: self._set_status(f"Downloading directory {filename}..."))
                    # adb pull handles directories recursively
                    self.device_manager.download_file(self.selected_device, remote_path, local_path)
                    self.frame.after(0, lambda: (
                        messagebox.showinfo("Success", f"Directory downloaded successfully to:\n{local_path}"),
                        self._set_status(f"Downloaded {filename}")
                    ))
                else:
                    self.frame.after(0, lambda: self._set_status(f"Downloading {filename}..."))
                    self.device_manager.download_file(self.selected_device, remote_path, local_path)
                    self.frame.after(0, lambda: (
                        messagebox.showinfo("Success", "File downloaded successfully"),
                        self._set_status(f"Downloaded {filename}")
                    ))
            except Exception as e:
                msg = str(e)
                self.frame.after(0, lambda: (
                    self._show_error("Download Error", msg),
                    self._set_status(f"Download failed")
                ))
        
        self._set_status("Processing...")
        threading.Thread(target=task, daemon=True).start()

    def _upload_file(self):
        if not self._require_device():
            return
            
        local_path = filedialog.askopenfilename()
        if not local_path:
            return
            
        filename = Path(local_path).name
        remote_path = self.current_path.rstrip('/') + '/' + filename
        
        def task():
            try:
                self.device_manager.upload_file(self.selected_device, local_path, remote_path)
                self.frame.after(0, self.refresh)
                self.frame.after(0, lambda: messagebox.showinfo("Success", "File uploaded successfully"))
            except Exception as e:
                msg = str(e)
                self.frame.after(0, lambda: self._show_error("Upload Error", msg))
        
        self._set_status("Uploading file...")
        threading.Thread(target=task, daemon=True).start()

    def _delete_file(self):
        if not self._require_device():
            return
            
        selection = self.file_tree.selection()
        if not selection:
            return
            
        item_id = selection[0]
        item = self.file_tree.item(item_id)
        filename = item['values'][0]
        remote_path = self.current_path.rstrip('/') + '/' + filename
        
        if not messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete {filename}?"):
            return
            
        try:
            self.device_manager.delete_file(self.selected_device, remote_path)
            self.refresh()
            self._set_status(f"Deleted {filename}")
        except Exception as e:
            self._show_error("Delete Error", str(e))

    def update_button_states(self, state):
        self.refresh_btn.config(state=state)
        self.download_btn.config(state=state)
        self.upload_btn.config(state=state)
        self._update_selection_buttons()
