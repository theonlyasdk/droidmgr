"""About dialog for droidmgr."""

import tkinter as tk
from tkinter import ttk
from .dpi import setup_window_dpi


class AboutDialog:
    
    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("About droidmgr")
        self.dialog.transient(parent)
        
        self._create_widgets()
        setup_window_dpi(self.dialog, base_width=400, base_height=550, min_width=400, min_height=500, parent=parent)
            
        # Ensure window is visible before grabbing
        self.dialog.wait_visibility()
        self.dialog.grab_set()
        self.dialog.bind('<Escape>', lambda e: self.dialog.destroy())


    

    
    def _create_widgets(self):
        main_frame = ttk.Frame(self.dialog, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        title = tk.Label(
            main_frame,
            text="Droidmgr",
            font=('Arial', 24, 'bold'),
            fg='#2196F3'
        )
        title.pack(pady=(0, 10))
        
        version = tk.Label(
            main_frame,
            text="Version 1.0.0",
            font=('Arial', 10)
        )
        version.pack()
        
        description = tk.Label(
            main_frame,
            text="GUI frontend for scrcpy and Android device manager\nReport bugs on GitHub issues if you find any!",
            font=('Arial', 10),
            justify=tk.CENTER
        )
        description.pack(pady=20)
        
        features_frame = ttk.LabelFrame(main_frame, text="Features", padding=10)
        features_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        features = [
            "• Screen mirroring with scrcpy",
            "• Process management",
            "• Application management",
            "• File browser & transfer",
            "• Auto-dependency installation"
        ]
        
        for feature in features:
            label = tk.Label(features_frame, text=feature, anchor=tk.W)
            label.pack(fill=tk.X, pady=2)
        
        info = tk.Label(
            main_frame,
            text="© 2026 theonlyasdk\nLicensed under MPL 2.0",
            font=('Arial', 8),
            fg='gray'
        )
        info.pack(pady=(10, 0))
        
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(10, 0))
        
        ttk.Button(
            button_frame,
            text="Close",
            command=self.dialog.destroy,
            width=15
        ).pack()
    
    def show(self):
        self.dialog.wait_window()
