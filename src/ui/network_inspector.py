"""Network inspector tab for the main window and device details dialog.

Answers questions about a device's networking: Wi-Fi state, cellular state,
signal strength, link speed, IP addresses, DNS, routes, data usage,
connectivity history, active connections, and latency diagnostics.
Supports exporting network diagnostic reports with automatic redaction of
sensitive identifiers (SSIDs, BSSIDs, MAC addresses, public IPs).
"""

import ipaddress
import json
import re
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# Enough rows to read a long list without scrolling; the rest is one scroll away.
TABLE_HEIGHT = 10

# The supplicant states that mean a network is actually in use.
_CONNECTED_STATES = ('COMPLETED',)

# A reading at or below this is what a disconnected radio reports, not a signal.
_NO_SIGNAL_DBM = -127

MISSING = 'Unavailable'


def _format_bytes(num_bytes):
    """Render a byte count as a short human-readable size such as '41.2 MB'."""
    size = float(num_bytes or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            return f"{int(size)} {unit}" if unit == 'B' else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _format_ms(value):
    """Render a round-trip time, or say plainly that there was not one."""
    return f"{value:.1f} ms" if value is not None else '-'


def _is_private_ip(ip_str):
    """Check if an IP address string is private, loopback, or link-local."""
    try:
        clean = ip_str.split('/')[0].strip()
        ip = ipaddress.ip_address(clean)
        return (ip.is_private or ip.is_loopback or ip.is_link_local
                or clean in ('8.8.8.8', '8.8.4.4', '1.1.1.1', '1.0.0.1', '9.9.9.9', '0.0.0.0', '255.255.255.255'))
    except ValueError:
        return False


def sanitize_network_data(val, ssid=None):
    """Recursively mask sensitive identifiers (SSID, BSSID, MAC, public IPs)."""
    if isinstance(val, str):
        # Mask MAC addresses / BSSIDs (e.g. 02:00:00:00:00:00 or aa-bb-cc-dd-ee-ff)
        val = re.sub(r'\b([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})\b', 'XX:XX:XX:XX:XX:XX', val)
        # Mask explicit SSID if provided
        if ssid and len(ssid) > 1:
            val = val.replace(ssid, '[REDACTED_SSID]')
        # Mask public IPv4 addresses
        def _repl_ipv4(m):
            ip_str = m.group(0)
            if not _is_private_ip(ip_str):
                parts = ip_str.split('.')
                return f"{parts[0]}.{parts[1]}.***.***"
            return ip_str
        val = re.sub(r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b',
                     _repl_ipv4, val)
        return val
    elif isinstance(val, list):
        return [sanitize_network_data(x, ssid) for x in val]
    elif isinstance(val, dict):
        new_d = {}
        for k, v in val.items():
            if k in ('bssid', 'mac') and isinstance(v, str) and v:
                new_d[k] = 'XX:XX:XX:XX:XX:XX'
            elif k == 'ssid' and isinstance(v, str) and v:
                new_d[k] = '[REDACTED_SSID]'
            else:
                new_d[k] = sanitize_network_data(v, ssid)
        return new_d
    return val


class _SortableTree(ttk.Frame):
    """A treeview whose rows reorder when a heading is clicked."""

    def __init__(self, parent, columns, sort_map=None, default_sort=None,
                 default_reverse=False, height=TABLE_HEIGHT):
        super().__init__(parent)
        self.sort_map = sort_map or {}
        self.sort_column = None
        self.sort_reverse = False
        self.rows = {}

        self.tree = ttk.Treeview(
            self, columns=[key for key, _, _, _ in columns],
            show='headings', height=height, selectmode='browse')

        for key, title, width, anchor in columns:
            self.tree.heading(key, text=title,
                              command=lambda column=key: self.sort_by(column))
            self.tree.column(key, width=width, anchor=anchor,
                             stretch=(key == columns[0][0]))

        vertical = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vertical.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        if default_sort:
            self.sort_column = default_sort
            self.sort_reverse = default_reverse

    def clear(self):
        self.rows.clear()
        for item in self.tree.get_children(''):
            self.tree.delete(item)

    def fill(self, rows, formatter):
        """Show each row, keeping the raw data so the sort has something to use."""
        yview = self.tree.yview()
        self.clear()
        for row in rows:
            item = self.tree.insert('', 'end', values=formatter(row))
            self.rows[item] = row
        self._apply_sort()
        if yview and yview[0] > 0:
            try:
                self.tree.yview_moveto(yview[0])
            except Exception:
                pass

    def _value_for(self, row, column):
        getter = self.sort_map.get(column)
        if getter is None:
            return row.get(column)
        return getter(row)

    def _apply_sort(self):
        if not self.sort_column:
            return

        column = self.sort_column

        def sort_key(item):
            value = self._value_for(self.rows.get(item, {}), column)
            if isinstance(value, (int, float)):
                return (1, float(value))
            return (0, '' if value is None else str(value).lower())

        items = list(self.rows)
        items.sort(key=sort_key, reverse=self.sort_reverse)
        for index, item in enumerate(items):
            self.tree.move(item, '', index)

    def sort_by(self, column):
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = self._opens_on_numbers(column)
        self._apply_sort()

    def _opens_on_numbers(self, column):
        for row in self.rows.values():
            return isinstance(self._value_for(row, column), (int, float))
        return False


class NetworkInspector(ttk.Frame):
    """The network inspector: Wi-Fi, cellular, routes, data usage, history, sockets."""

    def __init__(self, parent, device_id=None, device_manager=None,
                 set_status_callback=None, show_error_callback=None,
                 require_device_callback=None, auto_load=False,
                 config=None):
        super().__init__(parent)
        self.device_id = device_id
        self.device_manager = device_manager
        self.set_status = set_status_callback
        self.show_error = show_error_callback
        self.require_device = require_device_callback
        self.config = config
        if self.config is None:
            try:
                from core.config_manager import ConfigManager
                self.config = ConfigManager()
            except Exception:
                self.config = None

        self._gateway = ''
        self._connection_busy = False
        self._traffic_busy = False
        self._sockets_busy = False
        self._routes_busy = False
        self._history_busy = False
        self._requests_busy = False
        self._ping_busy = False
        self._poll_job = None
        self.loaded = False

        # Cached raw data for export
        self._cached_info = {}
        self._cached_traffic = []
        self._cached_sockets = []
        self._cached_routes = []
        self._cached_history = []
        self._cached_requests = []
        self._cached_pings = []

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        self._create_toolbar()
        self._create_summary_cards()
        self._create_tables()

        self.bind('<Destroy>', lambda event: self.stop_polling())

        if auto_load and self.device_id:
            self.load()

    # --- layout ------------------------------------------------------------

    def _create_toolbar(self):
        toolbar = ttk.Frame(self, padding=(4, 2, 4, 6))
        toolbar.grid(row=0, column=0, sticky='ew')

        self.refresh_all_btn = ttk.Button(
            toolbar, text='Refresh All', command=self.refresh_all, width=12)
        self.refresh_all_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.export_btn = ttk.Button(
            toolbar, text='Export Report...', command=self.export_report, width=15)
        self.export_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.hide_sensitive_var = tk.BooleanVar(value=True)
        self.hide_sensitive_cb = ttk.Checkbutton(
            toolbar, text='Hide sensitive network identifiers (SSID, BSSID, MAC, IP)',
            variable=self.hide_sensitive_var)
        self.hide_sensitive_cb.pack(side=tk.LEFT, padx=(0, 10))

        self.status_label = ttk.Label(toolbar, text='', foreground='gray')
        self.status_label.pack(side=tk.RIGHT, padx=4)

    def _create_summary_cards(self):
        container = ttk.Frame(self)
        container.grid(row=1, column=0, sticky='ew', padx=4, pady=(0, 6))
        container.columnconfigure(0, weight=1, uniform='card')
        container.columnconfigure(1, weight=1, uniform='card')
        container.columnconfigure(2, weight=1, uniform='card')

        # Card 1: Wi-Fi
        wifi_frame = ttk.LabelFrame(container, text='Wi-Fi', padding=6)
        wifi_frame.grid(row=0, column=0, sticky='nsew', padx=(0, 4))
        wifi_frame.columnconfigure(1, weight=1)

        self.wifi_vars = {}
        wifi_fields = (
            ('radio', 'Radio:'),
            ('ssid', 'SSID:'),
            ('bssid', 'BSSID:'),
            ('state', 'State:'),
            ('signal', 'Signal:'),
            ('speed', 'Link speed:'),
            ('frequency', 'Frequency:'),
        )
        for r, (key, label) in enumerate(wifi_fields):
            ttk.Label(wifi_frame, text=label, font=('Arial', 8, 'bold')).grid(
                row=r, column=0, sticky='nw', pady=1, padx=(0, 6))
            var = tk.StringVar(value='-')
            ttk.Label(wifi_frame, textvariable=var, wraplength=180, justify=tk.LEFT).grid(
                row=r, column=1, sticky='w', pady=1)
            self.wifi_vars[key] = var

        # Card 2: Cellular
        cell_frame = ttk.LabelFrame(container, text='Cellular', padding=6)
        cell_frame.grid(row=0, column=1, sticky='nsew', padx=2)
        cell_frame.columnconfigure(1, weight=1)

        self.cell_vars = {}
        cell_fields = (
            ('sim_state', 'SIM state:'),
            ('operator', 'Carrier:'),
            ('data_state', 'Mobile data:'),
            ('network_type', 'Network type:'),
            ('signal', 'Signal:'),
        )
        for r, (key, label) in enumerate(cell_fields):
            ttk.Label(cell_frame, text=label, font=('Arial', 8, 'bold')).grid(
                row=r, column=0, sticky='nw', pady=1, padx=(0, 6))
            var = tk.StringVar(value='-')
            ttk.Label(cell_frame, textvariable=var, wraplength=180, justify=tk.LEFT).grid(
                row=r, column=1, sticky='w', pady=1)
            self.cell_vars[key] = var

        # Card 3: IP & Network
        ip_frame = ttk.LabelFrame(container, text='IP & Routing', padding=6)
        ip_frame.grid(row=0, column=2, sticky='nsew', padx=(4, 0))
        ip_frame.columnconfigure(1, weight=1)

        self.ip_vars = {}
        ip_fields = (
            ('interface', 'Interface:'),
            ('ipv4', 'IPv4:'),
            ('ipv6', 'IPv6:'),
            ('gateway', 'Gateway:'),
            ('dns', 'DNS:'),
            ('default_network', 'Default net:'),
        )
        for r, (key, label) in enumerate(ip_fields):
            ttk.Label(ip_frame, text=label, font=('Arial', 8, 'bold')).grid(
                row=r, column=0, sticky='nw', pady=1, padx=(0, 6))
            var = tk.StringVar(value='-')
            ttk.Label(ip_frame, textvariable=var, wraplength=200, justify=tk.LEFT).grid(
                row=r, column=1, sticky='w', pady=1)
            self.ip_vars[key] = var

        # Connection notice label across the bottom of cards
        self.connection_notice = ttk.Label(
            container, text='', foreground='#E65100', wraplength=750, justify=tk.LEFT)
        self.connection_notice.grid(row=1, column=0, columnspan=3, sticky='w', pady=(4, 0))

    def _create_tables(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=2, column=0, sticky='nsew', padx=4, pady=2)

        # 1. Traffic: Data usage per app
        traffic = ttk.Frame(self.notebook, padding=6)
        self.traffic_table = _SortableTree(
            traffic,
            [
                ('package', 'App', 250, 'w'),
                ('rx', 'Received', 95, 'e'),
                ('tx', 'Sent', 95, 'e'),
                ('total', 'Total', 95, 'e'),
                ('uid', 'UID', 65, 'e'),
            ],
            sort_map={
                'package': lambda row: row.get('package') or f"uid {row.get('uid')}",
                'rx': lambda row: row.get('rx_bytes', 0),
                'tx': lambda row: row.get('tx_bytes', 0),
                'total': lambda row: row.get('total_bytes', 0),
                'uid': lambda row: row.get('uid', 0),
            },
            default_sort='total',
            default_reverse=True,
            height=TABLE_HEIGHT,
        )
        self.traffic_table.pack(fill=tk.BOTH, expand=True)
        self.traffic_summary = ttk.Label(traffic, text='', foreground='gray')
        self.traffic_summary.pack(anchor='w', pady=(4, 0))
        self._add_table_controls(traffic, self.refresh_traffic, 'traffic')
        self.notebook.add(traffic, text='Data usage')

        # 2. Active Connections (Sockets)
        sockets = ttk.Frame(self.notebook, padding=6)
        self.socket_table = _SortableTree(
            sockets,
            [
                ('direction', 'Direction', 100, 'w'),
                ('protocol', 'Protocol', 68, 'w'),
                ('state', 'State', 110, 'w'),
                ('package', 'App', 190, 'w'),
                ('local', 'Local address', 160, 'w'),
                ('remote', 'Remote address', 190, 'w'),
                ('uid', 'UID', 62, 'e'),
            ],
            sort_map={
                'package': lambda row: row.get('package') or f"uid {row.get('uid')}",
                'remote': lambda row: f"{row.get('remote')}:{row.get('remote_port')}",
                'local': lambda row: f"{row.get('local')}:{row.get('local_port')}",
            },
            height=TABLE_HEIGHT,
        )
        self.socket_table.pack(fill=tk.BOTH, expand=True)
        self.socket_summary = ttk.Label(sockets, text='', foreground='gray')
        self.socket_summary.pack(anchor='w', pady=(4, 0))
        self._add_table_controls(sockets, self.refresh_connections, 'connections')
        self.notebook.add(sockets, text='Active connections')

        # 3. Routing Table
        routes = ttk.Frame(self.notebook, padding=6)
        self.routes_table = _SortableTree(
            routes,
            [
                ('destination', 'Destination / Prefix', 160, 'w'),
                ('gateway', 'Gateway', 120, 'w'),
                ('interface', 'Interface', 80, 'w'),
                ('table', 'Table', 75, 'w'),
                ('metric', 'Metric', 65, 'e'),
                ('scope', 'Scope', 75, 'w'),
                ('source', 'Source IP', 120, 'w'),
            ],
            sort_map={
                'destination': lambda r: r.get('destination', ''),
                'gateway': lambda r: r.get('gateway', ''),
                'interface': lambda r: r.get('interface', ''),
                'table': lambda r: r.get('table', ''),
                'metric': lambda r: int(r.get('metric') or 0) if (r.get('metric') or '').isdigit() else 9999,
                'scope': lambda r: r.get('scope', ''),
                'source': lambda r: r.get('source', ''),
            },
            default_sort='destination',
            height=TABLE_HEIGHT,
        )
        self.routes_table.pack(fill=tk.BOTH, expand=True)
        self.routes_summary = ttk.Label(routes, text='', foreground='gray')
        self.routes_summary.pack(anchor='w', pady=(4, 0))
        self._add_table_controls(routes, self.refresh_routes, 'routes')
        self.notebook.add(routes, text='Routes')

        # 4. Connectivity History
        history = ttk.Frame(self.notebook, padding=6)
        self.history_table = _SortableTree(
            history,
            [
                ('timestamp', 'Timestamp', 180, 'w'),
                ('type', 'Event Type', 120, 'w'),
                ('details', 'Details', 480, 'w'),
            ],
            sort_map={
                'timestamp': lambda r: r.get('timestamp', ''),
                'type': lambda r: r.get('type', ''),
                'details': lambda r: r.get('details', ''),
            },
            height=TABLE_HEIGHT,
        )
        self.history_table.pack(fill=tk.BOTH, expand=True)
        self.history_summary = ttk.Label(history, text='', foreground='gray')
        self.history_summary.pack(anchor='w', pady=(4, 0))
        self._add_table_controls(history, self.refresh_history, 'history')
        self.notebook.add(history, text='Connectivity history')

        # 5. Network Requests
        requests = ttk.Frame(self.notebook, padding=6)
        self.request_table = _SortableTree(
            requests,
            [
                ('package', 'App', 210, 'w'),
                ('internet', 'Internet', 70, 'center'),
                ('validated', 'Validated', 76, 'center'),
                ('count', 'Requests', 72, 'e'),
                ('transports', 'Transports', 120, 'w'),
                ('kinds', 'Kinds', 250, 'w'),
                ('uid', 'UID', 62, 'e'),
            ],
            sort_map={
                'package': lambda row: row.get('package') or f"uid {row.get('uid')}",
                'internet': lambda row: row.get('internet'),
                'validated': lambda row: row.get('validated'),
                'count': lambda row: row.get('count'),
            },
            height=TABLE_HEIGHT,
        )
        self.request_table.pack(fill=tk.BOTH, expand=True)
        self.request_summary = ttk.Label(requests, text='', foreground='gray')
        self.request_summary.pack(anchor='w', pady=(4, 0))
        self._add_table_controls(requests, self.refresh_requests, 'requests')
        self.notebook.add(requests, text='Network requests')

        # 6. Ping & Latency Diagnostics
        latency = ttk.Frame(self.notebook, padding=6)
        controls = ttk.Frame(latency)
        controls.pack(fill=tk.X, pady=(0, 6))

        self.ping_host_var = tk.StringVar(value='8.8.8.8')
        ttk.Label(controls, text='Host:').pack(side=tk.LEFT)
        entry = ttk.Entry(controls, textvariable=self.ping_host_var, width=18)
        entry.pack(side=tk.LEFT, padx=(6, 10))
        entry.bind('<Return>', lambda event: self.run_ping_on_entry())

        ttk.Label(controls, text='Packets:').pack(side=tk.LEFT)
        self.ping_count_var = tk.IntVar(value=4)
        self.ping_count_spin = ttk.Spinbox(
            controls, from_=1, to=10, textvariable=self.ping_count_var, width=4)
        self.ping_count_spin.pack(side=tk.LEFT, padx=(6, 12))

        self.ping_button = ttk.Button(controls, text='Run test', command=self.run_ping_on_entry, width=12)
        self.ping_button.pack(side=tk.LEFT, padx=(0, 6))

        self.ping_quick_button = ttk.Button(
            controls, text='Test route and DNS', command=self.run_ping_suite, width=20)
        self.ping_quick_button.pack(side=tk.LEFT, padx=(0, 10))

        self.ping_status = ttk.Label(controls, text='', foreground='gray')
        self.ping_status.pack(side=tk.LEFT)

        columns = [
            ('host', 'Host', 140, 'w'),
            ('loss', 'Loss', 65, 'e'),
            ('min', 'Min', 75, 'e'),
            ('avg', 'Avg', 75, 'e'),
            ('max', 'Max', 75, 'e'),
            ('jitter', 'Jitter', 75, 'e'),
            ('note', 'Result', 220, 'w'),
        ]
        self.ping_table = _SortableTree(latency, columns)
        self.ping_table.pack(fill=tk.BOTH, expand=True)
        self.notebook.add(latency, text='Ping & Latency')

    def _add_table_controls(self, parent, command, name):
        controls = ttk.Frame(parent)
        controls.pack(fill=tk.X, pady=(6, 0))
        button = ttk.Button(controls, text='Refresh', command=command, width=10)
        button.pack(side=tk.LEFT)
        status = ttk.Label(controls, text='', foreground='gray')
        status.pack(side=tk.LEFT, padx=10)
        setattr(self, f'{name}_button', button)
        setattr(self, f'{name}_status', status)

    # --- device lifecycle ---------------------------------------------------

    def set_device(self, device_id):
        """Set the active device and reload data."""
        if self.device_id == device_id and self.loaded:
            self.start_polling()
            return
        self.stop_polling()
        self.device_id = device_id
        self.loaded = False
        self._cached_info = {}
        self._cached_traffic = []
        self._cached_sockets = []
        self._cached_routes = []
        self._cached_history = []
        self._cached_requests = []
        self._cached_pings = []

        if device_id:
            self.load()
        else:
            self._clear_all()

    def _clear_all(self):
        self.stop_polling()
        for var in self.wifi_vars.values():
            var.set('-')
        for var in self.cell_vars.values():
            var.set('-')
        for var in self.ip_vars.values():
            var.set('-')
        self.connection_notice.config(text='')
        self.status_label.config(text='')
        self.traffic_table.clear()
        self.socket_table.clear()
        self.routes_table.clear()
        self.history_table.clear()
        self.request_table.clear()
        self.ping_table.clear()
        self.traffic_summary.config(text='')
        self.socket_summary.config(text='')
        self.routes_summary.config(text='')
        self.history_summary.config(text='')
        self.request_summary.config(text='')
        self.ping_status.config(text='')

    def load(self):
        """Load all network inspection data once and start polling."""
        if not self.device_id or not self.device_manager:
            return
        self.refresh_connection()
        self.refresh_traffic()
        self.refresh_connections()
        self.refresh_routes()
        self.refresh_history()
        self.refresh_requests()
        self.loaded = True
        self.start_polling()

    def refresh_all(self):
        """Refresh all network data."""
        if not self.device_id:
            if self.show_error:
                self.show_error("No device selected.")
            return
        self.refresh_connection()
        self.refresh_traffic()
        self.refresh_connections()
        self.refresh_routes()
        self.refresh_history()
        self.refresh_requests()

    def get_polling_interval_ms(self):
        """Read query interval from settings (in milliseconds)."""
        if self.config:
            try:
                sec = self.config.get('general', 'query_interval', 5)
                return max(1, int(sec)) * 1000
            except Exception:
                pass
        return 5000

    def start_polling(self):
        """Start auto-refreshing at the interval configured in settings."""
        self.stop_polling()
        if not self._is_alive() or not self.device_id:
            return
        interval = self.get_polling_interval_ms()
        self._poll_job = self.after(interval, self._poll_tick)

    def stop_polling(self):
        """Stop periodic auto-refresh."""
        if self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None

    def _poll_tick(self):
        """Periodic timer callback running at settings polling interval."""
        self._poll_job = None
        if not self._is_alive() or not self.device_id:
            return

        # Only query if the tab is visible/mapped to conserve resources
        if self.winfo_ismapped():
            # Refresh connection status (Wi-Fi, cellular, signal, link speed, IP)
            self.refresh_connection()

            # Refresh currently active subtab
            try:
                current = self.notebook.select()
                if current:
                    tab_name = self.notebook.tab(current, 'text')
                    if 'Data usage' in tab_name:
                        self.refresh_traffic()
                    elif 'Active connections' in tab_name:
                        self.refresh_connections()
                    elif 'Routes' in tab_name:
                        self.refresh_routes()
                    elif 'Connectivity history' in tab_name:
                        self.refresh_history()
                    elif 'Network requests' in tab_name:
                        self.refresh_requests()
            except Exception:
                pass

        # Reschedule next tick at current settings interval
        interval = self.get_polling_interval_ms()
        self._poll_job = self.after(interval, self._poll_tick)

    # --- threading runner ---------------------------------------------------

    def _is_alive(self):
        try:
            return self.winfo_exists()
        except tk.TclError:
            return False

    def _run(self, busy_flag, work, apply, on_error):
        """Execute on a worker thread and update UI on main thread."""
        if getattr(self, busy_flag):
            return
        setattr(self, busy_flag, True)

        def finish(callback, *args):
            setattr(self, busy_flag, False)
            callback(*args)

        def task():
            try:
                result = work()
            except Exception as exc:
                message = str(exc)
                if self._is_alive():
                    self.after(0, lambda: finish(on_error, message))
                return
            if self._is_alive():
                self.after(0, lambda: finish(apply, result))

        threading.Thread(target=task, daemon=True).start()

    # --- readers ------------------------------------------------------------

    def refresh_connection(self):
        if not self.device_id:
            return
        self.status_label.config(text='Reading connection...')

        def apply(info):
            self._cached_info = info
            self._apply_connection(info)
            sec = self.get_polling_interval_ms() // 1000
            self.status_label.config(
                text=f'Updated {time.strftime("%H:%M:%S")} (polling {sec}s)', foreground='gray')

        def on_error(message):
            self.status_label.config(text='', foreground='#C62828')
            self.connection_notice.config(
                text=f'Could not read network connection: {message}')

        self._run('_connection_busy',
                  lambda: self.device_manager.get_network_info(self.device_id),
                  apply, on_error)

    def _apply_connection(self, info):
        wifi = info.get('wifi') or {}
        cellular = info.get('cellular') or {}
        interface = info.get('active_interface') or {}

        # Wi-Fi
        radio = wifi.get('enabled')
        state = wifi.get('state') or ''
        ssid = wifi.get('ssid') or ''
        bssid = wifi.get('bssid') or ''
        rssi = wifi.get('rssi')
        speed = wifi.get('link_speed') or ''
        freq = wifi.get('frequency') or ''

        self.wifi_vars['radio'].set('On' if radio else ('Off' if radio is False else MISSING))
        self.wifi_vars['ssid'].set(ssid or 'Not connected')
        self.wifi_vars['bssid'].set(bssid or '-')
        self.wifi_vars['state'].set(state or MISSING)

        if rssi is None:
            self.wifi_vars['signal'].set(MISSING)
        elif rssi <= _NO_SIGNAL_DBM:
            self.wifi_vars['signal'].set('No signal')
        else:
            self.wifi_vars['signal'].set(f'{rssi} dBm')

        self.wifi_vars['speed'].set(speed or '-')
        self.wifi_vars['frequency'].set(freq or '-')

        # Cellular
        self.cell_vars['sim_state'].set(cellular.get('sim_state') or MISSING)
        self.cell_vars['operator'].set(cellular.get('operator') or 'No carrier')
        self.cell_vars['data_state'].set(cellular.get('data_state') or 'Disconnected')
        self.cell_vars['network_type'].set(cellular.get('network_type') or 'None')
        self.cell_vars['signal'].set(cellular.get('signal') or 'N/A')

        # IP & Routing
        self.ip_vars['ipv4'].set(', '.join(interface.get('ipv4') or []) or 'None')
        ipv6 = interface.get('ipv6') or []
        self.ip_vars['ipv6'].set(', '.join(ipv6[:2]) or 'None')

        if interface:
            parts = [interface.get('name', '')]
            if interface.get('state'):
                parts.append(interface['state'])
            if interface.get('mtu'):
                parts.append(f"MTU {interface['mtu']}")
            self.ip_vars['interface'].set(' - '.join(p for p in parts if p))
        else:
            self.ip_vars['interface'].set('No interface is up')

        self._gateway = info.get('gateway') or ''
        self.ip_vars['gateway'].set(self._gateway or 'None')

        dns = info.get('dns') or []
        self.ip_vars['dns'].set(', '.join(dns) if dns else 'None')

        default_net = info.get('default_network') or ''
        self.ip_vars['default_network'].set(
            default_net if default_net and default_net != 'none' else 'None')

        # Notices
        notes = []
        if not interface:
            notes.append('No interface holds a routable address.')
        if radio is False:
            notes.append('Wi-Fi radio is off.')
        if ssid and state not in _CONNECTED_STATES:
            notes.append(f'{ssid} is the last network used, not currently connected.')
        if default_net in ('', 'none'):
            notes.append('System reports no validated default network.')
        self.connection_notice.config(text=' '.join(notes))

    def refresh_traffic(self):
        if not self.device_id:
            return
        status = getattr(self, 'traffic_status', None)
        if status:
            status.config(text='Reading...')

        def apply(rows):
            self._cached_traffic = rows
            self.traffic_table.fill(rows, self._format_usage_row)
            rx = sum(r.get('rx_bytes', 0) for r in rows)
            tx = sum(r.get('tx_bytes', 0) for r in rows)
            if rows:
                self.traffic_summary.config(
                    text=f'{len(rows)} apps moved data since boot: '
                         f'{_format_bytes(rx)} received, {_format_bytes(tx)} sent.',
                    foreground='gray')
            else:
                self.traffic_summary.config(
                    text='No network traffic recorded since boot.', foreground='gray')
            if status:
                status.config(text='')

        def on_error(message):
            self.traffic_summary.config(
                text=f'Could not read traffic: {message}', foreground='#C62828')
            if status:
                status.config(text='')

        self._run('_traffic_busy',
                  lambda: self.device_manager.get_app_network_usage(self.device_id),
                  apply, on_error)

    @staticmethod
    def _format_usage_row(row):
        return (
            row.get('package') or f"uid {row.get('uid')} (system)",
            _format_bytes(row.get('rx_bytes', 0)),
            _format_bytes(row.get('tx_bytes', 0)),
            _format_bytes(row.get('total_bytes', 0)),
            row.get('uid', '-'),
        )

    def refresh_connections(self):
        if not self.device_id:
            return
        status = getattr(self, 'connections_status', None)
        if status:
            status.config(text='Reading...')

        def apply(rows):
            self._cached_sockets = rows
            self.socket_table.fill(rows, self._format_socket_row)
            listening = sum(1 for r in rows if r.get('direction') == 'Listening')
            connected = sum(1 for r in rows if r.get('direction') == 'Connected')
            if rows:
                self.socket_summary.config(
                    text=f'{len(rows)} sockets open: {connected} connected, {listening} listening.',
                    foreground='gray')
            else:
                self.socket_summary.config(
                    text='Device holds no open sockets.', foreground='gray')
            if status:
                status.config(text='')

        def on_error(message):
            self.socket_summary.config(
                text=f'Could not read sockets: {message}', foreground='#C62828')
            if status:
                status.config(text='')

        self._run('_sockets_busy',
                  lambda: self.device_manager.get_active_connections(self.device_id),
                  apply, on_error)

    @staticmethod
    def _format_socket_row(row):
        remote = row.get('remote', '')
        if str(row.get('remote_port', '0')) != '0':
            remote = f"{remote}:{row.get('remote_port')}"
        return (
            row.get('direction', '-'),
            row.get('protocol', '-'),
            row.get('state', '-'),
            row.get('package') or f"uid {row.get('uid')}",
            f"{row.get('local')}:{row.get('local_port')}",
            remote or '-',
            row.get('uid', '-'),
        )

    def refresh_routes(self):
        if not self.device_id:
            return
        status = getattr(self, 'routes_status', None)
        if status:
            status.config(text='Reading...')

        def apply(rows):
            self._cached_routes = rows
            self.routes_table.fill(rows, self._format_route_row)
            self.routes_summary.config(
                text=f'{len(rows)} routing table entries found.', foreground='gray')
            if status:
                status.config(text='')

        def on_error(message):
            self.routes_summary.config(
                text=f'Could not read routing table: {message}', foreground='#C62828')
            if status:
                status.config(text='')

        self._run('_routes_busy',
                  lambda: self.device_manager.get_routing_table(self.device_id),
                  apply, on_error)

    @staticmethod
    def _format_route_row(row):
        return (
            row.get('destination') or '-',
            row.get('gateway') or '-',
            row.get('interface') or '-',
            row.get('table') or '-',
            row.get('metric') or '-',
            row.get('scope') or '-',
            row.get('source') or '-',
        )

    def refresh_history(self):
        if not self.device_id:
            return
        status = getattr(self, 'history_status', None)
        if status:
            status.config(text='Reading...')

        def apply(rows):
            self._cached_history = rows
            self.history_table.fill(rows, self._format_history_row)
            self.history_summary.config(
                text=f'{len(rows)} connectivity log events retrieved.', foreground='gray')
            if status:
                status.config(text='')

        def on_error(message):
            self.history_summary.config(
                text=f'Could not read connectivity history: {message}', foreground='#C62828')
            if status:
                status.config(text='')

        self._run('_history_busy',
                  lambda: self.device_manager.get_connectivity_history(self.device_id, limit=100),
                  apply, on_error)

    @staticmethod
    def _format_history_row(row):
        return (
            row.get('timestamp') or '-',
            row.get('type') or '-',
            row.get('details') or '-',
        )

    def refresh_requests(self):
        if not self.device_id:
            return
        status = getattr(self, 'requests_status', None)
        if status:
            status.config(text='Reading...')

        def apply(rows):
            self._cached_requests = rows
            self.request_table.fill(rows, self._format_request_row)
            wanting = sum(1 for r in rows if r.get('internet'))
            if rows:
                self.request_summary.config(
                    text=f'{len(rows)} owners hold network requests, {wanting} ask for internet.',
                    foreground='gray')
            else:
                self.request_summary.config(
                    text='No network requests are registered.', foreground='gray')
            if status:
                status.config(text='')

        def on_error(message):
            self.request_summary.config(
                text=f'Could not read network requests: {message}', foreground='#C62828')
            if status:
                status.config(text='')

        self._run('_requests_busy',
                  lambda: self.device_manager.get_network_requests(self.device_id),
                  apply, on_error)

    @staticmethod
    def _format_request_row(row):
        return (
            row.get('package') or f"uid {row.get('uid')} (system)",
            'yes' if row.get('internet') else 'no',
            'yes' if row.get('validated') else 'no',
            row.get('count', '-'),
            row.get('transports') or 'any',
            ', '.join((row.get('kinds') or '').split(', ')) or '-',
            row.get('uid', '-'),
        )

    # --- latency & ping ----------------------------------------------------

    def run_ping_on_entry(self):
        host = self.ping_host_var.get().strip()
        if not host:
            self.ping_status.config(text='Enter a host first', foreground='#C62828')
            return
        self._run_pings([(host, host)])

    def run_ping_suite(self):
        targets = []
        if self._gateway and self._gateway != 'None':
            targets.append((self._gateway, f'Gateway {self._gateway}'))
        targets.append(('8.8.8.8', 'Google DNS 8.8.8.8'))
        targets.append(('1.1.1.1', 'Cloudflare 1.1.1.1'))
        targets.append(('google.com', 'Name lookup google.com'))
        self._run_pings(targets)

    def _run_pings(self, targets):
        if self._ping_busy or not self.device_id:
            return
        self._ping_busy = True
        self.ping_table.clear()
        self.ping_status.config(text='Testing...')
        self._set_ping_controls('disabled')

        count = self.ping_count_var.get()
        device_id = self.device_id
        manager = self.device_manager

        def task():
            results = []
            for host, label in targets:
                try:
                    result = manager.ping_host(device_id, host, count)
                except Exception as exc:
                    result = {'host': host, 'error': str(exc)}
                result['label'] = label
                results.append(result)
            if self._is_alive():
                self.after(0, lambda: self._apply_pings(results))

        threading.Thread(target=task, daemon=True).start()

    def _apply_pings(self, results):
        self._ping_busy = False
        self._set_ping_controls('normal')
        self._cached_pings = results
        self.ping_table.fill(results, self._format_ping_row)

        answered = sum(1 for r in results if not r.get('error'))
        self.ping_status.config(
            text=f'{answered} of {len(results)} answered',
            foreground='gray' if answered == len(results) else '#E65100')

    @staticmethod
    def _format_ping_row(result):
        if result.get('error'):
            return (result.get('label') or result.get('host', ''), '-', '-', '-',
                    '-', '-', result['error'])

        loss = result.get('loss')
        times = result.get('times') or []
        note = ' / '.join(f"{v:.0f}" for v in times) + ' ms' if times else 'no replies'
        return (
            result.get('label') or result.get('host', ''),
            f"{loss:.0f}%" if loss is not None else '-',
            _format_ms(result.get('min')),
            _format_ms(result.get('avg')),
            _format_ms(result.get('max')),
            _format_ms(result.get('jitter')),
            note,
        )

    def _set_ping_controls(self, state):
        self.ping_button.config(state=state)
        self.ping_quick_button.config(state=state)

    # --- export -------------------------------------------------------------

    def export_report(self):
        """Export a comprehensive network diagnostic report."""
        if not self.device_id:
            messagebox.showwarning("Export Report", "No device selected.")
            return

        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Export Network Diagnostic Report",
            defaultextension=".json",
            filetypes=[("JSON File", "*.json"), ("Text File", "*.txt"), ("All Files", "*.*")]
        )
        if not filename:
            return

        hide_sensitive = self.hide_sensitive_var.get()
        current_ssid = (self._cached_info.get('wifi') or {}).get('ssid') or ''

        # Prepare payload
        report_data = {
            'device_id': self.device_id,
            'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
            'sensitive_masked': hide_sensitive,
            'wifi': {k: var.get() for k, var in self.wifi_vars.items()},
            'cellular': {k: var.get() for k, var in self.cell_vars.items()},
            'ip_and_routing': {k: var.get() for k, var in self.ip_vars.items()},
            'app_traffic': self._cached_traffic,
            'active_connections': self._cached_sockets,
            'routing_table': self._cached_routes,
            'connectivity_history': self._cached_history,
            'network_requests': self._cached_requests,
            'latency_diagnostics': self._cached_pings,
        }

        if hide_sensitive:
            report_data = sanitize_network_data(report_data, ssid=current_ssid)
            # Mask device serial/id if sensitive
            report_data['device_id'] = re.sub(r'[A-Za-z0-9]', 'X', self.device_id)

        try:
            if filename.lower().endswith('.txt'):
                self._write_text_report(filename, report_data)
            else:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(report_data, f, indent=2, ensure_ascii=False)

            if self.set_status:
                self.set_status(f"Exported network report to {filename}")
            messagebox.showinfo("Export Successful", f"Network diagnostic report exported to:\n{filename}")
        except Exception as exc:
            messagebox.showerror("Export Error", f"Failed to export report:\n{exc}")

    def _write_text_report(self, filename, data):
        """Format the report as human-readable text."""
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"NETWORK DIAGNOSTIC REPORT\n{'=' * 70}\n")
            f.write(f"Device: {data['device_id']}\n")
            f.write(f"Generated: {data['timestamp']}\n")
            f.write(f"Sensitive Identifiers Masked: {'Yes' if data['sensitive_masked'] else 'No'}\n\n")

            f.write("1. WI-FI STATUS\n" + "-" * 70 + "\n")
            for k, v in data['wifi'].items():
                f.write(f"  {k.replace('_', ' ').capitalize():<16}: {v}\n")
            f.write("\n")

            f.write("2. CELLULAR STATUS\n" + "-" * 70 + "\n")
            for k, v in data['cellular'].items():
                f.write(f"  {k.replace('_', ' ').capitalize():<16}: {v}\n")
            f.write("\n")

            f.write("3. IP & ROUTING SUMMARY\n" + "-" * 70 + "\n")
            for k, v in data['ip_and_routing'].items():
                f.write(f"  {k.replace('_', ' ').capitalize():<16}: {v}\n")
            f.write("\n")

            f.write(f"4. ROUTING TABLE ({len(data['routing_table'])} routes)\n" + "-" * 70 + "\n")
            f.write(f"{'Destination':<24} {'Gateway':<16} {'Iface':<10} {'Table':<8} {'Metric':<8} {'Source':<16}\n")
            for r in data['routing_table']:
                f.write(f"{str(r.get('destination') or '-'):<24} "
                        f"{str(r.get('gateway') or '-'):<16} "
                        f"{str(r.get('interface') or '-'):<10} "
                        f"{str(r.get('table') or '-'):<8} "
                        f"{str(r.get('metric') or '-'):<8} "
                        f"{str(r.get('source') or '-'):<16}\n")
            f.write("\n")

            f.write(f"5. DATA USAGE PER APP ({len(data['app_traffic'])} apps)\n" + "-" * 70 + "\n")
            f.write(f"{'App':<34} {'Received':<12} {'Sent':<12} {'Total':<12} {'UID':<8}\n")
            for row in data['app_traffic']:
                pkg = row.get('package') or f"uid {row.get('uid')}"
                f.write(f"{pkg[:32]:<34} "
                        f"{_format_bytes(row.get('rx_bytes', 0)):<12} "
                        f"{_format_bytes(row.get('tx_bytes', 0)):<12} "
                        f"{_format_bytes(row.get('total_bytes', 0)):<12} "
                        f"{str(row.get('uid', '')):<8}\n")
            f.write("\n")

            f.write(f"6. ACTIVE CONNECTIONS ({len(data['active_connections'])} sockets)\n" + "-" * 70 + "\n")
            f.write(f"{'Direction':<12} {'Proto':<6} {'State':<12} {'Local':<22} {'Remote':<24} {'App':<20}\n")
            for s in data['active_connections']:
                loc = f"{s.get('local')}:{s.get('local_port')}"
                rem = f"{s.get('remote')}:{s.get('remote_port')}" if str(s.get('remote_port', '0')) != '0' else s.get('remote', '-')
                pkg = s.get('package') or f"uid {s.get('uid')}"
                f.write(f"{str(s.get('direction', '')):<12} "
                        f"{str(s.get('protocol', '')):<6} "
                        f"{str(s.get('state', '')):<12} "
                        f"{loc[:20]:<22} "
                        f"{rem[:22]:<24} "
                        f"{pkg[:18]:<20}\n")
            f.write("\n")

            f.write(f"7. CONNECTIVITY HISTORY ({len(data['connectivity_history'])} events)\n" + "-" * 70 + "\n")
            for h in data['connectivity_history']:
                f.write(f"[{h.get('timestamp')}] {h.get('type')}: {h.get('details')}\n")
            f.write("\n")

            if data['latency_diagnostics']:
                f.write("8. LATENCY DIAGNOSTICS\n" + "-" * 70 + "\n")
                f.write(f"{'Host':<20} {'Loss':<8} {'Min':<10} {'Avg':<10} {'Max':<10} {'Result':<20}\n")
                for p in data['latency_diagnostics']:
                    loss = f"{p.get('loss', 0):.0f}%" if p.get('loss') is not None else '-'
                    note = p.get('error') or (' / '.join(f"{v:.0f}" for v in p.get('times', [])) + ' ms' if p.get('times') else 'no replies')
                    f.write(f"{str(p.get('label') or p.get('host', '')):<20} "
                            f"{loss:<8} "
                            f"{_format_ms(p.get('min')):<10} "
                            f"{_format_ms(p.get('avg')):<10} "
                            f"{_format_ms(p.get('max')):<10} "
                            f"{note:<20}\n")
                f.write("\n")