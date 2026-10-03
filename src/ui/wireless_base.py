"""Dialog shell and shared helpers for wireless ADB connections."""

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Callable, List, Dict

from core import ConfigManager, DeviceManager
from .dpi import setup_window_dpi, scale_size


class WirelessBaseMixin:
    """Shell, lifecycle helpers, and tab container for ConnectWirelesslyDialog."""


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
