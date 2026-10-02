"""Device details dialog for droidmgr."""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
from .dpi import setup_window_dpi
from .network_inspector import NetworkInspector

HEALTH_REFRESH_MS = 5000


def _format_bytes(num_bytes):
    """Render a byte count as a short human-readable size such as '41.2 GB'."""
    size = float(num_bytes or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            return f"{int(size)} {unit}" if unit == 'B' else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _format_duration(seconds):
    """Render a number of seconds as '4 days, 2 hours, 11 minutes'."""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return ''
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days > 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
    if minutes or not parts:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    return ', '.join(parts)


class DeviceDetailsDialog(tk.Toplevel):

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

        setup_window_dpi(self, base_width=650, base_height=600, min_width=500, min_height=450, parent=parent)

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

    def _create_health_tab(self):
        """Battery, storage, temperature, uptime and WiFi, refreshed on a timer."""
        self.health_vars = {}

        def field(parent, row, label, key, bar=None):
            ttk.Label(parent, text=label, font=('Arial', 10, 'bold')).grid(
                row=row, column=0, sticky='w', pady=5, padx=(0, 12))
            var = tk.StringVar(value='Reading...')
            ttk.Label(parent, textvariable=var).grid(row=row, column=1, sticky='w', pady=5)
            if bar is not None:
                bar.grid(row=row, column=2, sticky='w', padx=(12, 0), pady=5)
            self.health_vars[key] = var
            return var

        battery = ttk.LabelFrame(self.health_tab, text='Battery', padding=10)
        battery.pack(fill=tk.X, pady=(0, 8))
        battery.columnconfigure(1, weight=1)
        self.battery_bar = ttk.Progressbar(battery, maximum=100, length=150)
        field(battery, 0, 'Level:', 'battery_level', self.battery_bar)
        field(battery, 1, 'Status:', 'battery_status')
        field(battery, 2, 'Health:', 'battery_health')
        field(battery, 3, 'Temperature:', 'battery_temperature')
        field(battery, 4, 'Power source:', 'battery_power')
        field(battery, 5, 'Technology:', 'battery_technology')

        storage = ttk.LabelFrame(self.health_tab, text='Storage', padding=10)
        storage.pack(fill=tk.X, pady=(0, 8))
        storage.columnconfigure(1, weight=1)
        self.storage_bar = ttk.Progressbar(storage, maximum=100, length=150)
        field(storage, 0, 'Free space:', 'storage_free', self.storage_bar)
        field(storage, 1, 'Partition:', 'storage_mount')
        field(storage, 2, 'Used:', 'storage_used')

        device = ttk.LabelFrame(self.health_tab, text='Device', padding=10)
        device.pack(fill=tk.BOTH, expand=True)
        device.columnconfigure(1, weight=1)
        field(device, 0, 'CPU temperature:', 'thermal_cpu')
        field(device, 1, 'Battery temperature:', 'thermal_battery')
        field(device, 2, 'Thermal status:', 'thermal_status')
        field(device, 3, 'Uptime:', 'uptime')
        field(device, 4, 'WiFi:', 'wifi')

        controls = ttk.Frame(self.health_tab)
        controls.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(controls, text='Refresh now', command=self._refresh_health).pack(side=tk.LEFT)
        self.health_auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text='Auto-refresh', variable=self.health_auto_var,
                        command=self._schedule_health_refresh).pack(side=tk.LEFT, padx=10)
        self.health_updated_var = tk.StringVar(value='')
        ttk.Label(controls, textvariable=self.health_updated_var,
                  foreground='gray').pack(side=tk.RIGHT)

    def _on_tab_changed(self, event=None):
        """Read the network tab the first time it is shown, and never before."""
        if self.notebook.index(self.notebook.select()) != self.notebook.index(self.network_tab):
            return
        if self.network_inspector.loaded:
            return
        self.network_inspector.load()

    def _cancel_health_refresh(self):
        if self._health_job is not None:
            try:
                self.after_cancel(self._health_job)
            except tk.TclError:
                pass
            self._health_job = None

    def _schedule_health_refresh(self):
        """Queue the next health read, unless auto-refresh is off or the dialog is gone."""
        self._cancel_health_refresh()
        if not self.health_auto_var.get() or not self._is_alive():
            return
        self._health_job = self.after(HEALTH_REFRESH_MS, self._refresh_health)

    def _refresh_health(self):
        """Read health on a worker thread; ticks never overlap."""
        self._health_job = None
        if not self._is_alive():
            return
        if self._health_busy:
            self._schedule_health_refresh()
            return

        self._health_busy = True
        device_id = self.device_id

        def task():
            stats = None
            error = ''
            try:
                stats = self.device_manager.get_health_stats(device_id)
            except Exception as exc:
                error = str(exc)
            if self._is_alive():
                self.after(0, lambda: self._apply_health(stats, error))

        threading.Thread(target=task, daemon=True).start()

    def _apply_health(self, stats, error):
        self._health_busy = False
        if not self._is_alive():
            return

        if stats is None:
            message = error or 'Failed to read device health'
            for var in self.health_vars.values():
                var.set(message)
            self._schedule_health_refresh()
            return

        battery = stats.get('battery') or {}
        storage = stats.get('storage') or {}
        thermal = stats.get('thermal') or {}
        wifi = stats.get('wifi') or {}
        missing = 'Unavailable'

        level = battery.get('level')
        self.battery_bar['value'] = level if level is not None else 0
        self.health_vars['battery_level'].set(f"{level}%" if level is not None else missing)
        self.health_vars['battery_status'].set(battery.get('status') or missing)
        self.health_vars['battery_health'].set(battery.get('health') or missing)
        temperature = battery.get('temperature')
        self.health_vars['battery_temperature'].set(
            f"{temperature} °C" if temperature is not None else missing)
        self.health_vars['battery_power'].set(battery.get('powered_by') or missing)
        self.health_vars['battery_technology'].set(battery.get('technology') or missing)

        percent = storage.get('percent')
        self.storage_bar['value'] = percent if percent is not None else 0
        if storage.get('total'):
            self.health_vars['storage_free'].set(
                f"{_format_bytes(storage['free'])} free of {_format_bytes(storage['total'])}")
            self.health_vars['storage_used'].set(
                f"{_format_bytes(storage['used'])} used ({percent}%)")
        else:
            self.health_vars['storage_free'].set(missing)
            self.health_vars['storage_used'].set(missing)
        self.health_vars['storage_mount'].set(storage.get('mount') or missing)

        cpu_temp = thermal.get('cpu')
        battery_temp = thermal.get('battery')
        self.health_vars['thermal_cpu'].set(f"{cpu_temp} °C" if cpu_temp is not None else missing)
        self.health_vars['thermal_battery'].set(
            f"{battery_temp} °C" if battery_temp is not None else missing)
        self.health_vars['thermal_status'].set(thermal.get('status') or missing)

        uptime = _format_duration(stats.get('uptime'))
        self.health_vars['uptime'].set(uptime or missing)

        self.health_vars['wifi'].set(self._describe_wifi(wifi))

        self.health_updated_var.set(f"Updated {time.strftime('%H:%M:%S')}")
        self._schedule_health_refresh()

    @staticmethod
    def _describe_wifi(wifi):
        """One-line WiFi summary: state, network and signal strength."""
        enabled = wifi.get('enabled')
        if enabled is False:
            return 'Disabled'
        if enabled is None and not wifi.get('ssid'):
            return 'Unavailable'

        parts = ['Enabled' if enabled else '']
        if wifi.get('ssid'):
            parts.append(wifi['ssid'])
        if wifi.get('rssi') is not None:
            parts.append(f"{wifi['rssi']} dBm")
        if wifi.get('state'):
            parts.append(wifi['state'])
        return ' - '.join(part for part in parts if part)
        
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
