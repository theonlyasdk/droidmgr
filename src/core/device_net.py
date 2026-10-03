"""DeviceManager mixin: network inspection operations."""


class _DeviceNetMixin:
    """_DeviceNetMixin (see device_manager.py)."""

    def get_network_info(self, device_id: str) -> Dict[str, Any]:
        """Connection details: network name, address, gateway and name servers.

        Args:
            device_id: Device ID

        Returns:
            Dict with the wifi reading, every interface, the active one,
            the default route and the name servers in use.
        """
        return self.adb.get_network_info(device_id)

    def get_app_network_usage(self, device_id: str) -> List[Dict[str, Any]]:
        """Per-app received and sent bytes since boot, largest first.

        Args:
            device_id: Device ID
        """
        return self.adb.get_app_network_usage(device_id)

    def get_active_connections(self, device_id: str) -> List[Dict[str, Any]]:
        """Sockets the device currently holds open, with their owning app.

        Args:
            device_id: Device ID
        """
        return self.adb.get_active_connections(device_id)

    def get_cellular_info(self, device_id: str) -> Dict[str, Any]:
        """Cellular telephony status: SIM, carrier, network type, and data state."""
        return self.adb.get_cellular_info(device_id)

    def get_routing_table(self, device_id: str) -> List[Dict[str, Any]]:
        """Routing table entries across routing tables."""
        return self.adb.get_routing_table(device_id)

    def get_connectivity_history(self, device_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Timestamped connectivity requests and state changes."""
        return self.adb.get_connectivity_history(device_id, limit=limit)

    def get_network_requests(self, device_id: str) -> List[Dict[str, Any]]:
        """Which apps have registered for network access, and on what.

        Args:
            device_id: Device ID
        """
        return self.adb.get_network_requests(device_id)

    def ping_host(self, device_id: str, host: str, count: int = 4) -> Dict[str, Any]:
        """Time the round trip to a host from the device itself.

        Args:
            device_id: Device ID
            host: Hostname or address to ping
            count: Packets to send, 1 to 10

        Returns:
            Dict of the round-trip times, the loss and any error the host gave.
        """
        return self.adb.ping_host(device_id, host, count)

