"""Shared formatting helpers and constants for the network inspector."""

import ipaddress
import re


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
