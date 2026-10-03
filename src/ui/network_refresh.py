"""Data readers (connection, traffic, sockets, routes, history) for the network inspector."""

import time

from .network_format import _CONNECTED_STATES, _NO_SIGNAL_DBM, MISSING, _format_bytes


class NetworkRefreshMixin:
    """Reader methods for NetworkInspector."""


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
