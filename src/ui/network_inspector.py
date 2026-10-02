"""Network inspector tab for the device details dialog.

Answers three questions about a device's networking: what it is connected to,
what has moved over the connection since boot, and what is talking to what
right now. Each table is read on demand rather than on a timer, because the
statistics behind them run to hundreds of kilobytes and there is no reason to
pay for them while nobody is looking at the tab.
"""

import threading
import time
import tkinter as tk
from tkinter import ttk

# Enough rows to read a long list without scrolling; the rest is one scroll away.
TABLE_HEIGHT = 10

# The supplicant states that mean a network is actually in use. Everything else
# is a transient or an idle radio, and the network name that comes with it is a
# leftover from the last time the device was connected.
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


class _SortableTree(ttk.Frame):
    """A treeview whose rows reorder when a heading is clicked.

    Sorting runs over the values behind the rows rather than over the text on
    screen, so a column of byte counts orders by its number instead of by the
    way its number was formatted. Clicking the same heading twice reverses it.
    """

    def __init__(self, parent, columns, sort_map=None, default_sort=None,
                 default_reverse=False, height=TABLE_HEIGHT):
        super().__init__(parent)
        # Column key -> how to read that column's value out of a row.
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
        self.clear()
        for row in rows:
            item = self.tree.insert('', 'end', values=formatter(row))
            self.rows[item] = row
        self._apply_sort()

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
            # Booleans sort as their numbers, so a yes/no column can be put with
            # the yeses on top instead of alphabetically.
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
            # Numbers read best largest first, the way a size column does
            # elsewhere in this window; text reads best from A to Z.
            self.sort_reverse = self._opens_on_numbers(column)
        self._apply_sort()

    def _opens_on_numbers(self, column):
        for row in self.rows.values():
            return isinstance(self._value_for(row, column), (int, float))
        return False


class NetworkInspector(ttk.Frame):
    """The network tab: connection details, per-app traffic, live sockets."""

    def __init__(self, parent, device_id, device_manager):
        super().__init__(parent)
        self.device_id = device_id
        self.device_manager = device_manager

        self._gateway = ''
        self._connection_busy = False
        self._traffic_busy = False
        self._sockets_busy = False
        self._requests_busy = False
        self._ping_busy = False
        self.loaded = False

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._create_top_row()
        self._create_tables()

    # --- layout ------------------------------------------------------------

    def _create_top_row(self):
        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        top.columnconfigure(0, weight=3, uniform='top')
        top.columnconfigure(1, weight=2, uniform='top')

        self._create_connection_panel(top)
        self._create_latency_panel(top)

    def _create_connection_panel(self, parent):
        frame = ttk.LabelFrame(parent, text='Connection', padding=10)
        frame.grid(row=0, column=0, sticky='nsew', padx=(0, 8))
        frame.columnconfigure(1, weight=1)

        self.connection_vars = {}
        fields = (
            ('radio', 'WiFi radio:'),
            ('network', 'Network:'),
            ('signal', 'Signal:'),
            ('state', 'State:'),
            ('ipv4', 'IP address:'),
            ('ipv6', 'IPv6 address:'),
            ('interface', 'Interface:'),
            ('gateway', 'Gateway:'),
            ('dns', 'Name servers:'),
            ('default_network', 'Default network:'),
        )
        for row, (key, label) in enumerate(fields):
            ttk.Label(frame, text=label, font=('Arial', 9, 'bold')).grid(
                row=row, column=0, sticky='nw', pady=3, padx=(0, 10))
            var = tk.StringVar(value='Reading...')
            ttk.Label(frame, textvariable=var, wraplength=260,
                      justify=tk.LEFT).grid(row=row, column=1, sticky='w', pady=3)
            self.connection_vars[key] = var

        self.connection_notice = ttk.Label(frame, text='', foreground='#E65100',
                                           wraplength=300, justify=tk.LEFT)
        self.connection_notice.grid(row=len(fields), column=0, columnspan=2,
                                    sticky='w', pady=(6, 0))

        controls = ttk.Frame(frame)
        controls.grid(row=len(fields) + 1, column=0, columnspan=2,
                      sticky='w', pady=(10, 0))
        ttk.Button(controls, text='Refresh', command=self.refresh_connection,
                   width=10).pack(side=tk.LEFT)
        self.connection_status = ttk.Label(controls, text='', foreground='gray')
        self.connection_status.pack(side=tk.LEFT, padx=10)

    def _create_latency_panel(self, parent):
        frame = ttk.LabelFrame(parent, text='Latency', padding=10)
        frame.grid(row=0, column=1, sticky='nsew')
        frame.columnconfigure(0, weight=1)

        controls = ttk.Frame(frame)
        controls.grid(row=0, column=0, sticky='ew')
        self.ping_host_var = tk.StringVar(value='8.8.8.8')
        ttk.Label(controls, text='Host').pack(side=tk.LEFT)
        entry = ttk.Entry(controls, textvariable=self.ping_host_var, width=18)
        entry.pack(side=tk.LEFT, padx=(6, 10))
        entry.bind('<Return>', lambda event: self.run_ping_on_entry())
        ttk.Label(controls, text='Packets').pack(side=tk.LEFT)
        self.ping_count_var = tk.IntVar(value=4)
        self.ping_count_spin = ttk.Spinbox(
            controls, from_=1, to=10, textvariable=self.ping_count_var, width=4)
        self.ping_count_spin.pack(side=tk.LEFT, padx=(6, 0))

        buttons = ttk.Frame(frame)
        buttons.grid(row=1, column=0, sticky='ew', pady=(8, 8))
        self.ping_button = ttk.Button(buttons, text='Run test',
                                      command=self.run_ping_on_entry, width=12)
        self.ping_button.pack(side=tk.LEFT)
        self.ping_quick_button = ttk.Button(
            buttons, text='Test route and DNS', command=self.run_ping_suite,
            width=20)
        self.ping_quick_button.pack(side=tk.LEFT, padx=8)
        self.ping_status = ttk.Label(buttons, text='', foreground='gray')
        self.ping_status.pack(side=tk.LEFT)

        columns = [
            ('host', 'Host', 130, 'w'),
            ('loss', 'Loss', 62, 'e'),
            ('min', 'Min', 74, 'e'),
            ('avg', 'Avg', 74, 'e'),
            ('max', 'Max', 74, 'e'),
            ('jitter', 'Jitter', 74, 'e'),
            ('note', 'Result', 190, 'w'),
        ]
        self.ping_table = _SortableTree(frame, columns)
        self.ping_table.grid(row=2, column=0, sticky='nsew')
        frame.rowconfigure(2, weight=1)

    def _create_tables(self):
        notebook = ttk.Notebook(self)
        notebook.grid(row=1, column=0, sticky='nsew')

        # Traffic: bytes in and out per app, which is where the incoming and
        # outgoing split of a connection actually shows up.
        traffic = ttk.Frame(notebook, padding=6)
        self.traffic_table = _SortableTree(
            traffic,
            [
                ('package', 'App', 250, 'w'),
                ('rx', 'Received', 92, 'e'),
                ('tx', 'Sent', 92, 'e'),
                ('total', 'Total', 92, 'e'),
                ('uid', 'UID', 62, 'e'),
            ],
            sort_map={
                'package': lambda row: row['package'] or f"uid {row['uid']}",
                'rx': lambda row: row['rx_bytes'],
                'tx': lambda row: row['tx_bytes'],
                'total': lambda row: row['total_bytes'],
                'uid': lambda row: row['uid'],
            },
            default_sort='total',
            default_reverse=True,
            height=TABLE_HEIGHT + 4,
        )
        self.traffic_table.pack(fill=tk.BOTH, expand=True)
        self.traffic_summary = ttk.Label(traffic, text='', foreground='gray')
        self.traffic_summary.pack(anchor='w', pady=(6, 0))
        self._add_table_controls(traffic, self.refresh_traffic, 'traffic')
        notebook.add(traffic, text='App traffic')

        # Sockets: what is open right now, and which app owns each end.
        sockets = ttk.Frame(notebook, padding=6)
        self.socket_table = _SortableTree(
            sockets,
            [
                ('direction', 'Direction', 104, 'w'),
                ('protocol', 'Protocol', 68, 'w'),
                ('state', 'State', 112, 'w'),
                ('package', 'App', 200, 'w'),
                ('local', 'Local address', 168, 'w'),
                ('remote', 'Remote address', 196, 'w'),
                ('uid', 'UID', 62, 'e'),
            ],
            sort_map={
                'package': lambda row: row['package'] or f"uid {row['uid']}",
                'remote': lambda row: f"{row['remote']}:{row['remote_port']}",
                'local': lambda row: f"{row['local']}:{row['local_port']}",
            },
            height=TABLE_HEIGHT + 4,
        )
        self.socket_table.pack(fill=tk.BOTH, expand=True)
        self.socket_summary = ttk.Label(sockets, text='', foreground='gray')
        self.socket_summary.pack(anchor='w', pady=(6, 0))
        self._add_table_controls(sockets, self.refresh_connections, 'connections')
        notebook.add(sockets, text='Active connections')

        # Requests: who has asked the system for network access at all.
        requests = ttk.Frame(notebook, padding=6)
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
                'package': lambda row: row['package'] or f"uid {row['uid']}",
                'internet': lambda row: row['internet'],
                'validated': lambda row: row['validated'],
                'count': lambda row: row['count'],
            },
            height=TABLE_HEIGHT + 4,
        )
        self.request_table.pack(fill=tk.BOTH, expand=True)
        self.request_summary = ttk.Label(requests, text='', foreground='gray')
        self.request_summary.pack(anchor='w', pady=(6, 0))
        self._add_table_controls(requests, self.refresh_requests, 'requests')
        notebook.add(requests, text='Network requests')

    def _add_table_controls(self, parent, command, name):
        controls = ttk.Frame(parent)
        controls.pack(fill=tk.X, pady=(8, 0))
        button = ttk.Button(controls, text='Refresh', command=command, width=10)
        button.pack(side=tk.LEFT)
        status = ttk.Label(controls, text='', foreground='gray')
        status.pack(side=tk.LEFT, padx=10)
        setattr(self, f'{name}_button', button)
        setattr(self, f'{name}_status', status)

    # --- reading ------------------------------------------------------------

    def _is_alive(self):
        try:
            return self.winfo_exists()
        except tk.TclError:
            return False

    def _run(self, busy_flag, work, apply, on_error):
        """Read on a worker thread and apply on the main one, one read at a time.

        The flag is owned here and cleared however the read ends. A refresh
        asked for while the previous one is still in flight is dropped rather
        than queued, so a slow device cannot pile up work behind every click.
        """
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
                # Python clears 'exc' as the except block ends, so the message
                # has to be kept in a name that outlives it before the callback
                # is handed to the event loop.
                message = str(exc)
                if self._is_alive():
                    self.after(0, lambda: finish(on_error, message))
                return
            if self._is_alive():
                self.after(0, lambda: finish(apply, result))

        threading.Thread(target=task, daemon=True).start()

    def load(self):
        """Read everything once, the first time the tab is shown."""
        self.refresh_connection()
        self.refresh_traffic()
        self.refresh_connections()
        self.refresh_requests()
        self.loaded = True

    def refresh_connection(self):
        self.connection_status.config(text='Reading...')

        def apply(info):
            self._apply_connection(info)

        def on_error(message):
            self.connection_status.config(text='', foreground='#C62828')
            self.connection_notice.config(text=f'Could not read the connection: {message}')

        self._run('_connection_busy',
                  lambda: self.device_manager.get_network_info(self.device_id),
                  apply, on_error)

    def _apply_connection(self, info):
        wifi = info.get('wifi') or {}
        interface = info.get('active_interface') or {}

        radio = wifi.get('enabled')
        state = wifi.get('state') or ''
        ssid = wifi.get('ssid') or ''
        rssi = wifi.get('rssi')

        connected = state in _CONNECTED_STATES
        self.connection_vars['radio'].set(
            'On' if radio else ('Off' if radio is False else MISSING))
        self.connection_vars['network'].set(ssid or 'Not connected')
        if rssi is None:
            self.connection_vars['signal'].set(MISSING)
        elif rssi <= _NO_SIGNAL_DBM:
            self.connection_vars['signal'].set('No signal')
        else:
            self.connection_vars['signal'].set(f'{rssi} dBm')
        self.connection_vars['state'].set(state or MISSING)

        self.connection_vars['ipv4'].set(
            ', '.join(interface.get('ipv4') or []) or 'None')
        ipv6 = interface.get('ipv6') or []
        self.connection_vars['ipv6'].set(', '.join(ipv6[:2]) or 'None')

        if interface:
            details = [interface.get('name', '')]
            if interface.get('mtu'):
                details.append(f"MTU {interface['mtu']}")
            if interface.get('state'):
                details.append(interface['state'])
            self.connection_vars['interface'].set(' - '.join(
                part for part in details if part))
        else:
            self.connection_vars['interface'].set('No interface is up')

        self._gateway = info.get('gateway') or ''
        self.connection_vars['gateway'].set(self._gateway or 'None')

        dns = info.get('dns') or []
        self.connection_vars['dns'].set(', '.join(dns) if dns else 'None')

        default_network = info.get('default_network') or ''
        self.connection_vars['default_network'].set(
            default_network if default_network and default_network != 'none' else 'None')

        # The network name that comes with a disconnected radio is the last one
        # the device saw, so it is labelled rather than presented as current.
        notes = []
        if not interface:
            notes.append('No interface holds a routable address.')
        if radio is False:
            notes.append('The WiFi radio is off.')
        if ssid and not connected:
            notes.append(f'{ssid} is the last network this device used, '
                         f'not the one it is on now.')
        if default_network in ('', 'none'):
            notes.append('The system reports no validated network.')
        self.connection_notice.config(text=' '.join(notes), foreground='#E65100')
        self.connection_status.config(
            text=f'Read {time.strftime("%H:%M:%S")}', foreground='gray')

    def refresh_traffic(self):
        self.traffic_status.config(text='Reading...')

        def apply(rows):
            self.traffic_table.fill(rows, self._format_usage_row)
            received = sum(row['rx_bytes'] for row in rows)
            sent = sum(row['tx_bytes'] for row in rows)
            if rows:
                self.traffic_summary.config(
                    text=f'{len(rows)} apps moved data since boot: '
                         f'{_format_bytes(received)} received, '
                         f'{_format_bytes(sent)} sent.',
                    foreground='gray')
            else:
                self.traffic_summary.config(
                    text='Nothing has moved over the network since boot.',
                    foreground='gray')
            self.traffic_status.config(text='', foreground='gray')

        def on_error(message):
            self.traffic_summary.config(text=f'Could not read traffic: {message}',
                                        foreground='#C62828')
            self.traffic_status.config(text='')

        self._run('_traffic_busy',
                  lambda: self.device_manager.get_app_network_usage(self.device_id),
                  apply, on_error)

    @staticmethod
    def _format_usage_row(row):
        return (
            row['package'] or f"uid {row['uid']} (system)",
            _format_bytes(row['rx_bytes']),
            _format_bytes(row['tx_bytes']),
            _format_bytes(row['total_bytes']),
            row['uid'],
        )

    def refresh_connections(self):
        self.connections_status.config(text='Reading...')

        def apply(rows):
            self.socket_table.fill(rows, self._format_socket_row)
            listening = sum(1 for row in rows if row['direction'] == 'Listening')
            connected = sum(1 for row in rows if row['direction'] == 'Connected')
            if rows:
                self.socket_summary.config(
                    text=f'{len(rows)} sockets open: {connected} connected, '
                         f'{listening} listening.',
                    foreground='gray')
            else:
                self.socket_summary.config(
                    text='The device holds no open sockets.', foreground='gray')
            self.connections_status.config(text='', foreground='gray')

        def on_error(message):
            self.socket_summary.config(
                text=f'Could not read sockets: {message}', foreground='#C62828')
            self.connections_status.config(text='')

        self._run('_sockets_busy',
                  lambda: self.device_manager.get_active_connections(self.device_id),
                  apply, on_error)

    @staticmethod
    def _format_socket_row(row):
        remote = row['remote']
        if row['remote_port'] != '0':
            remote = f"{remote}:{row['remote_port']}"
        return (
            row['direction'],
            row['protocol'],
            row['state'],
            row['package'] or f"uid {row['uid']}",
            f"{row['local']}:{row['local_port']}",
            remote or '-',
            row['uid'],
        )

    def refresh_requests(self):
        self.requests_status.config(text='Reading...')

        def apply(rows):
            self.request_table.fill(rows, self._format_request_row)
            wanting = sum(1 for row in rows if row['internet'])
            if rows:
                self.request_summary.config(
                    text=f'{len(rows)} owners hold network requests, '
                         f'{wanting} of them ask for internet access.',
                    foreground='gray')
            else:
                self.request_summary.config(
                    text='No network requests are registered.', foreground='gray')
            self.requests_status.config(text='', foreground='gray')

        def on_error(message):
            self.request_summary.config(
                text=f'Could not read network requests: {message}',
                foreground='#C62828')
            self.requests_status.config(text='')

        self._run('_requests_busy',
                  lambda: self.device_manager.get_network_requests(self.device_id),
                  apply, on_error)

    @staticmethod
    def _format_request_row(row):
        return (
            row['package'] or f"uid {row['uid']} (system)",
            'yes' if row['internet'] else 'no',
            'yes' if row['validated'] else 'no',
            row['count'],
            row['transports'] or 'any',
            ', '.join(row['kinds'].split(', ')) or '-',
            row['uid'],
        )

    # --- latency ------------------------------------------------------------

    def run_ping_on_entry(self):
        host = self.ping_host_var.get().strip()
        if not host:
            self.ping_status.config(text='Enter a host first', foreground='#C62828')
            return
        self._run_pings([(host, host)])

    def run_ping_suite(self):
        """Time the route out and the route to a name, which fail differently.

        A gateway that answers while a public address does not means the device
        is on the network but off the internet, and a name that will not resolve
        points at the name servers rather than the route. Testing them apart is
        what tells the two cases apart.
        """
        targets = []
        if self._gateway:
            targets.append((self._gateway, f'Gateway {self._gateway}'))
        targets.append(('8.8.8.8', 'Google DNS 8.8.8.8'))
        targets.append(('1.1.1.1', 'Cloudflare 1.1.1.1'))
        targets.append(('google.com', 'Name lookup google.com'))
        self._run_pings(targets)

    def _run_pings(self, targets):
        if self._ping_busy:
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
        self.ping_table.fill(results, self._format_ping_row)

        answered = sum(1 for result in results if not result.get('error'))
        self.ping_status.config(
            text=f'{answered} of {len(results)} answered',
            foreground='gray' if answered == len(results) else '#E65100')

    @staticmethod
    def _format_ping_row(result):
        if result.get('error'):
            return (result.get('label') or result.get('host', ''), '-', '-', '-',
                    '-', '-', result['error'])

        loss = result.get('loss')
        # The individual replies are the honest part of a ping: an average of a
        # few packets says little about whether the link is steady.
        times = result.get('times') or []
        if times:
            note = ' / '.join(f"{value:.0f}" for value in times) + ' ms'
        else:
            note = 'no replies'
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