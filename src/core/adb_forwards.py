"""ADBManager mixin: adb forward/reverse management."""

from typing import Dict, Any, List
from .adb_parse_net import _parse_forward_list


class _ForwardsMixin:
    """_ForwardsMixin for ADBManager (see adb_manager.py)."""

    def list_forwards(self, reverse: bool = False) -> List[Dict[str, str]]:
        """List every forward (or reverse forward) known to the adb server.

        The listing covers all connected devices, so callers interested in one
        device must filter on the 'serial' field.

        Args:
            reverse: List reverse forwards (device to host) instead of forwards
        """
        args = ['reverse', '--list'] if reverse else ['forward', '--list']
        return _parse_forward_list(self._run_command(args))

    def add_forward(self, device_id: str, local: str, remote: str, reverse: bool = False) -> str:
        """Forward a host port to a device port, or the reverse.

        Args:
            device_id: Device ID / serial number
            local: Local endpoint, e.g. 'tcp:8080' or 'localabstract:mysocket'
            remote: Remote endpoint in the same form
            reverse: Set up a reverse forward (device to host) instead
        """
        args = ['reverse' if reverse else 'forward', local, remote]
        return self._run_command(args, device_id)

    def remove_forward(self, device_id: str, local: str, reverse: bool = False) -> str:
        """Remove the forward whose local endpoint matches.

        Args:
            device_id: Device ID / serial number
            local: The local endpoint used when the forward was added
            reverse: Remove a reverse forward instead
        """
        args = ['reverse' if reverse else 'forward', '--remove', local]
        return self._run_command(args, device_id)

    def remove_all_forwards(self, device_id: Optional[str] = None, reverse: bool = False) -> str:
        """Remove every forward, for one device or for all of them.

        Args:
            device_id: Limit the removal to this device; None means every device
            reverse: Remove reverse forwards instead
        """
        args = ['reverse' if reverse else 'forward', '--remove-all']
        return self._run_command(args, device_id)

