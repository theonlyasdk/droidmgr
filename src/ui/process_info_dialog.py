"""Process details dialog."""
"""Split from app_info_dialog.py (MOVE-ONLY)."""

import tkinter as tk
from tkinter import ttk


        # Main notebook containing Overview and Details tabs
        # Bottom Bar
        # Center dialog relative to parent window
        # Load icon asynchronously
        # 1. Right-side icon frame
        # 2. Left-side details frame
        # Top Action Bar
        # Summary Metadata Card
        # Fingerprint row
        # Components Sub-Notebook (Permissions, Activities, Services, Receivers & Providers)
                # 1. Resolve exact remote APK path via pm path
                # Fallback if pm path failed
        # Populate components
            # Zoom or subsample to fit in 512x512
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
