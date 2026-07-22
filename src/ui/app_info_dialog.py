import tkinter as tk
from tkinter import ttk
import threading
import os
import tempfile

class AppInfoDialog(tk.Toplevel):
    def __init__(self, parent, app_info, device_id=None, device_manager=None):
        super().__init__(parent)
        self.title(f"Application Info: {app_info['package']}")
        self.resizable(False, False)
        self.transient(parent)
        
        self.app_info = app_info
        self.device_id = device_id
        self.device_manager = device_manager
        
        frame = tk.Frame(self, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # 1. Create right-side icon_frame first to ensure correct Tkinter packing layout
        icon_frame = tk.Frame(frame, padx=10)
        icon_frame.pack(side=tk.RIGHT, fill=tk.Y, anchor='n')
        
        icon_area = tk.Frame(icon_frame, width=512, height=512, bg="#f0f0f0", bd=1, relief=tk.SUNKEN)
        icon_area.pack_propagate(False)
        icon_area.pack(pady=10)
        
        self.icon_label = tk.Label(icon_area, text="Loading icon...", bg="#f0f0f0", font=('', 12, 'bold'))
        self.icon_label.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(icon_frame, text="App Icon", font=('Arial', 9, 'italic')).pack()
        
        # 2. Create left-side details_frame
        details_frame = tk.Frame(frame)
        details_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 20))
        
        info_grid = tk.Frame(details_frame)
        info_grid.pack(side=tk.TOP, fill=tk.X)
        info_grid.columnconfigure(1, weight=1)
        
        btn_frame = tk.Frame(details_frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, anchor='w')
        
        details = [
            ("Package Name:", app_info['package']),
            ("Version Name:", app_info.get('version_name', 'Unknown')),
            ("Version Code:", app_info.get('version_code', 'Unknown')),
            ("Install Time:", app_info.get('install_time', 'Unknown')),
            ("Update Time:", app_info.get('update_time', 'Unknown')),
            ("User ID:", app_info.get('user_id', 'Unknown')),
            ("Installer:", app_info.get('installer', 'Unknown')),
            ("Path:", app_info.get('path', 'Unknown')),
        ]
        
        for i, (label, value) in enumerate(details):
            ttk.Label(info_grid, text=label, font=('', 10, 'bold')).grid(row=i, column=0, sticky='nw', pady=5, padx=(0, 10))
            
            val_text = tk.Text(info_grid, height=1, width=45, wrap='char', bd=0, bg=frame.cget('bg'), font=('', 10))
            if len(str(value)) > 40:
                val_text.config(height=2)
            elif '\n' in str(value):
                val_text.config(height=str(value).count('\n') + 1)
                
            val_text.insert('1.0', str(value))
            val_text.config(state='disabled')
            val_text.grid(row=i, column=1, sticky='new', pady=5)
            
        ttk.Button(btn_frame, text="Close", command=self.destroy, width=12).pack(side=tk.LEFT)


        
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

        
        # Load icon asynchronously
        if self.device_id and self.device_manager:
            threading.Thread(target=self._load_icon_async, daemon=True).start()
        else:
            self.icon_label.config(text="No Device Link")

    def _load_icon_async(self):
        try:
            package = self.app_info['package']
            cache_dir = os.path.join(tempfile.gettempdir(), 'droidmgr_icons')
            icon_path = self.device_manager.adb.extract_app_icon(self.device_id, package, cache_dir)
            
            if icon_path and os.path.exists(icon_path):
                self.after(0, lambda: self._update_icon_ui(icon_path))
            else:
                self.after(0, lambda: self.icon_label.config(text="No Icon Found"))
        except Exception as e:
            self.after(0, lambda: self.icon_label.config(text="Failed to load"))

    def _update_icon_ui(self, icon_path):
        try:
            self.icon_image = tk.PhotoImage(file=icon_path)
            w = self.icon_image.width()
            h = self.icon_image.height()
            
            # Zoom or subsample to fit in 512x512
            if w > 0 and w < 256:
                factor = 256 // w
                if factor > 1:
                    self.icon_image = self.icon_image.zoom(factor)
            elif w > 512:
                factor = w // 512
                if factor > 1:
                    self.icon_image = self.icon_image.subsample(factor)
                    
            self.icon_label.config(image=self.icon_image, text="")
        except Exception as e:
            self.icon_label.config(text="Display Error")




class ProcessInfoDialog(tk.Toplevel):
    def __init__(self, parent, proc_info):
        super().__init__(parent)
        self.title(f"Process Details: {proc_info['name']}")
        self.resizable(False, False)
        self.transient(parent)
        
        frame = tk.Frame(self, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)
        
        details = [
            ("Process Name:", proc_info['name']),
            ("PID:", proc_info['pid']),
            ("User:", proc_info['user']),
            ("CPU Usage:", f"{proc_info['cpu']}%"),
            ("Memory Usage:", proc_info['mem']),
        ]
        
        for i, (label, value) in enumerate(details):
            ttk.Label(frame, text=label, font=('', 10, 'bold')).grid(row=i, column=0, sticky='nw', pady=5, padx=(0, 10))
            
            val_text = tk.Text(frame, height=1, wrap='char', bd=0, bg=frame.cget('bg'), font=('', 10))
            val_text.insert('1.0', str(value))
            val_text.config(state='disabled')
            val_text.grid(row=i, column=1, sticky='new', pady=5)
            
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
            
        self.wait_visibility()
        self.grab_set()
        self.bind('<Escape>', lambda e: self.destroy())



