"""ADBManager mixin: TCP/IP mode, IP discovery, pairing and connect."""

import re
import socket
import subprocess
import time
from typing import Dict, Any, List, Optional, Tuple
from .adb_base import ADBCommandError
from .adb_parse_net import _parse_ip_addr


class _WirelessMixin:
    """_WirelessMixin for ADBManager (see adb_manager.py)."""

    def enable_tcpip(self, device_id: str, port: int = 5555) -> str:
        """Restart ADB daemon on the device in TCP/IP mode on specified port.

        Args:
            device_id: Device ID / serial number
            port: Port number (default 5555)

        Returns:
            Output message from ADB
        """
        if not isinstance(port, int) or port < 1024 or port > 65535:
            raise ValueError(f"Invalid TCP/IP port: {port}. Must be between 1024 and 65535.")
        return self._run_command(['tcpip', str(port)], device_id=device_id)

    @staticmethod
    def _get_host_wifi_gateway() -> Optional[str]:
        """Attempt to discover the default gateway of the host's Wi-Fi adapter or hotspot network."""
        import platform
        system = platform.system().lower()
        try:
            if system == 'windows':
                out = subprocess.run(['ipconfig'], capture_output=True, text=True,
                                     encoding='utf-8', errors='replace', timeout=3).stdout
                sections = re.split(r'\r?\n(?=[^\s])', out)
                # First priority: Wireless / Wi-Fi adapter
                for sec in sections:
                    if re.search(r'wi-?fi|wireless', sec, re.IGNORECASE):
                        m = re.search(r'Default Gateway[ .]*:\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)', sec)
                        if m:
                            gw = m.group(1).strip()
                            if gw != '0.0.0.0' and not gw.startswith('127.'):
                                return gw
                # Second priority: any adapter with gateway starting with 192.168.
                for sec in sections:
                    m = re.search(r'Default Gateway[ .]*:\s*(192\.168\.[0-9]+\.[0-9]+)', sec)
                    if m:
                        return m.group(1).strip()
            else:
                out = subprocess.run(['ip', 'route', 'show', 'default'], capture_output=True, text=True,
                                     encoding='utf-8', errors='replace', timeout=3).stdout
                m = re.search(r'default\s+via\s+([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)\s+dev\s+([a-zA-Z0-9_\-]+)', out)
                if m:
                    gw, dev = m.group(1), m.group(2).lower()
                    if re.search(r'^(wl|wifi|wlan|ap)', dev) or gw.startswith('192.168.'):
                        return gw
        except Exception:
            pass
        return None

    def get_device_ip(self, device_id: Optional[str] = None) -> Optional[str]:
        """Attempt to determine the Wi-Fi or Hotspot IP address of the connected device.

        Detects hotspot interfaces (ap0, softap0), Wi-Fi client interfaces (wlan0, wlan1),
        routing tables, network properties, and host gateway correlation (prioritizing 192.168.*).

        Args:
            device_id: Optional Device ID / serial number

        Returns:
            IP address string if found, None otherwise
        """
        host_gw = self._get_host_wifi_gateway()
        candidates: List[Any] = []

        if device_id:
            # 1. Parse ip -4 addr show block by block
            try:
                out = self._run_command(['shell', 'ip', '-4', 'addr', 'show'], device_id=device_id)
                current_iface = ''
                for line in out.splitlines():
                    m_iface = re.match(r'^\d+:\s+([a-zA-Z0-9_\-]+):', line)
                    if m_iface:
                        current_iface = m_iface.group(1).lower()
                        continue
                    m_inet = re.search(r'inet\s+([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)', line)
                    if m_inet:
                        ip = m_inet.group(1)
                        if ip != '127.0.0.1' and not ip.startswith('127.'):
                            candidates.append((current_iface, ip))
            except Exception:
                pass

            # 2. Query hotspot & Wi-Fi interfaces specifically
            for iface in ['ap0', 'ap1', 'softap0', 'softap1', 'wlan0', 'wlan1', 'wlan2', 'swlan0', 'rndis0', 'usb0', 'eth0']:
                try:
                    out = self._run_command(['shell', 'ip', '-f', 'inet', 'addr', 'show', iface], device_id=device_id)
                    m = re.search(r'inet\s+([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)', out)
                    if m and m.group(1) != '127.0.0.1' and not m.group(1).startswith('127.'):
                        candidates.append((iface, m.group(1)))
                except Exception:
                    pass

            # 3. Parse routing table for source IP
            try:
                out = self._run_command(['shell', 'ip', 'route'], device_id=device_id)
                for line in out.splitlines():
                    m_src = re.search(r'src\s+([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)', line)
                    m_dev = re.search(r'dev\s+([a-zA-Z0-9_\-]+)', line)
                    if m_src:
                        ip = m_src.group(1)
                        iface = m_dev.group(1).lower() if m_dev else 'route'
                        if ip != '127.0.0.1' and not ip.startswith('127.'):
                            candidates.append((iface, ip))
            except Exception:
                pass

            # 4. Check DHCP and network properties
            for prop in [
                'dhcp.ap0.ipaddress', 'dhcp.softap0.ipaddress',
                'dhcp.wlan0.ipaddress', 'dhcp.wlan1.ipaddress',
                'net.ap0.ip', 'net.softap0.ip',
                'net.wlan0.ip', 'net.wlan1.ip',
                'dhcp.rndis0.ipaddress'
            ]:
                try:
                    out = self._run_command(['shell', 'getprop', prop], device_id=device_id).strip()
                    if re.match(r'^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$', out) and not out.startswith('127.'):
                        candidates.append((prop, out))
                except Exception:
                    pass

        # 5. Score candidates
        def score_candidate(iface: str, ip: str) -> int:
            if re.search(r'^(ccmni|rmnet|pdp|wwan|dummy|lo|tun|sit)', iface):
                return -1000
            score = 0
            if re.search(r'^(ap|softap)', iface):
                score += 120  # Hotspot interfaces
            elif re.search(r'^(wlan|swlan|wifi)', iface):
                score += 90   # Wi-Fi client interfaces
            elif re.search(r'^(rndis|usb)', iface):
                score += 40   # USB tethering
            elif re.search(r'^(eth)', iface):
                score += 30   # Ethernet

            # Prioritize standard 192.168.x.x addresses (typical for hotspots & LANs)
            if ip.startswith('192.168.'):
                score += 80
            elif re.match(r'^172\.(1[6-9]|2[0-9]|3[0-1])\.', ip):
                score += 30
            elif ip.startswith('10.'):
                score += 15
            else:
                score -= 50

            # Direct match with PC Wi-Fi default gateway (highest confidence)
            if host_gw and ip == host_gw:
                score += 300

            return score

        scored_candidates = []
        seen = set()
        for iface, ip in candidates:
            if ip not in seen:
                seen.add(ip)
                s = score_candidate(iface, ip)
                if s > 0:
                    scored_candidates.append((s, ip))

        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        if scored_candidates:
            return scored_candidates[0][1]

        # 6. Fallback: Host Wi-Fi default gateway (phone is hotspot)
        if host_gw:
            return host_gw

        return None

    def connect_device(self, host: str, port: int = 5555) -> str:
        """Connect to an Android device over TCP/IP.

        Args:
            host: IP address or host string
            port: Port number (default 5555)

        Returns:
            Output from adb connect command
        """
        host = host.strip()
        if not host:
            raise ValueError("Host/IP address cannot be empty.")
        address = f"{host}:{port}" if ":" not in host else host
        output = self._run_command(['connect', address])
        lower_out = output.lower()
        if 'cannot connect' in lower_out or 'failed to connect' in lower_out or 'unable to connect' in lower_out:
            raise ADBCommandError(output)
        return output

    def pair_device(self, host: str, port: int, pairing_code: str) -> str:
        """Pair with an Android device over Wi-Fi using a pairing code (Android 11+).

        Args:
            host: IP address or hostname
            port: Pairing port number
            pairing_code: 6-digit Wi-Fi pairing code

        Returns:
            Output from adb pair command
        """
        host = host.strip()
        pairing_code = str(pairing_code).strip()
        if not host:
            raise ValueError("Host/IP address cannot be empty.")
        if not pairing_code:
            raise ValueError("Pairing code cannot be empty.")

        address = f"{host}:{port}" if ":" not in host else host
        output = self._run_command(['pair', address, pairing_code])
        lower_out = output.lower()
        if 'failed:' in lower_out or 'error:' in lower_out:
            raise ADBCommandError(output)
        return output

    def disconnect_device(self, address: str) -> str:
        """Disconnect from an ADB device over network.

        Args:
            address: IP:port or device ID

        Returns:
            Output from adb disconnect command
        """
        address = address.strip()
        if not address:
            raise ValueError("Device address cannot be empty.")
        return self._run_command(['disconnect', address])

