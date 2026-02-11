import tkinter as tk
from tkinter import ttk

class AppInfoDialog(tk.Toplevel):
    def __init__(self, parent, app_info):
        super().__init__(parent)
        self.title(f"Application Info: {app_info['package']}")
        self.resizable(False, False)
        self.transient(parent)
        
        frame = tk.Frame(self, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)
        
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
            ttk.Label(frame, text=label, font=('', 10, 'bold')).grid(row=i, column=0, sticky='nw', pady=5, padx=(0, 10))
            
            # Text widget for values that might be long (like path)
            val_text = tk.Text(frame, height=1, wrap='char', bd=0, bg=frame.cget('bg'), font=('', 10))
            if len(str(value)) > 40:
                val_text.config(height=2)
            elif '\n' in str(value):
                val_text.config(height=str(value).count('\n') + 1)
                
            val_text.insert('1.0', str(value))
            val_text.config(state='disabled')
            val_text.grid(row=i, column=1, sticky='new', pady=5)
            
        ttk.Button(frame, text="Close", command=self.destroy).grid(row=len(details), column=0, columnspan=2, pady=(20, 0))
        
        # Ensure window is visible before grabbing
        self.wait_visibility()
        self.grab_set()
