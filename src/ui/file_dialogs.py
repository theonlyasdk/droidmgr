"""Dialogs used by the file manager."""

import posixpath
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from core import ConfigManager
from .dpi import scale_size, setup_window_dpi


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
        
        # Center dialog relative to parent window
        self.update_idletasks()
        try:
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            dw = self.winfo_reqwidth()
            dh = self.winfo_reqheight()
            cx = px + (pw // 2) - (dw // 2)
            cy = py + (ph // 2) - (dh // 2)
            self.geometry(f"+{max(0, cx)}+{max(0, cy)}")
        except Exception:
            pass
            
        # Ensure window is visible before grabbing
        self.wait_visibility()
        self.grab_set()
        self.bind('<Escape>', lambda e: self.destroy())

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
        setup_window_dpi(self, base_width=600, base_height=400, parent=parent)
        self.wait_visibility()
        self.grab_set()
        self.bind('<Escape>', lambda e: self.destroy())


        
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

