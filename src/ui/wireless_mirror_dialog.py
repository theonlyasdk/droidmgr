"""One-stop wireless mirroring: adb connect to a device's IP, then mirror.

The full 'Connect Wirelessly...' dialog covers pairing, the TCP/IP 5555
switch and everything else; this one is the quick path for a device whose
address is already known. The caller remembers the last address per device
and mirrors the connection once it completes.
"""

import threading
import tkinter as tk
from tkinter import ttk

from .dpi import setup_window_dpi


class WirelessMirrorDialog(tk.Toplevel):
    def __init__(self, parent, device_manager, device_id: str,
                 initial_address: str = '', on_connected=None):
        super().__init__(parent)
        self.title('Wireless Mirror')
        self.resizable(False, False)
        self.transient(parent)

        self.device_manager = device_manager
        self._on_connected = on_connected

        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame,
                  text=f"Mirror '{device_id}' over Wi-Fi",
                  font=('', 10, 'bold')).pack(anchor='w', pady=(0, 4))

        ttk.Label(frame,
                  text="adb connects to the phone's wireless-debugging or "
                       "TCP/IP listener, then scrcpy mirrors that connection. "
                       "Pairing (Android 11+) and switching the phone into "
                       "TCP/IP mode live in the fuller 'Connect Wirelessly...' "
                       "dialog.",
                  wraplength=400, justify='left').pack(anchor='w', pady=(0, 8))

        row = ttk.Frame(frame)
        row.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(row, text='Device address:').pack(side=tk.LEFT, padx=(0, 6))
        self._address_var = tk.StringVar(value=initial_address)
        self._address_entry = ttk.Entry(row, textvariable=self._address_var,
                                        width=28)
        self._address_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._address_entry.bind('<Return>', lambda event: self._connect())

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(6, 0))
        self._connect_btn = ttk.Button(buttons, text='Connect & Mirror',
                                       command=self._connect)
        self._connect_btn.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(buttons, text='Cancel',
                   command=self._close).pack(side=tk.LEFT)

        self._status = tk.StringVar(self, '')
        ttk.Label(frame, textvariable=self._status, wraplength=400,
                  font=('', 9, 'italic')).pack(anchor='w', pady=(8, 0))

        setup_window_dpi(self, base_width=460, base_height=190,
                         min_width=420, min_height=160, parent=parent)
        self.grab_set()
        self.focus_set()
        self._address_entry.focus_set()

    def _parse_address(self, raw: str):
        """'host' or 'host:port' -> (host, port); None when malformed.

        A bare address gets the classic 5555 port.
        """
        raw = raw.strip()
        if not raw:
            return None
        host, port = raw, 5555
        if ':' in raw:
            host, _, port_text = raw.rpartition(':')
            host, port_text = host.strip(), port_text.strip()
            if not host or not port_text.isdigit():
                return None
            port = int(port_text)
        return host, port

    def _connect(self):
        raw = self._address_var.get()
        parsed = self._parse_address(raw)
        if parsed is None:
            self._status.set('The address must be host or host:port - '
                             'for example 192.168.1.10 or 192.168.1.10:5555.')
            return
        host, port = parsed
        address = f'{host}:{port}'

        self._status.set(f"Connecting to {address}...")
        self._connect_btn.state(['disabled'])
        self._address_entry.state(['disabled'])

        def task():
            try:
                output = self.device_manager.connect_device(host, port)
            except Exception as e:
                def fail():
                    self._status.set(f"Connect failed: {e}")
                    self._connect_btn.state(['!disabled'])
                    self._address_entry.state(['!disabled'])
                self.after(0, fail)
                return

            def done():
                self._status.set((output or 'connected').strip())
                try:
                    if self._on_connected:
                        self._on_connected(address)
                finally:
                    self._close()

            self.after(0, done)

        threading.Thread(target=task, daemon=True).start()

    def _close(self):
        self.grab_release()
        self.destroy()
