"""ADBManager mixin: cellular, routing, connectivity and ping."""

import ipaddress
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional, Tuple
from .adb_parse_net import (_parse_ip_addr, _pick_active_interface, _parse_ip_route,
    _parse_netstats_uid_stats, _decode_socket_address, _parse_proc_net,
    _parse_ping, _parse_wifi_status)


_CONNECTIVITY_REQUEST = re.compile(
    r'uid/pid:(\d+)/(\d+)\s+NetworkRequest\s*\[\s*([A-Z_]+)\s+id=\d+,\s*\[')


_CONNECTIVITY_TRANSPORTS = re.compile(r'Transports:\s*([A-Z_|]+)')


_CONNECTIVITY_CAPABILITIES = re.compile(r'Capabilities:\s*([A-Z_&|]+)')


_CONNECTIVITY_DNS = re.compile(r'DnsAddresses:\s*\[([^\]]*)\]')


_CONNECTIVITY_DEFAULT = re.compile(r'Active default network:\s*(\S+)')


def _parse_network_requests(output: str) -> Dict[int, Dict[str, Any]]:
    """Who has registered for network access, gathered per uid from connectivity.

    Each request sits on its own line, so one pass over the lines collects the
    kind of request, the transports it asked for and the capabilities it wants.
    An app that has both a plain request and a listen registered appears once,
    with everything it asked for merged in.
    """
    requests: Dict[int, Dict[str, Any]] = {}

    for raw in output.splitlines():
        line = raw.strip()
        match = _CONNECTIVITY_REQUEST.match(line)
        if not match:
            continue

        uid = int(match.group(1))
        entry = requests.get(uid)
        if entry is None:
            entry = {
                'pids': set(), 'kinds': set(), 'transports': set(),
                'capabilities': set(), 'internet': False, 'validated': False,
                'count': 0,
            }
            requests[uid] = entry

        entry['count'] += 1
        entry['pids'].add(int(match.group(2)))
        entry['kinds'].add(match.group(3))

        transports = _CONNECTIVITY_TRANSPORTS.search(line)
        if transports:
            entry['transports'].update(
                name for name in transports.group(1).split('|') if name)

        capabilities = _CONNECTIVITY_CAPABILITIES.search(line)
        if capabilities:
            wanted = capabilities.group(1).split('&')
            entry['capabilities'].update(name for name in wanted if name)
            if 'INTERNET' in wanted:
                entry['internet'] = True
            if 'VALIDATED' in wanted:
                entry['validated'] = True

    return requests

def _parse_dns_servers(output: str) -> List[str]:
    """The name servers offered by whichever network is up."""
    addresses: List[str] = []
    for group in _CONNECTIVITY_DNS.findall(output):
        for address in re.findall(r'[0-9a-fA-F:.]{3,}', group):
            if address not in addresses:
                addresses.append(address)
    return addresses
class _NetworkMixin:
    """_NetworkMixin for ADBManager (see adb_manager.py)."""

    # 'pm list packages -U' walks every package on the device, and each of the
    # network tables needs the same answer, so it is held briefly rather than
    # asked for again every time a tab is opened.
    UID_MAP_TTL = 60

    def _get_uid_map(self, device_id: str) -> Dict[int, str]:
        """Map each app's uid to its package name, cached for a minute."""
        cached = getattr(self, '_uid_map_cache', None)
        now = time.time()
        if cached and cached[0] == device_id and now - cached[1] < self.UID_MAP_TTL:
            return cached[2]

        mapping: Dict[int, str] = {}
        try:
            output = self._run_command(
                ['shell', 'pm', 'list', 'packages', '-U'], device_id, timeout=30)
        except Exception:
            output = ''

        for package, uid in re.findall(r'package:(\S+)\s+uid:(\d+)', output):
            mapping[int(uid)] = package

        self._uid_map_cache = (device_id, now, mapping)
        return mapping

    def get_cellular_info(self, device_id: str) -> Dict[str, Any]:
        """Fetch cellular telephony status including SIM state, carrier, network type, and signal."""
        try:
            sim = self._run_command(['shell', 'getprop', 'gsm.sim.state'], device_id, timeout=3).strip()
            sim_val = 'Ready' if 'READY' in sim else ('Absent' if 'ABSENT' in sim else (sim or 'Unknown'))

            operator = self._run_command(['shell', 'getprop', 'gsm.operator.alpha'], device_id, timeout=3).strip()
            if not operator:
                operator = self._run_command(['shell', 'getprop', 'gsm.sim.operator.alpha'], device_id, timeout=3).strip()

            net_type = self._run_command(['shell', 'getprop', 'gsm.network.type'], device_id, timeout=3).strip()
            if not net_type or net_type == 'Unknown,Unknown':
                net_type = 'None/Unknown'

            tele = self._run_command(['shell', 'dumpsys', 'telephony.registry'], device_id, timeout=4)
            data_state_m = re.search(r'mDataConnectionState=(\d+)', tele)
            state_map = {'0': 'Disconnected', '1': 'Connecting', '2': 'Connected', '3': 'Suspended'}
            data_state = state_map.get(data_state_m.group(1), 'Disconnected') if data_state_m else 'Disconnected'

            data_net_m = re.search(r'mDataNetworkType=([^\s]+)', tele)
            if data_net_m and data_net_m.group(1) != 'Unknown':
                net_type = data_net_m.group(1)

            sig_m = re.search(r'SignalStrength:\{([^}]+)\}', tele)
            sig_str = 'N/A'
            if sig_m:
                dbm_m = re.search(r'(?:lteDbm|gsmDbm|nrDbm|cdmaDbm)=(-?\d+)', sig_m.group(1))
                if dbm_m and dbm_m.group(1) not in ('2147483647', '99', '-1'):
                    sig_str = f"{dbm_m.group(1)} dBm"

            return {
                'sim_state': sim_val,
                'operator': operator or 'No carrier',
                'data_state': data_state,
                'network_type': net_type,
                'signal': sig_str,
            }
        except Exception as e:
            return {
                'sim_state': 'Unknown',
                'operator': 'Unknown',
                'data_state': 'Unknown',
                'network_type': 'Unknown',
                'signal': 'N/A',
                'error': str(e),
            }

    def get_routing_table(self, device_id: str) -> List[Dict[str, Any]]:
        """Fetch all routing table entries across tables."""
        try:
            out = self._run_command(['shell', 'ip', 'route', 'show', 'table', 'all'], device_id, timeout=5)
            routes = []
            for line in out.splitlines():
                line = line.strip()
                if not line or line.startswith('unreachable') or line.startswith('broadcast') or 'error' in line:
                    continue
                parts = line.split()
                dest = parts[0]
                via = ''
                dev = ''
                table = ''
                proto = ''
                metric = ''
                scope = ''
                src = ''

                i = 1
                while i < len(parts):
                    if parts[i] == 'via' and i + 1 < len(parts):
                        via = parts[i+1]; i += 2
                    elif parts[i] == 'dev' and i + 1 < len(parts):
                        dev = parts[i+1]; i += 2
                    elif parts[i] == 'table' and i + 1 < len(parts):
                        table = parts[i+1]; i += 2
                    elif parts[i] == 'proto' and i + 1 < len(parts):
                        proto = parts[i+1]; i += 2
                    elif parts[i] == 'metric' and i + 1 < len(parts):
                        metric = parts[i+1]; i += 2
                    elif parts[i] == 'scope' and i + 1 < len(parts):
                        scope = parts[i+1]; i += 2
                    elif parts[i] == 'src' and i + 1 < len(parts):
                        src = parts[i+1]; i += 2
                    else:
                        i += 1
                routes.append({
                    'destination': dest,
                    'gateway': via or 'Direct',
                    'interface': dev or 'lo',
                    'table': table or 'main',
                    'metric': metric or '-',
                    'scope': scope or proto or '-',
                    'source': src or '-',
                })
            return routes
        except Exception:
            return []

    def get_connectivity_history(self, device_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch timestamped connectivity requests and state changes."""
        try:
            out = self._run_command(['shell', 'dumpsys', 'connectivity'], device_id, timeout=10)
            events = []
            in_log = False
            log_type = 'NetworkRequest'
            for line in out.splitlines():
                if 'mNetworkRequestInfoLogs' in line:
                    in_log = True
                    log_type = 'NetworkRequest'
                    continue
                elif 'mNetworkInfoBlockingLogs' in line:
                    in_log = True
                    log_type = 'NetworkBlocking'
                    continue
                elif 'NetworkStackClient logs:' in line:
                    in_log = True
                    log_type = 'NetworkStack'
                    continue
                elif in_log and line.strip().endswith(':'):
                    if not any(k in line for k in ['NetworkRequest', 'Blocking', 'NetworkStack']):
                        in_log = False

                if in_log:
                    clean_l = line.strip()
                    if not clean_l or clean_l.startswith('total') or clean_l.startswith('bandwidth'):
                        continue
                    m = re.match(r'([0-9T:.\-]+)\s*-\s*(.+)', clean_l)
                    if m:
                        ts = m.group(1).replace('T', ' ')
                        rest = m.group(2)
                        action_m = re.match(r'([A-Za-z_]+)\s*(.*)', rest)
                        action = action_m.group(1) if action_m else log_type
                        details = action_m.group(2) if action_m else rest
                        events.append({
                            'timestamp': ts,
                            'category': log_type,
                            'event': action,
                            'details': details,
                        })
                        if len(events) >= limit:
                            break
            return events
        except Exception:
            return []

    def get_network_info(self, device_id: str) -> Dict[str, Any]:
        """Everything about the connection in one pass.

        The sources are independent, so they run together. A device that
        refuses one of them still reports the rest, since being able to say which
        half is missing is what makes the rest useful.
        """
        jobs = {
            'addresses': lambda: self._run_command(
                ['shell', 'ip', 'addr', 'show'], device_id, timeout=15),
            'route': lambda: self._run_command(
                ['shell', 'ip', 'route'], device_id, timeout=15),
            'wifi': lambda: self._run_command(
                ['shell', 'cmd', 'wifi', 'status'], device_id, timeout=15),
            'connectivity': lambda: self._run_command(
                ['shell', 'dumpsys', 'connectivity'], device_id, timeout=25),
            'cellular': lambda: self.get_cellular_info(device_id),
        }

        raw: Dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = {name: pool.submit(job) for name, job in jobs.items()}
            for name, future in futures.items():
                try:
                    raw[name] = future.result()
                except Exception:
                    raw[name] = ''

        # 'cmd wifi status' needs a privilege the shell does not have on some
        # builds, where the full dump is the only way to the network's name.
        wifi_raw = raw.get('wifi') or ''
        wifi = _parse_wifi_status(wifi_raw) if isinstance(wifi_raw, str) else {}
        if not wifi.get('ssid') and not wifi.get('state'):
            try:
                wifi = _parse_wifi_status(self._run_command(
                    ['shell', 'dumpsys', 'wifi'], device_id, timeout=20))
            except Exception:
                pass

        addr_raw = raw.get('addresses') or ''
        interfaces = _parse_ip_addr(addr_raw) if isinstance(addr_raw, str) else []
        route_raw = raw.get('route') or ''
        route = _parse_ip_route(route_raw) if isinstance(route_raw, str) else {}
        active = _pick_active_interface(interfaces)

        conn_raw = raw.get('connectivity') or ''
        default_network = _CONNECTIVITY_DEFAULT.search(conn_raw) if isinstance(conn_raw, str) else None
        cellular = raw.get('cellular') if isinstance(raw.get('cellular'), dict) else self.get_cellular_info(device_id)

        return {
            'wifi': wifi,
            'cellular': cellular,
            'interfaces': interfaces,
            'active_interface': active,
            'gateway': route.get('gateway', ''),
            'route_interface': route.get('interface', ''),
            'source_address': route.get('source', ''),
            'dns': _parse_dns_servers(conn_raw) if isinstance(conn_raw, str) else [],
            'default_network': default_network.group(1) if default_network else '',
        }

    def get_app_network_usage(self, device_id: str) -> List[Dict[str, Any]]:
        """Bytes each app has received and sent since boot, largest first.

        The figures cover the device's own history rather than the last refresh,
        so this answers what an app has been doing over the life of the boot
        rather than what it did in the last few seconds.
        """
        output = self._run_command(
            ['shell', 'dumpsys', 'netstats', 'detail'], device_id, timeout=45)
        totals = _parse_netstats_uid_stats(output)
        names = self._get_uid_map(device_id)

        rows: List[Dict[str, Any]] = []
        for uid, entry in totals.items():
            received = entry['rx_bytes']
            sent = entry['tx_bytes']
            if not received and not sent:
                continue
            rows.append({
                'uid': uid,
                'package': names.get(uid, ''),
                'rx_bytes': received,
                'tx_bytes': sent,
                'total_bytes': received + sent,
                'rx_packets': entry['rx_packets'],
                'tx_packets': entry['tx_packets'],
                'networks': ', '.join(sorted(entry['networks'])),
            })

        rows.sort(key=lambda row: -row['total_bytes'])
        return rows

    def get_active_connections(self, device_id: str) -> List[Dict[str, Any]]:
        """The sockets the device holds open, with the app behind each one."""
        names = self._get_uid_map(device_id)
        sockets: List[Dict[str, Any]] = []

        for table, protocol in (('tcp', 'TCP'), ('tcp6', 'TCP'),
                                ('udp', 'UDP'), ('udp6', 'UDP')):
            try:
                output = self._run_command(['shell', 'cat', f'/proc/net/{table}'],
                                           device_id, timeout=15)
            except Exception:
                continue
            sockets.extend(_parse_proc_net(output, protocol, names))

        sockets.sort(key=lambda row: (row['protocol'], row['state'],
                                      row['remote'], row['remote_port']))
        return sockets

    def get_network_requests(self, device_id: str) -> List[Dict[str, Any]]:
        """Which apps have registered for network access, and on what."""
        output = self._run_command(
            ['shell', 'dumpsys', 'connectivity'], device_id, timeout=25)
        requests = _parse_network_requests(output)
        names = self._get_uid_map(device_id)

        rows = []
        for uid, entry in requests.items():
            rows.append({
                'uid': uid,
                'package': names.get(uid, ''),
                'pids': ', '.join(str(pid) for pid in sorted(entry['pids'])),
                'kinds': ', '.join(sorted(entry['kinds'])),
                'transports': ', '.join(sorted(entry['transports'])),
                'internet': entry['internet'],
                'validated': entry['validated'],
                'count': entry['count'],
            })
        rows.sort(key=lambda row: (not row['internet'], row['package'], row['uid']))
        return rows


