"""Pure parsing helpers for ip/route/netstat/ping/wifi output."""

import ipaddress
import re
from typing import Dict, Any, List, Optional, Tuple
_WIFI_SSID = re.compile(r'SSID:\s*(.*?)(?=,\s|\s+\w+:|$)')
_WIFI_RSSI = re.compile(r'RSSI:\s*(-?\d+)')
_WIFI_STATE = re.compile(r'[Ss]upplicant state:\s*(\w+)')
_WIFI_ON = re.compile(r'wi-?fi\s+is\s+enabled', re.I)
_WIFI_OFF = re.compile(r'wi-?fi\s+is\s+disabled', re.I)

# on top of another, which is not part of its name.
_IP_INTERFACE = re.compile(r'^\d+:\s+([^:@]+)(?:@\S+)?:\s*<([^>]*)>')
_IP_MTU = re.compile(r'\bmtu (\d+)')
_IP_STATE = re.compile(r'\bstate (\w+)')
_IP_ADDRESS = re.compile(r'^\s+(inet6?)\s+(\S+)')
_IP_MAC = re.compile(r'^\s+link/\S+\s+([0-9a-fA-F:]+)')

# Only the default route matters for reaching anywhere off the device.
_IP_ROUTE_VIA = re.compile(r'\bvia (\S+)')
_IP_ROUTE_DEV = re.compile(r'\bdev (\S+)')
_IP_ROUTE_SRC = re.compile(r'\bsrc (\S+)')

# 'dumpsys netstats' is a run of titled sections. Each one reports the same
# bytes under a different grouping, so only 'UID stats' counts each app once.
_NETSTATS_SECTION = re.compile(r'^([A-Za-z][A-Za-z ]*):\s*$')
_NETSTATS_IDENT = re.compile(r'\buid=(-?\d+)\s')
_NETSTATS_NETWORK = re.compile(r'networkId="([^"]*)"')
_NETSTATS_BUCKET = re.compile(
    r'st=(-?\d+)\s+rb=(\d+)\s+rp=(\d+)\s+tb=(\d+)\s+tp=(\d+)\s+op=(\d+)')

# 'dumpsys connectivity' lists every registered network request. The kind of
# request says whether an app is asking for data, listening for it, or both.

# The addresses a network hands out for name lookups live in the active
# network's link properties, which are absent while nothing is connected.

# ping answers in its own words: a reply line per packet, then a summary. The
# round-trip line is missing altogether when every packet was lost.
_PING_REPLY = re.compile(r'time[=<]\s*([\d.]+)\s*ms')
_PING_SUMMARY = re.compile(
    r'(\d+)\s+packets transmitted,\s*(\d+)(?:\s+packets)?\s+received')
_PING_LOSS = re.compile(r'([\d.]+)%\s*packet loss')
_PING_RTT = re.compile(
    r'rtt\s+min/avg/max(?:\S*)?\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)(?:/([\d.]+))?')

# 'ss' cannot be used: it wants a netlink socket the shell user may not open.
# '/proc/net' is world-readable and carries the same rows with their uid.
_TCP_STATES = {
    '01': 'ESTABLISHED', '02': 'SYN_SENT', '03': 'SYN_RECV', '04': 'FIN_WAIT1',
    '05': 'FIN_WAIT2', '06': 'TIME_WAIT', '07': 'CLOSE', '08': 'CLOSE_WAIT',
    '09': 'LAST_ACK', '0A': 'LISTEN', '0B': 'CLOSING',
}

# An address of all zeroes with port zero is how the kernel writes "nobody".
_UNSPECIFIED_ADDRESSES = frozenset({'0.0.0.0:0', ':::0', '[::]:0'})

def _parse_ip_addr(output: str) -> List[Dict[str, Any]]:
    """Read the interfaces and their addresses out of 'ip addr' output."""
    interfaces: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    for line in output.splitlines():
        heading = _IP_INTERFACE.match(line)
        if heading:
            current = {
                'name': heading.group(1).strip(),
                'flags': [flag for flag in heading.group(2).split(',') if flag],
                'mtu': None,
                'state': None,
                'mac': '',
                'ipv4': [],
                'ipv6': [],
            }
            mtu = _IP_MTU.search(line)
            if mtu:
                current['mtu'] = int(mtu.group(1))
            state = _IP_STATE.search(line)
            if state:
                current['state'] = state.group(1)
            interfaces.append(current)
            continue

        if current is None:
            continue

        address = _IP_ADDRESS.match(line)
        if address:
            family = 'ipv4' if address.group(1) == 'inet' else 'ipv6'
            current[family].append(address.group(2).split('/')[0])
            continue

        mac = _IP_MAC.match(line)
        if mac:
            current['mac'] = mac.group(1)

    return interfaces

def _pick_active_interface(interfaces: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The interface carrying the address a remote peer could reach.

    A phone may hold several up at once, so a routable address is the only
    reliable test, and loopback is not one: a device with nothing else up has no
    interface to report rather than one that only talks to itself. Wireless and
    cellular names come first so that a VPN or hotspot interface does not
    outrank the interface behind it.
    """
    preferred = ('wlan', 'rmnet', 'ccmni', 'eth', 'ap', 'swlan')

    def rank(interface: Dict[str, Any]) -> Tuple[int, int]:
        if interface['state'] not in ('UP', 'UNKNOWN'):
            return (2, 0)
        for index, prefix in enumerate(preferred):
            if interface['name'].startswith(prefix):
                return (index, 0)
        return (1, 0)

    candidates = [
        iface for iface in interfaces
        if iface['name'] != 'lo'
        and any(not address.startswith('127.') for address in iface['ipv4'])
    ]
    if not candidates:
        return None
    return min(candidates, key=rank)

def _parse_ip_route(output: str) -> Dict[str, str]:
    """The default route: where traffic goes, by which interface, from what address."""
    for line in output.splitlines():
        if not line.startswith('default'):
            continue
        via = _IP_ROUTE_VIA.search(line)
        dev = _IP_ROUTE_DEV.search(line)
        src = _IP_ROUTE_SRC.search(line)
        if not via:
            continue
        return {
            'gateway': via.group(1),
            'interface': dev.group(1) if dev else '',
            'source': src.group(1) if src else '',
            'line': line.strip(),
        }
    return {}

def _parse_netstats_uid_stats(output: str) -> Dict[int, Dict[str, Any]]:
    """Bytes moved per uid, from the 'UID stats' section of 'dumpsys netstats'.

    Only that section counts each app once. 'Dev stats' holds the device as a
    whole, 'UID tag stats' splits one app across per-socket tags, and the XT
    sections are the same bytes as the iptables layer saw them, so adding the
    sections together would multiply every total several times over.

    Within the section a uid appears once per network it used and again per
    state, and each of those carries an hourly bucket per entry, so every
    bucket is added into the one figure for that uid.
    """
    totals: Dict[int, Dict[str, Any]] = {}
    section = ''
    uid: Optional[int] = None

    for line in output.splitlines():
        heading = _NETSTATS_SECTION.match(line)
        if heading:
            section = heading.group(1)
            uid = None
            continue
        if section != 'UID stats':
            continue

        if 'ident=' in line:
            match = _NETSTATS_IDENT.search(line)
            uid = int(match.group(1)) if match else None
            if uid is not None and uid not in totals:
                totals[uid] = {
                    'rx_bytes': 0, 'rx_packets': 0,
                    'tx_bytes': 0, 'tx_packets': 0, 'operations': 0,
                    'networks': set(),
                }
            if uid is not None:
                network = _NETSTATS_NETWORK.search(line)
                if network and network.group(1):
                    totals[uid]['networks'].add(network.group(1))
            continue

        if uid is None:
            continue
        bucket = _NETSTATS_BUCKET.search(line)
        if bucket:
            entry = totals[uid]
            entry['rx_bytes'] += int(bucket.group(2))
            entry['rx_packets'] += int(bucket.group(3))
            entry['tx_bytes'] += int(bucket.group(4))
            entry['tx_packets'] += int(bucket.group(5))
            entry['operations'] += int(bucket.group(6))

    return totals

def _decode_socket_address(token: str) -> str:
    """Turn one '/proc/net' address into the dotted form a reader expects.

    The kernel writes each 32-bit word in the host's own order, so the bytes of
    a word are reversed. An IPv6 address holds four such words, each reversed in
    the same way while the words themselves stay in order.
    """
    address, _, port = token.partition(':')
    try:
        raw = bytes.fromhex(address)
    except ValueError:
        return token

    if len(raw) == 4:
        host = str(ipaddress.IPv4Address(raw[::-1]))
    elif len(raw) == 16:
        words = b''.join(raw[index:index + 4][::-1] for index in range(0, 16, 4))
        host = str(ipaddress.IPv6Address(words))
    else:
        return token

    try:
        number = int(port, 16)
    except ValueError:
        number = 0
    return f'{host}:{number}'

def _parse_proc_net(output: str, protocol: str, names: Dict[int, str]) -> List[Dict[str, Any]]:
    """One row per open socket, from a '/proc/net' table.

    The rows carry the uid of the app that owns the socket, which is what makes
    them worth reading: without it a table of addresses says nothing about which
    app is talking to whom.
    """
    sockets: List[Dict[str, Any]] = []

    for line in output.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 8:
            continue
        try:
            uid = int(fields[7])
        except ValueError:
            continue

        local = _decode_socket_address(fields[1])
        remote = _decode_socket_address(fields[2])
        no_peer = remote in _UNSPECIFIED_ADDRESSES or remote.endswith(':0')
        raw_state = fields[3].upper()

        if protocol == 'UDP':
            direction = 'Outbound' if not no_peer else 'Unconnected'
            state = 'UNCONN'
        elif raw_state == '0A':
            direction = 'Listening'
            state = _TCP_STATES[raw_state]
        elif no_peer:
            direction = 'No peer'
            state = _TCP_STATES.get(raw_state, raw_state)
        else:
            # A live TCP socket carries traffic both ways; it is not outgoing.
            direction = 'Connected'
            state = _TCP_STATES.get(raw_state, raw_state)

        local_host, _, local_port = local.rpartition(':')
        remote_host, _, remote_port = remote.rpartition(':')
        sockets.append({
            'protocol': protocol,
            'direction': direction,
            'state': state,
            'local': local_host,
            'local_port': local_port,
            'remote': remote_host,
            'remote_port': remote_port,
            'uid': uid,
            'package': names.get(uid, ''),
        })

    return sockets



def _parse_ping(output: str, error: str, host: str, count: int) -> Dict[str, Any]:
    """Read a ping run out of its own output.

    A host that cannot be reached is an answer rather than a failure, so the
    statistics are allowed to be absent: an unreachable host reports no timings
    and no summary, and says why in its error line instead.
    """
    result: Dict[str, Any] = {
        'host': host,
        'requested': count,
        'times': [float(value) for value in _PING_REPLY.findall(output)],
        'sent': 0,
        'received': 0,
        'loss': None,
        'min': None,
        'avg': None,
        'max': None,
        'jitter': None,
        'error': '',
    }

    summary = _PING_SUMMARY.search(output)
    if summary:
        result['sent'] = int(summary.group(1))
        result['received'] = int(summary.group(2))

    loss = _PING_LOSS.search(output)
    if loss:
        result['loss'] = float(loss.group(1))
    elif result['sent']:
        result['loss'] = round(
            (result['sent'] - result['received']) * 100.0 / result['sent'], 1)

    rtt = _PING_RTT.search(output)
    if rtt:
        result['min'] = float(rtt.group(1))
        result['avg'] = float(rtt.group(2))
        result['max'] = float(rtt.group(3))
        result['jitter'] = float(rtt.group(4)) if rtt.group(4) else None

    if not result['times'] and not summary:
        for line in error.splitlines():
            if line.strip():
                result['error'] = line.strip()
                break
        if not result['error']:
            result['error'] = 'No reply from this host'

    return result

def _parse_forward_list(output: str) -> List[Dict[str, str]]:
    """Parse 'adb forward --list' / 'adb reverse --list' output.

    Every line is '<serial> <local> <remote>'; other lines are ignored so a
    warning adb prints alongside the list does not become a bogus entry.
    """
    entries = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        entries.append({'serial': parts[0], 'local': parts[1], 'remote': parts[2]})
    return entries

def _parse_wifi_status(output: str) -> Dict[str, Any]:
    """Pull SSID, signal, state, link speed, frequency, and BSSID out of wifi status/dump."""
    text = output.strip()
    enabled = None
    if _WIFI_ON.search(text):
        enabled = True
    elif _WIFI_OFF.search(text):
        enabled = False

    ssid = _WIFI_SSID.search(text)
    rssi = _WIFI_RSSI.search(text)
    state = _WIFI_STATE.search(text)

    name = ssid.group(1).strip().strip('"') if ssid else ''
    if name.startswith('<'):
        name = ''

    link_speed_m = re.search(r'[Ll]ink speed:\s*(\d+\s*[Mm]bps)', text)
    freq_m = re.search(r'[Ff]requency:\s*(\d+\s*[Mm][Hh]z)', text)
    bssid_m = re.search(r'BSSID:\s*([0-9a-fA-F:]{17})', text)
    mac_m = re.search(r'MAC:\s*([0-9a-fA-F:]{17})', text)

    return {
        'enabled': enabled,
        'ssid': name,
        'rssi': int(rssi.group(1)) if rssi else None,
        'state': state.group(1) if state else '',
        'link_speed': link_speed_m.group(1) if link_speed_m else '',
        'frequency': freq_m.group(1) if freq_m else '',
        'bssid': bssid_m.group(1) if bssid_m else '',
        'mac': mac_m.group(1) if mac_m else '',
    }

