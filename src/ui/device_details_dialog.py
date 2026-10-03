"""Device details dialog for droidmgr."""

import tkinter as tk
from tkinter import ttk
from .device_details_format import _format_bytes, _format_duration, HEALTH_REFRESH_MS
from .device_details_health import DeviceHealthMixin
from .device_details_specs import DeviceSpecsMixin
from .dpi import setup_window_dpi
from .network_inspector import NetworkInspector


__all__ = [
    'DeviceDetailsDialog',
    'HEALTH_REFRESH_MS',
    '_format_bytes',
    '_format_duration',
]


class DeviceDetailsDialog(DeviceHealthMixin, DeviceSpecsMixin, tk.Toplevel):
    def __init__(self, parent, device_id, device_manager):
        super().__init__(parent)
        self.title(f"Device Details - {device_id}")
        self.device_id = device_id
        self.device_manager = device_manager

        self._health_job = None
        self._health_busy = False

        self.resizable(True, True)
        self.transient(parent)

        self._create_widgets()
        self._load_info()

        setup_window_dpi(self, base_width=650, base_height=720, min_width=500, min_height=500, parent=parent)

        # Ensure window is drawn before grabbing focus
        self.wait_visibility()
        self.grab_set()
        self.bind('<Escape>', lambda e: self._close())
        self.protocol('WM_DELETE_WINDOW', self._close)

        self._refresh_health()

    def _close(self):
        """Stop the health timer before the dialog goes away."""
        self._cancel_health_refresh()
        self.destroy()

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
        self.health_tab = ttk.Frame(self.notebook, padding=10)
        self.network_tab = ttk.Frame(self.notebook, padding=10)

        self.notebook.add(self.specs_tab, text="Specifications")
        self.notebook.add(self.health_tab, text="Health")
        self.notebook.add(self.network_tab, text="Network")
        self.notebook.add(self.encoders_tab, text="Encoders")
        self.notebook.add(self.displays_tab, text="Displays")
        self.notebook.add(self.cameras_tab, text="Cameras")

        # Specs layout
        self.specs_scroll = ttk.Frame(self.specs_tab)
        self.specs_scroll.pack(fill=tk.BOTH, expand=True)

        self._create_health_tab()

        # The network tables cost a few hundred kilobytes of device output to
        # read, so they are left alone until the tab is actually looked at.
        self.network_inspector = NetworkInspector(
            self.network_tab, self.device_id, self.device_manager)
        self.network_inspector.pack(fill=tk.BOTH, expand=True)
        self.notebook.bind('<<NotebookTabChanged>>', self._on_tab_changed)

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
            command=self._close,
            width=12
        ).pack(side=tk.RIGHT)

    def _on_tab_changed(self, event=None):
        """Read the network tab the first time it is shown, and manage polling."""
        if self.notebook.index(self.notebook.select()) != self.notebook.index(self.network_tab):
            self.network_inspector.stop_polling()
            return
        if not self.network_inspector.loaded:
            self.network_inspector.load()
        else:
            self.network_inspector.start_polling()
