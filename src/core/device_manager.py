"""High-level device management coordinating ADB and scrcpy operations."""

from typing import List, Dict, Any, Optional
from pathlib import Path
import subprocess

from .adb_manager import ADBManager
from .scrcpy_manager import ScrcpyManager
from .dependency_manager import DependencyManager
from .device_registry import DeviceRegistry
from .device_files import _DeviceFilesMixin
from .device_diag import _DeviceDiagMixin
from .device_net import _DeviceNetMixin
from .device_shell import _DeviceShellMixin


class DeviceManager(_DeviceFilesMixin, _DeviceDiagMixin, _DeviceNetMixin,
                      _DeviceShellMixin):
    """High-level manager coordinating all device operations."""
    
    def __init__(self, adb_path=None, scrcpy_path=None):
        """Initialize the device manager.
        
        Args:
            adb_path: Optional pre-initialized ADB path
            scrcpy_path: Optional pre-initialized scrcpy path
        """
        # Setup dependencies
        if adb_path is None or scrcpy_path is None:
            self.dep_manager = DependencyManager()
            
            if adb_path is None:
                adb_path = self.dep_manager.get_adb_path()
            if scrcpy_path is None:
                scrcpy_path = self.dep_manager.get_scrcpy_path()
        
        # Initialize managers
        self.adb = ADBManager(adb_path)
        self.scrcpy = ScrcpyManager(scrcpy_path)
        # File-backed database of every device ever connected.
        self.registry = DeviceRegistry()
    
    def get_devices(self) -> List[Dict[str, str]]:
        """Get list of all connected devices with additional info.
        
        Returns:
            List of device dictionaries
        """
        devices = self.adb.get_devices()
        
        # Enhance with additional information
        for device in devices:
            device_id = device['id']
            
            # Add model name
            if 'model' not in device:
                device['model'] = self.adb.get_device_model(device_id)
            
            # Add mirroring status
            device['is_mirroring'] = self.scrcpy.is_mirroring(device_id)
        
        return devices

    def get_device_status(self, device_id: str) -> Optional[str]:
        """Get the current ADB status of a specific device (e.g. 'device', 'offline', 'unauthorized')."""
        try:
            for device in self.adb.get_devices():
                if device['id'] == device_id:
                    return device.get('status', '').lower()
        except Exception:
            pass
        return None

    def is_device_ready(self, device_id: str) -> bool:
        """Check if device is connected and in ready ('device') state."""
        return self.get_device_status(device_id) == 'device'
    
    def start_mirroring(self, device_id: str, **kwargs) -> subprocess.Popen:
        """Start screen mirroring for a device.
        
        Args:
            device_id: Device ID
            **kwargs: Additional scrcpy options
            
        Returns:
            The scrcpy process instance
        """
        return self.scrcpy.start_mirroring(device_id, **kwargs)
    
    def stop_mirroring(self, device_id: str) -> None:
        """Stop screen mirroring for a device.
        
        Args:
            device_id: Device ID
        """
        self.scrcpy.stop_mirroring(device_id)
    
    def get_processes(self, device_id: str) -> List[Dict[str, str]]:
        """Get running processes on a device.
        
        Args:
            device_id: Device ID
            
        Returns:
            List of process dictionaries
        """
        return self.adb.get_running_processes(device_id)
    
    def sample_process_load(self, device_id: str, timeout: int = 20):
        """Take one reading of the device's CPU and memory load.
        
        Args:
            device_id: Device ID
            timeout: Seconds to allow for the 'top' run
            
        Returns:
            Dict with the process list, the device CPU summary and its memory summary
        """
        return self.adb.sample_process_load(device_id, timeout)
    
    def kill_process(self, device_id: str, pid: str) -> None:
        """Kill a process on a device.
        
        Args:
            device_id: Device ID
            pid: Process ID
        """
        self.adb.kill_process(device_id, pid)
    
    def get_apps(self, device_id: str) -> List[str]:
        """Get installed applications on a device.
        
        Args:
            device_id: Device ID
            
        Returns:
            List of package names
        """
        return self.adb.get_installed_apps(device_id)
    
    def start_app(self, device_id: str, package: str) -> None:
        """Start an application on a device.
        
        Args:
            device_id: Device ID
            package: Package name
        """
        self.adb.start_app(device_id, package)
    
    def stop_app(self, device_id: str, package: str) -> None:
        """Stop an application on a device.
        
        Args:
            device_id: Device ID
            package: Package name
        """
        self.adb.stop_app(device_id, package)

    def clear_app_data(self, device_id: str, package: str) -> None:
        """Clear an application's data and cache on a device.

        Args:
            device_id: Device ID
            package: Package name
        """
        self.adb.clear_app_data(device_id, package)
        
    def uninstall_app(self, device_id: str, package: str) -> None:
        """Uninstall an application from a device."""
        self.adb.uninstall_app(device_id, package)

    def get_installed_apps_details(self, device_id: str) -> List[Dict[str, Any]]:
        """Get detailed list of installed applications."""
        return self.adb.get_installed_apps_details(device_id)

    def get_health_stats(self, device_id: str) -> Dict[str, Any]:
        """Get battery, storage, temperature, uptime and WiFi in one pass."""
        return self.adb.get_health_stats(device_id)

    def reboot_device(self, device_id: str, target: Optional[str] = None) -> str:
        """Reboot a device, optionally into recovery or the bootloader."""
        return self.adb.reboot_device(device_id, target)

    def get_fastboot_devices(self) -> List[str]:
        """Serials of the devices currently sitting in fastboot mode.
        
        Returns:
            List of device serials, empty when none are or fastboot is absent
        """
        return self.adb.get_fastboot_devices()

    def fastboot_reboot(self, device_id: str) -> str:
        """Restart a fastboot-mode device back into Android.
        
        Args:
            device_id: Device ID
            
        Returns:
            Output from the fastboot reboot command
        """
        return self.adb.fastboot_reboot(device_id)

    def shutdown_device(self, device_id: str) -> str:
        """Power a device off."""
        return self.adb.shutdown_device(device_id)

    def get_root_status(self, device_id: str) -> Dict[str, Any]:
        """Report root availability for a device."""
        return self.adb.get_root_status(device_id)

    def get_empty_dirs(self, device_id: str, path: str) -> set:
        """Names of immediate subdirectories of path that contain no entries."""
        return self.adb.get_empty_dirs(device_id, path)

    def enrich_device_record(self, device_id: str) -> bool:
        """Fetch stable facts + root status once and store them in the registry.

        Returns True when this call did the work. At most one caller per
        session per device gets True (claim_enrichment); the work runs on the
        caller's thread, so call it from a background thread. Returns False
        when another call already handles it or the device is not ready.
        """
        registry = getattr(self, 'registry', None)
        if registry is None or not device_id:
            return False
        if not self.is_device_ready(device_id):
            return False
        if not registry.claim_enrichment(device_id):
            return False
        try:
            try:
                details = self.adb.get_detailed_device_info(device_id)
                if details and not details.get('error'):
                    registry.record_details(device_id, details)
            except Exception:
                pass
            try:
                registry.record_root(device_id, self.adb.get_root_status(device_id))
            except Exception:
                pass
            return True
        except Exception:
            registry.release_enrichment(device_id)
            return False

    def reconnect_devices(self, offline: bool = False) -> str:
        """Ask the adb server to re-establish device connections."""
        return self.adb.reconnect_devices(offline)

    def list_forwards(self, reverse: bool = False) -> List[Dict[str, str]]:
        """List all port forwards (or reverse forwards) known to the adb server."""
        return self.adb.list_forwards(reverse)

    def add_forward(self, device_id: str, local: str, remote: str, reverse: bool = False) -> str:
        """Forward a host port to a device port, or the reverse."""
        return self.adb.add_forward(device_id, local, remote, reverse)

    def remove_forward(self, device_id: str, local: str, reverse: bool = False) -> str:
        """Remove a forward by its local endpoint."""
        return self.adb.remove_forward(device_id, local, reverse)

    def remove_all_forwards(self, device_id: Optional[str] = None, reverse: bool = False) -> str:
        """Remove all forwards, for one device or for all of them."""
        return self.adb.remove_all_forwards(device_id, reverse)


