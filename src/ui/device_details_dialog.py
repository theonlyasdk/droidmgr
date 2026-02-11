"""Device details dialog for droidmgr."""

import tkinter as tk
from tkinter import ttk, messagebox
import threading

class DeviceDetailsDialog(tk.Toplevel):
    
    def __init__(self, parent, device_id, device_manager):
        super().__init__(parent)
        self.title(f"Device Details - {device_id}")
        self.geometry("650x600")
        self.device_id = device_id
        self.device_manager = device_manager
        
        self.resizable(True, True)
        self.transient(parent)
        
        self._create_widgets()
        self._load_info()
        
        # Ensure window is drawn before grabbing focus
        self.wait_visibility()
        self.grab_set()
    
    def _create_widgets(self):
        self.main_frame = ttk.Frame(self, padding=10)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        header = tk.Label(
            self.main_frame,
            text=f"Device: {self.device_id}",
            font=('Arial', 14, 'bold'),
            fg='#2196F3'
        )
        header.pack(pady=(0, 10))
        
        # Tabs for different data categories
        self.notebook = ttk.Notebook(self.main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        self.specs_tab = ttk.Frame(self.notebook, padding=10)
        self.encoders_tab = ttk.Frame(self.notebook, padding=10)
        self.displays_tab = ttk.Frame(self.notebook, padding=10)
        self.cameras_tab = ttk.Frame(self.notebook, padding=10)
        
        self.notebook.add(self.specs_tab, text="Specifications")
        self.notebook.add(self.encoders_tab, text="Encoders")
        self.notebook.add(self.displays_tab, text="Displays")
        self.notebook.add(self.cameras_tab, text="Cameras")
        
        # Specs layout
        self.specs_scroll = ttk.Frame(self.specs_tab)
        self.specs_scroll.pack(fill=tk.BOTH, expand=True)
        
        # Loading indicators
        self.loading_labels = {}
        for tab_frame in [self.specs_tab, self.encoders_tab, self.displays_tab, self.cameras_tab]:
            lbl = ttk.Label(tab_frame, text="Retrieving data...")
            lbl.pack(pady=50)
            self.loading_labels[tab_frame] = lbl

        # Placeholder for text widgets
        self.text_widgets = {}
        for tab_frame in [self.encoders_tab, self.displays_tab, self.cameras_tab]:
            txt = tk.Text(tab_frame, wrap=tk.NONE, font=('Courier New', 9))
            vsb = ttk.Scrollbar(tab_frame, orient="vertical", command=txt.yview)
            hsb = ttk.Scrollbar(tab_frame, orient="horizontal", command=txt.xview)
            txt.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
            
            self.text_widgets[tab_frame] = (txt, vsb, hsb)
            
        # Button frame
        btn_frame = ttk.Frame(self.main_frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        
        self.easter_egg_btn = ttk.Button(
            btn_frame,
            text="Launch Easter Egg",
            command=self._launch_easter_egg,
            state=tk.DISABLED
        )
        self.easter_egg_btn.pack(side=tk.LEFT)
        
        ttk.Button(
            btn_frame,
            text="Close",
            command=self.destroy,
            width=12
        ).pack(side=tk.RIGHT)
        
    def _is_alive(self):
        """Check if the dialog window still exists."""
        try:
            return self.winfo_exists()
        except tk.TclError:
            return False

    def _load_info(self):
        def task():
            try:
                # 1. Specs
                info = self.device_manager.adb.get_detailed_device_info(self.device_id)
                if self._is_alive():
                    self.after(0, lambda: self._display_specs(info))
                
                # 2. Encoders
                encoders = self.device_manager.scrcpy.list_encoders(self.device_id)
                if self._is_alive():
                    self.after(0, lambda: self._display_text_result(self.encoders_tab, encoders))
                
                # 3. Displays
                displays = self.device_manager.scrcpy.list_displays(self.device_id)
                if self._is_alive():
                    self.after(0, lambda: self._display_text_result(self.displays_tab, displays))
                
                # 4. Cameras & Sizes
                cameras = self.device_manager.scrcpy.list_cameras(self.device_id)
                cam_sizes = self.device_manager.scrcpy.list_camera_sizes(self.device_id)
                combined_cams = f"--- AVAILABLE CAMERAS ---\n{cameras}\n\n--- AVAILABLE CAMERA SIZES ---\n{cam_sizes}"
                if self._is_alive():
                    self.after(0, lambda: self._display_text_result(self.cameras_tab, combined_cams))
                
            except Exception as e:
                if self._is_alive():
                    msg = str(e)
                    self.after(0, lambda: messagebox.showerror("Error", f"Failed to get device info:\n{msg}"))
                    self.after(0, self.destroy)
        
        threading.Thread(target=task, daemon=True).start()
        
    def _display_specs(self, info):
        if not self._is_alive(): return
        
        if self.specs_tab in self.loading_labels:
            self.loading_labels[self.specs_tab].destroy()
            del self.loading_labels[self.specs_tab]
        
        labels = [
            ("Manufacturer:", info.get('manufacturer', 'N/A')),
            ("Model:", info.get('model', 'N/A')),
            ("Chipset (CPU):", info.get('cpu', 'N/A')),
            ("Memory (RAM):", info.get('ram', 'N/A')),
            ("Product Name:", info.get('product_name', 'N/A')),
            ("Serial Number:", info.get('serial', 'N/A')),
            ("Android Version:", info.get('android_version', 'N/A')),
            ("Android Codename:", info.get('android_codename', 'N/A')),
            ("Build ID:", info.get('build_id', 'N/A')),
            ("Linux Kernel:", info.get('kernel', 'N/A')),
        ]
        
        container = self.specs_scroll
        container.columnconfigure(1, weight=1)
        
        for i, (label_txt, value) in enumerate(labels):
            tk.Label(
                container,
                text=label_txt,
                font=('Arial', 10, 'bold'),
                anchor=tk.W
            ).grid(row=i, column=0, sticky='nw', pady=8, padx=(0, 10))
            
            val_widget = tk.Text(
                container,
                height=1,
                font=('Arial', 10),
                bd=0,
                bg=self.cget('bg'),
                highlightthickness=0
            )
            if len(str(value)) > 40:
                val_widget.config(height=2, wrap=tk.CHAR)
            
            val_widget.insert('1.0', str(value))
            val_widget.config(state='disabled')
            val_widget.grid(row=i, column=1, sticky='new', pady=8)
            
        self.easter_egg_btn.config(state=tk.NORMAL)

    def _display_text_result(self, tab, content):
        if not self._is_alive(): return
        
        if tab in self.loading_labels:
            self.loading_labels[tab].destroy()
            del self.loading_labels[tab]
            
        txt, vsb, hsb = self.text_widgets[tab]
        
        # Show scrollbars
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        txt.insert('1.0', content)
        txt.config(state='disabled')
        
    def _launch_easter_egg(self):
        try:
            self.device_manager.adb.trigger_easter_egg(self.device_id)
            messagebox.showinfo("Easter Egg", "Look at your device screen! Attempted to launch the Android Easter Egg.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to launch easter egg: {e}")
