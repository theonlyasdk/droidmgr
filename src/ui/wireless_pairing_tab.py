"""Pair-with-code tab (Android 11+) for the wireless connection dialog."""

import threading
import tkinter as tk
from tkinter import ttk, messagebox


class WirelessPairingMixin:
    """Tab 3 (pairing code) methods for ConnectWirelesslyDialog."""


    # -------------------------------------------------------------------------
    # TAB 3: Pair with Code (Android 11+)
    # -------------------------------------------------------------------------
    def _build_tab3(self):
        header_frame = ttk.Frame(self.tab3)
        header_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(
            header_frame,
            text="Wireless Debugging via Pairing Code (Android 11+)",
            font=('Arial', 11, 'bold')
        ).pack(anchor='w')

        ttk.Label(
            header_frame,
            text="Pair and connect over Wi-Fi / Hotspot without ever needing a USB cable.",
            font=('Arial', 9)
        ).pack(anchor='w', pady=(2, 0))

        # Instructions Step-by-Step
        steps_frame = ttk.LabelFrame(self.tab3, text="How to Pair on Android 11+", padding=10)
        steps_frame.pack(fill=tk.X, pady=(0, 10))

        steps_text = (
            "1. Connect phone and PC to the SAME Wi-Fi network or Hotspot.\n"
            "2. On phone: Settings > Developer Options > Wireless Debugging (turn ON).\n"
            "3. Tap 'Pair device with pairing code' to show the 6-digit code and pairing port.\n"
            "4. Enter the details below and click 'Pair & Connect'."
        )
        ttk.Label(
            steps_frame,
            text=steps_text,
            font=('Arial', 9),
            justify=tk.LEFT,
            wraplength=540
        ).pack(anchor='w')

        # Input Fields
        input_frame = ttk.LabelFrame(self.tab3, text="Pairing Credentials", padding=10)
        input_frame.pack(fill=tk.X, pady=(0, 10))

        grid = ttk.Frame(input_frame)
        grid.pack(fill=tk.X)

        # Row 0: Device IP & Pairing Port
        ttk.Label(grid, text="Device IP:").grid(row=0, column=0, sticky='w', padx=(0, 6), pady=4)
        self.tab3_ip_entry = ttk.Entry(grid, textvariable=self.ip_tab3_var, width=16)
        self.tab3_ip_entry.grid(row=0, column=1, sticky='w', padx=(0, 6), pady=4)

        self.tab3_autodetect_btn = ttk.Button(
            grid,
            text="Auto-Detect",
            command=lambda: self._autodetect_ip(self.ip_tab3_var, self.tab3_status_label)
        )
        self.tab3_autodetect_btn.grid(row=0, column=2, sticky='w', padx=(0, 10), pady=4)

        ttk.Label(grid, text="Pairing Port:").grid(row=0, column=3, sticky='w', padx=(0, 6), pady=4)
        self.tab3_pair_port_entry = ttk.Entry(grid, textvariable=self.pair_port_tab3_var, width=8)
        self.tab3_pair_port_entry.grid(row=0, column=4, sticky='w', pady=4)

        # Row 1: Pairing Code & Connect Port
        ttk.Label(grid, text="Pairing Code:").grid(row=1, column=0, sticky='w', padx=(0, 6), pady=4)
        self.tab3_code_entry = ttk.Entry(grid, textvariable=self.pair_code_tab3_var, width=16)
        self.tab3_code_entry.grid(row=1, column=1, sticky='w', padx=(0, 6), pady=4)

        ttk.Label(grid, text="Connect Port:").grid(row=1, column=3, sticky='w', padx=(0, 6), pady=4)
        self.tab3_connect_port_entry = ttk.Entry(grid, textvariable=self.connect_port_tab3_var, width=8)
        self.tab3_connect_port_entry.grid(row=1, column=4, sticky='w', pady=4)

        help_note = ttk.Label(
            input_frame,
            text=(
                "* Pairing Port is the port shown in the popup dialog with the 6-digit code.\n"
                "* Connect Port is shown on the main Wireless Debugging screen (leave blank if same)."
            ),
            font=('Arial', 8, 'italic'),
            foreground='#666666',
            wraplength=520
        )
        help_note.pack(anchor='w', pady=(4, 0))

        # Action Buttons & Status
        action_row = ttk.Frame(self.tab3)
        action_row.pack(fill=tk.X, pady=(4, 0))

        self.tab3_pair_btn = ttk.Button(action_row, text="Pair & Connect", command=self._tab3_pair_and_connect)
        self.tab3_pair_btn.pack(side=tk.LEFT)

        self.tab3_status_label = ttk.Label(action_row, text="", font=('Arial', 9))
        self.tab3_status_label.pack(side=tk.LEFT, padx=(10, 0))

    def _tab3_pair_and_connect(self):
        ip = self.ip_tab3_var.get().strip()
        pair_port_str = self.pair_port_tab3_var.get().strip()
        code = self.pair_code_tab3_var.get().strip()
        connect_port_str = self.connect_port_tab3_var.get().strip() or pair_port_str

        if not ip:
            messagebox.showwarning(
                "Missing IP",
                "Please enter the device IP address, or click 'Auto-Detect'.",
                parent=self if self._is_alive() else None
            )
            return

        if not pair_port_str:
            messagebox.showwarning(
                "Missing Pairing Port",
                "Please enter the pairing port shown in the 'Pair with code' dialog on your phone.",
                parent=self if self._is_alive() else None
            )
            return

        if not code:
            messagebox.showwarning(
                "Missing Pairing Code",
                "Please enter the 6-digit pairing code shown on your phone screen.",
                parent=self if self._is_alive() else None
            )
            return

        try:
            pair_port = int(pair_port_str)
        except ValueError:
            messagebox.showwarning("Invalid Port", "Pairing port must be a number.", parent=self if self._is_alive() else None)
            return

        try:
            connect_port = int(connect_port_str)
        except ValueError:
            messagebox.showwarning("Invalid Port", "Connect port must be a number.", parent=self if self._is_alive() else None)
            return

        self._save_last_ip(ip)
        try:
            self.tab3_pair_btn.config(state='disabled')
            self.tab3_status_label.config(
                text=f"Pairing with {ip}:{pair_port} using code {code}...",
                foreground='#1976d2'
            )
        except (tk.TclError, RuntimeError):
            pass

        def task():
            try:
                # Step 1: Pair
                pair_output = self.device_manager.pair_device(ip, pair_port, code)
                
                def on_paired():
                    if not self._is_alive():
                        return
                    try:
                        self.tab3_status_label.config(
                            text=f"✓ Paired! Connecting to {ip}:{connect_port}...",
                            foreground='#1976d2'
                        )
                    except (tk.TclError, RuntimeError):
                        pass

                self._safe_after(on_paired)

                # Step 2: Connect
                connect_output = self.device_manager.connect_device(ip, connect_port)

                def on_success():
                    if not self._is_alive():
                        return
                    try:
                        self.tab3_status_label.config(
                            text=f"✓ Paired & Connected to {ip}:{connect_port}!",
                            foreground='#2e7d32'
                        )
                        self.tab3_pair_btn.config(state='normal')
                        if self.on_connected_callback:
                            self.on_connected_callback()
                        self._safe_after(self._safe_destroy, 1500)
                    except (tk.TclError, RuntimeError):
                        pass

                self._safe_after(on_success)

            except Exception as e:
                err_msg = str(e)
                def on_fail():
                    if not self._is_alive():
                        return
                    try:
                        self.tab3_pair_btn.config(state='normal')
                        self.tab3_status_label.config(text="Pairing or connection failed.", foreground='#d32f2f')
                        messagebox.showerror(
                            "Pairing Error",
                            f"Failed to pair or connect with {ip}:\n\n{err_msg}\n\n"
                            f"Troubleshooting:\n"
                            f"1. Make sure the pairing dialog is still OPEN on your phone screen.\n"
                            f"2. Double check the 6-digit code and pairing port.\n"
                            f"3. Check if 'Connect Port' matches the port on the main Wireless Debugging screen.",
                            parent=self if self._is_alive() else None
                        )
                    except (tk.TclError, RuntimeError):
                        pass
                self._safe_after(on_fail)

        threading.Thread(target=task, daemon=True).start()
