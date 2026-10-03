"""ADBManager mixin: connectivity probing via device ping."""

from typing import Dict, Any
from .adb_parse_net import _parse_ping


class _PingMixin:
    """_PingMixin for ADBManager (see adb_manager.py)."""

    def ping_host(self, device_id: str, host: str, count: int = 4) -> Dict[str, Any]:
        """Time the round trip to a host from the device itself.

        Pinged from the device rather than from the host, because the route to
        the internet is the device's and not the workstation's.
        """
        target = (host or '').strip()
        if not target:
            return _parse_ping('', 'No host given', '', count)

        try:
            packets = max(1, min(10, int(count)))
        except (TypeError, ValueError):
            packets = 4

        # Each packet waits up to two seconds for a reply, with slack for the
        # interval between them and for the shell round trip itself.
        stdout, stderr = self._run_probe(
            ['shell', 'ping', '-c', str(packets), '-W', '2', target],
            device_id, timeout=packets * 3 + 15)
        return _parse_ping(f'{stdout}\n{stderr}', stderr, target, packets)

