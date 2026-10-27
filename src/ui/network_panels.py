"""Layout (toolbar, summary cards, tables) for the network inspector."""

import tkinter as tk
from tkinter import ttk

from .network_format import TABLE_HEIGHT
from .network_export import TABLE_SLUGS, export_rows_to
from .network_tables import _SortableTree


def _traffic_row_tags(row):
    """Wireshark-style coloring rules: heavy talkers stand out."""
    total = row.get('total_bytes') or 0
    if total > (1024 ** 3):
        return ('very-heavy',)
    if total > (100 * 1024 ** 2):
        return ('heavy',)
    return ()


def _socket_row_tags(row):
    """Color sockets the way Wireshark colors TCP states."""
    state = (row.get('state') or '').upper()
    if 'ESTABLISHED' in state:
        return ('established',)
    if 'LISTEN' in state:
        return ('listening',)
    if state.startswith('SYN') or 'CONNECTING' in state:
        return ('opening',)
    if any(mark in state for mark in ('CLOSE', 'FIN_WAIT', 'TIME_WAIT',
                                      'LAST_ACK', 'CLOSING')):
        return ('closing',)
    return ()


def _ping_row_tags(row):
    """Red for unanswered hosts, amber for a degraded link."""
    if row.get('error'):
        return ('dropped',)
    loss = (row.get('loss') or '')
    text = str(loss).replace('%', '').strip()
    if text.isdigit():
        if int(text) >= 50:
            return ('dropped',)
        if int(text) > 0:
            return ('degraded',)
    return ()


class NetworkPanelsMixin:
    """Layout methods for NetworkInspector (init, toolbar, cards, tables)."""


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
        # The notebook is the only vertically-growing region; everything above
        # it keeps its natural height.
        self.rowconfigure(3, weight=1)

        self._filter_after = None
        self._filter_applied = ''
        self._busy_filter = False

        self._create_toolbar()
        self._create_filter_bar()
        self._create_summary_cards()
        self._create_tables()

        self.bind('<Destroy>', lambda event: (self._cancel_filter_after(),
                                              self.stop_polling()))

        if auto_load and self.device_id:
            self.load()

    # --- layout ------------------------------------------------------------

    def _create_toolbar(self):
        toolbar = ttk.Frame(self, padding=(4, 2, 4, 2))
        toolbar.grid(row=0, column=0, sticky='ew')

        self.refresh_all_btn = ttk.Button(
            toolbar, text='Refresh All', command=self.refresh_all, width=12)
        self.refresh_all_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.export_btn = ttk.Button(
            toolbar, text='Export Report...', command=self.export_report, width=15)
        self.export_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.export_rows_btn = ttk.Button(
            toolbar, text='Export Rows...', command=self.export_rows, width=14)
        self.export_rows_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.capture_toggle = ttk.Button(
            toolbar, text='Stop polling', command=self.toggle_capture, width=13)
        self.capture_toggle.pack(side=tk.LEFT, padx=(0, 10))

        self.hide_sensitive_var = tk.BooleanVar(value=True)
        self.hide_sensitive_cb = ttk.Checkbutton(
            toolbar, text='Hide sensitive network identifiers (SSID, BSSID, MAC, IP)',
            variable=self.hide_sensitive_var)
        self.hide_sensitive_cb.pack(side=tk.LEFT, padx=(0, 10))

        self.status_label = ttk.Label(toolbar, text='', foreground='gray')
        self.status_label.pack(side=tk.RIGHT, padx=4)

    # --- display filter bar ------------------------------------------------

    def _create_filter_bar(self):
        """Wireshark's display filter: a live box above the packet list.

        Space-separated terms are matched anywhere in each row without
        re-querying the device. The entry carries Wireshark's tint: yellow
        while unsaved, green when rows match, red when nothing does.
        """
        bar = ttk.Frame(self, padding=(4, 0, 4, 4))
        bar.grid(row=1, column=0, sticky='ew')
        bar.columnconfigure(1, weight=1)

        ttk.Label(bar, text='Filter:',
                  font=('Segoe UI', 9, 'bold')).grid(row=0, column=0, padx=(0, 6))
        self.display_filter_var = tk.StringVar()
        self.display_filter_entry = ttk.Entry(bar, textvariable=self.display_filter_var)
        self.display_filter_entry.grid(row=0, column=1, sticky='ew')
        self.display_filter_entry.bind('<Return>', self._on_filter_enter)
        self.display_filter_entry.bind('<Escape>',
                                       lambda event: self.display_filter_var.set(''))
        self.display_filter_var.trace_add('write', self._on_filter_edited)

        self.filter_status = tk.StringVar(value='')
        ttk.Label(bar, textvariable=self.filter_status,
                  foreground='gray').grid(row=0, column=2, sticky='w', padx=(10, 0))

    def _current_filter_text(self):
        return self.display_filter_var.get()

    def _on_filter_enter(self, event=None):
        self._filter_applied = None  # force a re-evaluation even of same text
        self._apply_display_filter()
        return 'break'

    def _on_filter_edited(self, *_):
        # Trace fires for programmatic sets in _clear_all too.
        if self.display_filter_var.get() == self._filter_applied:
            return
        self._cancel_filter_after()
        try:
            self.display_filter_entry.config(background='#fff3cd')  # unsaved
        except Exception:
            pass
        self._filter_after = self.after(220, self._apply_display_filter)

    def _cancel_filter_after(self):
        if getattr(self, '_filter_after', None):
            try:
                self.after_cancel(self._filter_after)
            except Exception:
                pass
            self._filter_after = None

    def _apply_display_filter(self):
        self._filter_after = None
        self._filter_applied = self.display_filter_var.get().strip()

        tables = getattr(self, '_wire_tables', ())
        for table in tables:
            table.force_refill()

        self._evaluate_filter_tint()
        self._update_filter_status()

    def _evaluate_filter_tint(self):
        """Wireshark's tint: white (no filter), green (has matches), red (none)."""
        tables = getattr(self, '_wire_tables', ())
        populated = [t for t in tables if getattr(t, 'total', 0) > 0]
        if not self._filter_applied or not populated:
            tint = '#ffffff'   # no filter in force
        elif all(t.shown == 0 for t in populated):
            tint = '#ffd6d6'   # every table rejects it
        else:
            tint = '#d8f0d8'   # something matches somewhere

        try:
            self.display_filter_entry.config(background=tint)
        except Exception:
            pass

    def _wire_table_for_tab(self):
        """The table shown by the active notebook tab, or None."""
        mapping = {
            'Data usage': 'traffic_table',
            'Active connections': 'socket_table',
            'Routes': 'routes_table',
            'Connectivity history': 'history_table',
            'Network requests': 'request_table',
            'Ping & Latency': 'ping_table',
        }
        try:
            current = self.notebook.select()
            name = self.notebook.tab(current, 'text')
            return getattr(self, mapping.get(name, ''), None)
        except Exception:
            return None

    def export_rows(self):
        """Export the visible tab's captured rows to CSV or JSON, no re-query."""
        table = self._wire_table_for_tab()
        if table is None:
            return
        slug = 'rows'
        for attr, candidate in TABLE_SLUGS.items():
            if getattr(self, attr, None) is table:
                slug = candidate
        path = export_rows_to(self, table, slug)
        if path and self.set_status:
            self.set_status(
                f'Exported {getattr(table, "total", 0)} rows to {path}')

    def _update_filter_status(self):
        """The 'N of M shown' counter for the visible tab, next to the box."""
        table = self._wire_table_for_tab()
        if table is None or getattr(table, 'total', 0) == 0:
            self.filter_status.set('')
            return
        query = self._filter_applied
        text = f'{table.shown} of {table.total} shown' if query \
            else f'{table.total} rows'
        self.filter_status.set(text)

    def _refresh_filter_tint(self, shown=0, total=0):
        """after_fill hook: freshly captured rows can flip the tint; no refill."""
        self._evaluate_filter_tint()
        self._update_filter_status()

    def _create_summary_cards(self):
        container = ttk.Frame(self)
        container.grid(row=2, column=0, sticky='ew', padx=4, pady=(0, 6))
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
            ttk.Label(wifi_frame, text=label,
                      font=('Segoe UI', 9, 'bold')).grid(
                row=r, column=0, sticky='nw', pady=1, padx=(0, 6))
            var = tk.StringVar(value='-')
            ttk.Label(wifi_frame, textvariable=var, font=('Consolas', 9),
                      wraplength=180, justify=tk.LEFT).grid(
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
            ttk.Label(cell_frame, text=label,
                      font=('Segoe UI', 9, 'bold')).grid(
                row=r, column=0, sticky='nw', pady=1, padx=(0, 6))
            var = tk.StringVar(value='-')
            ttk.Label(cell_frame, textvariable=var, font=('Consolas', 9),
                      wraplength=180, justify=tk.LEFT).grid(
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
            ttk.Label(ip_frame, text=label,
                      font=('Segoe UI', 9, 'bold')).grid(
                row=r, column=0, sticky='nw', pady=1, padx=(0, 6))
            var = tk.StringVar(value='-')
            ttk.Label(ip_frame, textvariable=var, font=('Consolas', 9),
                      wraplength=200, justify=tk.LEFT).grid(
                row=r, column=1, sticky='w', pady=1)
            self.ip_vars[key] = var

        # Connection notice label across the bottom of cards
        self.connection_notice = ttk.Label(
            container, text='', foreground='#E65100', wraplength=750, justify=tk.LEFT)
        self.connection_notice.grid(row=1, column=0, columnspan=3, sticky='w', pady=(4, 0))

    def _create_tables(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=3, column=0, sticky='nsew', padx=4, pady=2)

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
            empty_text='No data usage captured yet',
            tag_fn=_traffic_row_tags,
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
            empty_text='No connections captured yet',
            tag_fn=_socket_row_tags,
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
            empty_text='No routes captured yet',
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
            empty_text='No connectivity events captured yet',
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
            empty_text='No network requests captured yet',
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
        self.ping_table = _SortableTree(
            latency, columns,
            empty_text='No ping results yet',
            tag_fn=_ping_row_tags)
        self.ping_table.pack(fill=tk.BOTH, expand=True)
        self.notebook.add(latency, text='Ping & Latency')

        # Everything above is one Wireshark "capture": one display filter and
        # one counter drive all six lists.
        self._wire_tables = (
            self.traffic_table, self.socket_table, self.routes_table,
            self.history_table, self.request_table, self.ping_table)
        for table in self._wire_tables:
            table.set_filter_fn(self._current_filter_text)

    def _add_table_controls(self, parent, command, name):
        controls = ttk.Frame(parent)
        controls.pack(fill=tk.X, pady=(6, 0))
        button = ttk.Button(controls, text='Refresh', command=command, width=10)
        button.pack(side=tk.LEFT)
        status = ttk.Label(controls, text='', foreground='gray')
        status.pack(side=tk.LEFT, padx=10)
        setattr(self, f'{name}_button', button)
        setattr(self, f'{name}_status', status)
