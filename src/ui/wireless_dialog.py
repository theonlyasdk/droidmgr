"""Dialog for configuring and connecting to Android devices wirelessly via ADB TCP/IP and Wireless Pairing."""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
from typing import Optional, Callable, List, Dict

from core import ConfigManager, DeviceManager
from .dpi import setup_window_dpi, scale_size


class ConnectWirelesslyDialog(tk.Toplevel):
    """3-Tabbed Unified Wireless ADB Connection Dialog:
    - Tab 1: Via USB (TCP/IP 5555 setup & connect)
    - Tab 2: Direct IP Connect (manual IP:Port)
    - Tab 3: Pair with Code (Android 11+ wireless debugging)
    """

    def __init__(
        self,
        parent: tk.Misc,
        device_manager: DeviceManager,
        selected_device: Optional[str] = None,
        on_connected_callback: Optional[Callable[[], None]] = None,
        initial_tab: Optional[int] = None,
        default_ip: str = ""
    ):
        super().__init__(parent)
        self.title("Connect Wirelessly to Android")
        self.resizable(True, True)
        self.transient(parent)

        self.device_manager = device_manager
        self.selected_device = selected_device
        self.on_connected_callback = on_connected_callback
        self.config = ConfigManager()

        # Load last known IP or auto-detect from network / hotspot
        last_ip = default_ip or self.config.get('wireless', 'last_ip', '')
        if not last_ip:
            try:
                last_ip = self.device_manager.get_device_ip(self.selected_device) or ""
            except Exception:
                last_ip = ""

        self.ip_tab1_var = tk.StringVar(value=last_ip)
        self.port_tab1_var = tk.StringVar(value="5555")

        self.ip_tab2_var = tk.StringVar(value=last_ip)
        self.port_tab2_var = tk.StringVar(value="5555")

        self.ip_tab3_var = tk.StringVar(value=last_ip)
        self.pair_port_tab3_var = tk.StringVar(value="")
        self.pair_code_tab3_var = tk.StringVar(value="")
        self.connect_port_tab3_var = tk.StringVar(value="")

        self._create_widgets()
        setup_window_dpi(self, base_width=610, base_height=550, min_width=530, min_height=480, parent=parent)

        # Decide initial tab
        if initial_tab is not None:
            self.notebook.select(initial_tab)
        else:
            usb_devices = self._get_usb_devices()
            if usb_devices:
                self.notebook.select(0)
            else:
                self.notebook.select(1)

        try:
            if parent and hasattr(parent, 'winfo_viewable') and parent.winfo_viewable():
                self.wait_visibility()
            self.grab_set()
        except Exception:
            pass
        self.bind('<Escape>', lambda e: self.destroy())

    def _is_alive(self) -> bool:
        """Check if this dialog window and its widgets are still valid and active."""
        try:
            return bool(self.winfo_exists())
        except Exception:
            return False

    def _safe_destroy(self):
        """Safely destroy this window if it is still alive."""
        if self._is_alive():
            try:
                self.destroy()
            except Exception:
                pass

    def _safe_after(self, fn, ms: int = 0):
        """Schedule a function on the main thread only if dialog is still alive."""
        if not self._is_alive():
            return

        def wrapped():
            if self._is_alive():
                try:
                    fn()
                except (tk.TclError, RuntimeError):
                    pass

        try:
            self.after(ms, wrapped)
        except (tk.TclError, RuntimeError):
            pass

    def _get_usb_devices(self) -> List[Dict[str, str]]:
        """Get connected devices that are connected via USB (not network IP:port)."""
        try:
            devices = self.device_manager.get_devices()
            return [d for d in devices if ":" not in d['id']]
        except Exception:
            return []

    def _save_last_ip(self, ip: str):
        if ip:
            try:
                self.config.set('wireless', 'last_ip', ip.strip())
            except Exception:
                pass

    def _autodetect_ip(self, target_var: tk.StringVar, status_label: Optional[ttk.Label] = None, dev_id: Optional[str] = None):
        """Asynchronously detect the device's hotspot or Wi-Fi IP address."""
        if status_label and self._is_alive():
            try:
                status_label.config(text="Detecting phone IP (hotspot / Wi-Fi)...", foreground='#1976d2')
            except (tk.TclError, RuntimeError):
                pass

        def task():
            try:
                dev = dev_id or self.selected_device
                ip = self.device_manager.get_device_ip(dev)
                def on_done():
                    if not self._is_alive():
                        return
                    try:
                        if ip:
                            target_var.set(ip)
                            if not self.ip_tab1_var.get().strip():
                                self.ip_tab1_var.set(ip)
                            if not self.ip_tab2_var.get().strip():
                                self.ip_tab2_var.set(ip)
                            if not self.ip_tab3_var.get().strip():
                                self.ip_tab3_var.set(ip)
                            self._save_last_ip(ip)
                            if status_label:
                                status_label.config(text=f"✓ Detected phone IP: {ip}", foreground='#2e7d32')
                        else:
                            if status_label:
                                status_label.config(text="Could not auto-detect IP. Check phone Wi-Fi/Hotspot settings.", foreground='#d32f2f')
                    except (tk.TclError, RuntimeError):
                        pass
                self._safe_after(on_done)
            except Exception as e:
                err_msg = str(e)
                def on_err():
                    if not self._is_alive():
                        return
                    try:
                        if status_label:
                            status_label.config(text=f"Detection error: {err_msg}", foreground='#d32f2f')
                    except (tk.TclError, RuntimeError):
                        pass
                self._safe_after(on_err)

        threading.Thread(target=task, daemon=True).start()

    def _create_widgets(self):
        container = ttk.Frame(self, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        self.notebook = ttk.Notebook(container)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Create the 3 tabs
        self.tab1 = ttk.Frame(self.notebook, padding=12)
        self.tab2 = ttk.Frame(self.notebook, padding=12)
        self.tab3 = ttk.Frame(self.notebook, padding=12)

        self.notebook.add(self.tab1, text="1. Via USB (TCP/IP)")
        self.notebook.add(self.tab2, text="2. Direct IP Connect")
        self.notebook.add(self.tab3, text="3. Pair with Code (Android 11+)")

        self._build_tab1()
        self._build_tab2()
        self._build_tab3()

        # Shared Bottom Status and Close Frame
        bottom_frame = ttk.Frame(container)
        bottom_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(4, 0))

        self.global_status_label = ttk.Label(bottom_frame, text="", font=('Arial', 9))
        self.global_status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.close_btn = ttk.Button(bottom_frame, text="Close", command=self.destroy)
        self.close_btn.pack(side=tk.RIGHT)

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


# Backward-compatible aliases
WirelessADBSetupDialog = ConnectWirelesslyDialog
ConnectWirelessDialog = ConnectWirelesslyDialog
