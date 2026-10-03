"""Via-USB (TCP/IP) tab for the wireless connection dialog."""

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional


class WirelessUsbTabMixin:
    """Tab 1 (via USB) methods for ConnectWirelesslyDialog."""


    # -------------------------------------------------------------------------
    # TAB 1: Via USB (TCP/IP Setup)
    # -------------------------------------------------------------------------
    def _build_tab1(self):
        header_frame = ttk.Frame(self.tab1)
        header_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(
            header_frame,
            text="One-Click Wireless Mode Setup via USB",
            font=('Arial', 11, 'bold')
        ).pack(anchor='w')

        ttk.Label(
            header_frame,
            text="Plug your phone in once via USB. We'll enable TCP/IP 5555, detect its Wi-Fi / Hotspot IP, and connect wirelessly.",
            font=('Arial', 9),
            wraplength=540
        ).pack(anchor='w', pady=(2, 0))

        # USB Device Selection
        dev_frame = ttk.LabelFrame(self.tab1, text="Target USB Device", padding=10)
        dev_frame.pack(fill=tk.X, pady=(0, 10))

        dev_row = ttk.Frame(dev_frame)
        dev_row.pack(fill=tk.X)

        ttk.Label(dev_row, text="Device:").pack(side=tk.LEFT, padx=(0, 8))

        self.tab1_device_combo = ttk.Combobox(dev_row, state='readonly', width=30)
        self.tab1_device_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.tab1_device_combo.bind('<<ComboboxSelected>>', lambda e: self._on_tab1_device_changed())

        self.tab1_refresh_dev_btn = ttk.Button(dev_row, text="Refresh", command=self._refresh_tab1_devices)
        self.tab1_refresh_dev_btn.pack(side=tk.LEFT)

        self.tab1_enable_btn = ttk.Button(
            dev_frame,
            text="Enable Wireless ADB (Port 5555)",
            command=self._tab1_enable_tcpip
        )
        self.tab1_enable_btn.pack(anchor='w', pady=(8, 0))

        # Instructions / Post-Enable Frame
        self.tab1_inst_frame = ttk.LabelFrame(self.tab1, text="Instructions & Connect", padding=10)
        self.tab1_inst_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        self.tab1_banner_label = tk.Label(
            self.tab1_inst_frame,
            text="Click 'Enable Wireless ADB' above once your phone is connected via USB.",
            font=('Arial', 9, 'italic'),
            fg='#555555',
            anchor='w',
            justify=tk.LEFT,
            wraplength=520
        )
        self.tab1_banner_label.pack(anchor='w', pady=(0, 8))

        # IP, Auto-Detect and Connect sub-frame
        ip_grid = ttk.Frame(self.tab1_inst_frame)
        ip_grid.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(ip_grid, text="Device IP:").grid(row=0, column=0, sticky='w', padx=(0, 6), pady=4)
        self.tab1_ip_entry = ttk.Entry(ip_grid, textvariable=self.ip_tab1_var, width=16)
        self.tab1_ip_entry.grid(row=0, column=1, sticky='w', padx=(0, 6), pady=4)

        self.tab1_autodetect_btn = ttk.Button(
            ip_grid,
            text="Auto-Detect",
            command=lambda: self._autodetect_ip(self.ip_tab1_var, self.tab1_status_label, self._get_tab1_selected_id())
        )
        self.tab1_autodetect_btn.grid(row=0, column=2, sticky='w', padx=(0, 10), pady=4)

        ttk.Label(ip_grid, text="Port:").grid(row=0, column=3, sticky='w', padx=(0, 6), pady=4)
        self.tab1_port_entry = ttk.Entry(ip_grid, textvariable=self.port_tab1_var, width=8)
        self.tab1_port_entry.grid(row=0, column=4, sticky='w', padx=(0, 8), pady=4)

        action_row = ttk.Frame(self.tab1_inst_frame)
        action_row.pack(fill=tk.X, pady=(4, 0))

        self.tab1_connect_btn = ttk.Button(
            action_row,
            text="Connect Wirelessly Now",
            command=self._tab1_connect,
            state='disabled'
        )
        self.tab1_connect_btn.pack(side=tk.LEFT)

        self.tab1_status_label = ttk.Label(action_row, text="", font=('Arial', 9))
        self.tab1_status_label.pack(side=tk.LEFT, padx=(10, 0))

        self._refresh_tab1_devices()

    def _refresh_tab1_devices(self):
        if not self._is_alive():
            return
        usb_devices = self._get_usb_devices()
        values = []
        default_idx = 0
        for idx, d in enumerate(usb_devices):
            label = f"{d['id']} ({d.get('model', 'Android')}) [{d.get('status', 'device')}]"
            values.append(label)
            if self.selected_device and d['id'] == self.selected_device:
                default_idx = idx

        try:
            self.tab1_device_combo['values'] = values
            if values:
                self.tab1_device_combo.current(default_idx)
                self.tab1_enable_btn.config(state='normal')
                if not self.ip_tab1_var.get().strip():
                    dev_id = self._get_tab1_selected_id()
                    self._autodetect_ip(self.ip_tab1_var, self.tab1_status_label, dev_id)
            else:
                self.tab1_device_combo.set("No USB devices detected")
                self.tab1_enable_btn.config(state='disabled')
        except (tk.TclError, RuntimeError):
            pass

    def _on_tab1_device_changed(self):
        dev_id = self._get_tab1_selected_id()
        if dev_id:
            self._autodetect_ip(self.ip_tab1_var, self.tab1_status_label, dev_id)

    def _get_tab1_selected_id(self) -> Optional[str]:
        try:
            val = self.tab1_device_combo.get().strip()
            if not val or val == "No USB devices detected":
                return None
            return val.split()[0].strip()
        except (tk.TclError, RuntimeError):
            return None

    def _tab1_enable_tcpip(self):
        device_id = self._get_tab1_selected_id()
        if not device_id:
            messagebox.showwarning(
                "No USB Device",
                "Please connect your phone via USB cable and ensure USB debugging is authorized.",
                parent=self if self._is_alive() else None
            )
            return

        if hasattr(self.device_manager, 'is_device_ready') and not self.device_manager.is_device_ready(device_id):
            messagebox.showwarning(
                "Device Offline/Unauthorized",
                f"Device '{device_id}' is offline or unauthorized.\nPlease unlock your phone and accept the USB debugging prompt.",
                parent=self if self._is_alive() else None
            )
            return

        try:
            self.tab1_enable_btn.config(state='disabled')
            self.tab1_status_label.config(text=f"Enabling TCP/IP 5555 on {device_id}...", foreground='#1976d2')
        except (tk.TclError, RuntimeError):
            pass

        def task():
            try:
                # 1. Discover Wi-Fi / Hotspot IP while cable is plugged in
                ip = None
                try:
                    ip = self.device_manager.get_device_ip(device_id)
                except Exception:
                    pass

                # 2. Enable TCP/IP 5555
                self.device_manager.enable_tcpip(device_id, 5555)

                def on_success():
                    if not self._is_alive():
                        return
                    try:
                        self.tab1_enable_btn.config(state='normal')
                        self.tab1_connect_btn.config(state='normal')
                        if ip:
                            self.ip_tab1_var.set(ip)
                            self.ip_tab2_var.set(ip)
                            self.ip_tab3_var.set(ip)
                            self._save_last_ip(ip)

                        self.tab1_banner_label.config(
                            text=(
                                "✓ ADB TCP/IP mode is now enabled on port 5555!\n\n"
                                "1. Disconnect the USB cable from your phone now.\n"
                                "2. Keep your phone connected to the SAME Wi-Fi network or Hotspot as this PC.\n"
                                "3. Click 'Connect Wirelessly Now' below."
                            ),
                            font=('Arial', 9, 'bold'),
                            fg='#2e7d32'
                        )
                        self.tab1_status_label.config(
                            text="Unplug USB cable, then click 'Connect Wirelessly Now'.",
                            foreground='#2e7d32'
                        )
                    except (tk.TclError, RuntimeError):
                        pass

                self._safe_after(on_success)
            except Exception as e:
                err_msg = str(e)
                def on_fail():
                    if not self._is_alive():
                        return
                    try:
                        self.tab1_enable_btn.config(state='normal')
                        self.tab1_status_label.config(text="Failed to enable TCP/IP mode.", foreground='#d32f2f')
                        messagebox.showerror(
                            "TCP/IP Mode Error",
                            f"Failed to enable TCP/IP 5555 on device '{device_id}':\n\n{err_msg}",
                            parent=self if self._is_alive() else None
                        )
                    except (tk.TclError, RuntimeError):
                        pass
                self._safe_after(on_fail)

        threading.Thread(target=task, daemon=True).start()

    def _tab1_connect(self):
        ip = self.ip_tab1_var.get().strip()
        port_str = self.port_tab1_var.get().strip() or "5555"

        if not ip:
            messagebox.showwarning(
                "Missing IP",
                "Please enter your device's Wi-Fi / Hotspot IP address, or click 'Auto-Detect'.",
                parent=self if self._is_alive() else None
            )
            return

        try:
            port = int(port_str)
        except ValueError:
            messagebox.showwarning("Invalid Port", "Port must be a valid number.", parent=self if self._is_alive() else None)
            return

        self._save_last_ip(ip)
        try:
            self.tab1_connect_btn.config(state='disabled')
            self.tab1_status_label.config(text=f"Connecting to {ip}:{port}...", foreground='#1976d2')
        except (tk.TclError, RuntimeError):
            pass

        def task():
            try:
                out = self.device_manager.connect_device(ip, port)
                def on_success():
                    if not self._is_alive():
                        return
                    try:
                        self.tab1_status_label.config(text=f"✓ Connected to {ip}:{port}!", foreground='#2e7d32')
                        self.tab1_connect_btn.config(state='normal')
                        if self.on_connected_callback:
                            self.on_connected_callback()
                        self._safe_after(self._safe_destroy, 1200)
                    except (tk.TclError, RuntimeError):
                        pass
                self._safe_after(on_success)
            except Exception as e:
                err_msg = str(e)
                def on_fail():
                    if not self._is_alive():
                        return
                    try:
                        self.tab1_connect_btn.config(state='normal')
                        self.tab1_status_label.config(text="Connection failed.", foreground='#d32f2f')
                        messagebox.showerror(
                            "Wireless Connection Failed",
                            f"Failed to connect to {ip}:{port}:\n\n{err_msg}\n\n"
                            f"Troubleshooting tips:\n"
                            f"1. Make sure USB cable is unplugged.\n"
                            f"2. Ensure phone and PC are on the EXACT same Wi-Fi or Hotspot.\n"
                            f"3. Verify device IP address (click 'Auto-Detect' or check phone status).",
                            parent=self if self._is_alive() else None
                        )
                    except (tk.TclError, RuntimeError):
                        pass
                self._safe_after(on_fail)

        threading.Thread(target=task, daemon=True).start()
