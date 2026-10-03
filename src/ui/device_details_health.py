"""Battery/storage/thermal health tab for the device details dialog."""

import threading
import time
import tkinter as tk
from tkinter import ttk
from .device_details_format import _format_bytes, _format_duration, HEALTH_REFRESH_MS


class DeviceHealthMixin:
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
