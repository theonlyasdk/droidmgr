"""Direct IP connect tab for the wireless connection dialog."""

import threading
import tkinter as tk
from tkinter import ttk, messagebox


class WirelessDirectTabMixin:
    """Tab 2 (direct IP) methods for ConnectWirelesslyDialog."""


    # -------------------------------------------------------------------------
    # TAB 2: Direct IP Connect
    # -------------------------------------------------------------------------
    def _build_tab2(self):
        header_frame = ttk.Frame(self.tab2)
        header_frame.pack(fill=tk.X, pady=(0, 15))

        ttk.Label(
            header_frame,
            text="Direct Connection via IP Address",
            font=('Arial', 11, 'bold')
        ).pack(anchor='w')

        ttk.Label(
            header_frame,
            text="Connect directly to an Android device that already has wireless ADB / TCP/IP enabled (e.g. over Hotspot or Wi-Fi).",
            font=('Arial', 9),
            wraplength=540
        ).pack(anchor='w', pady=(2, 0))

        form_frame = ttk.LabelFrame(self.tab2, text="Connection Details", padding=12)
        form_frame.pack(fill=tk.X, pady=(0, 15))

        grid = ttk.Frame(form_frame)
        grid.pack(fill=tk.X)

        ttk.Label(grid, text="Device IP:").grid(row=0, column=0, sticky='w', padx=(0, 6), pady=6)
        self.tab2_ip_entry = ttk.Entry(grid, textvariable=self.ip_tab2_var, width=18)
        self.tab2_ip_entry.grid(row=0, column=1, sticky='w', padx=(0, 6), pady=6)

        self.tab2_autodetect_btn = ttk.Button(
            grid,
            text="Auto-Detect",
            command=lambda: self._autodetect_ip(self.ip_tab2_var, self.tab2_status_label)
        )
        self.tab2_autodetect_btn.grid(row=0, column=2, sticky='w', padx=(0, 10), pady=6)

        ttk.Label(grid, text="Port:").grid(row=0, column=3, sticky='w', padx=(0, 6), pady=6)
        self.tab2_port_entry = ttk.Entry(grid, textvariable=self.port_tab2_var, width=8)
        self.tab2_port_entry.grid(row=0, column=4, sticky='w', pady=6)

        hint = ttk.Label(
            form_frame,
            text="Default port is 5555. If connected via phone hotspot, click 'Auto-Detect' to fetch the phone's gateway IP.",
            font=('Arial', 8, 'italic'),
            foreground='#666666'
        )
        hint.pack(anchor='w', pady=(6, 0))

        btn_row = ttk.Frame(self.tab2)
        btn_row.pack(fill=tk.X, pady=(5, 0))

        self.tab2_connect_btn = ttk.Button(btn_row, text="Connect", command=self._tab2_connect)
        self.tab2_connect_btn.pack(side=tk.LEFT)

        self.tab2_status_label = ttk.Label(btn_row, text="", font=('Arial', 9))
        self.tab2_status_label.pack(side=tk.LEFT, padx=(10, 0))

    def _tab2_connect(self):
        ip = self.ip_tab2_var.get().strip()
        port_str = self.port_tab2_var.get().strip() or "5555"

        if not ip:
            messagebox.showwarning(
                "Missing IP",
                "Please enter the device Wi-Fi or Hotspot IP address, or click 'Auto-Detect'.",
                parent=self if self._is_alive() else None
            )
            return

        try:
            port = int(port_str)
        except ValueError:
            messagebox.showwarning("Invalid Port", "Port must be an integer.", parent=self if self._is_alive() else None)
            return

        self._save_last_ip(ip)
        try:
            self.tab2_connect_btn.config(state='disabled')
            self.tab2_status_label.config(text=f"Connecting to {ip}:{port}...", foreground='#1976d2')
        except (tk.TclError, RuntimeError):
            pass

        def task():
            try:
                out = self.device_manager.connect_device(ip, port)
                def on_success():
                    if not self._is_alive():
                        return
                    try:
                        self.tab2_status_label.config(text=f"✓ Connected: {out}", foreground='#2e7d32')
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
                        self.tab2_status_label.config(text="Connection failed.", foreground='#d32f2f')
                        self.tab2_connect_btn.config(state='normal')
                        messagebox.showerror(
                            "Connection Failed",
                            f"Failed to connect to {ip}:{port}:\n\n{err_msg}\n\n"
                            f"Make sure:\n"
                            f"1. Wireless debugging / TCP/IP is active on the phone.\n"
                            f"2. Phone and PC are connected to the SAME Wi-Fi network or Hotspot.",
                            parent=self if self._is_alive() else None
                        )
                    except (tk.TclError, RuntimeError):
                        pass
                self._safe_after(on_fail)

        threading.Thread(target=task, daemon=True).start()
