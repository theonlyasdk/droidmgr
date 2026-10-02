"""High-level device management coordinating ADB and scrcpy operations."""

from typing import List, Dict, Any, Optional
from pathlib import Path
import subprocess

from .adb_manager import ADBManager
from .scrcpy_manager import ScrcpyManager
from .dependency_manager import DependencyManager


class DeviceManager:
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
        
    def uninstall_app(self, device_id: str, package: str) -> None:
        """Uninstall an application from a device."""
        self.adb.uninstall_app(device_id, package)

    def get_installed_apps_details(self, device_id: str) -> List[Dict[str, Any]]:
        """Get detailed list of installed applications."""
        return self.adb.get_installed_apps_details(device_id)


    
    def list_files(self, device_id: str, path: str = '/sdcard/', show_hidden: bool = True, use_exact_sizes: bool = False) -> List[Dict[str, Any]]:
        """List files in a directory on a device.
        
        Args:
            device_id: Device ID
            path: Directory path
            show_hidden: Whether to show hidden files
            use_exact_sizes: Whether to show sizes in bytes
            
        Returns:
            List of file dictionaries
        """
        return self.adb.list_files(device_id, path, show_hidden, use_exact_sizes)
    
    def download_file(self, device_id: str, remote_path: str, local_path: str) -> None:
        """Download a file from a device.
        
        Args:
            device_id: Device ID
            remote_path: Path on device
            local_path: Local destination path
        """
        self.adb.download_file(device_id, remote_path, local_path)

    def backup_filesystem(self, device_id: str, destination: str, cancel_event, progress_callback=None,
                          remote_root: str = '/', parallelism: int = 4, exclusions=None, only_paths=None,
                          verify_checksums=False) -> bool:
        """Back up accessible device files after indexing the filesystem."""
        return self.adb.backup_filesystem(
            device_id, destination, cancel_event, progress_callback, remote_root, parallelism, exclusions,
            only_paths, verify_checksums
        )

    def estimate_filesystem_size(self, device_id: str, remote_root: str = '/', cancel_event=None):
        return self.adb.estimate_filesystem_size(device_id, remote_root, cancel_event)
    
    def upload_file(self, device_id: str, local_path: str, remote_path: str, cancel_event=None) -> None:
        """Upload a file to a device.
        
        Args:
            device_id: Device ID
            local_path: Local file path
            remote_path: Destination path on device
        """
        self.adb.upload_file(device_id, local_path, remote_path, cancel_event)
    
    def delete_file(self, device_id: str, remote_path: str) -> None:
        """Delete a file on a device.
        
        Args:
            device_id: Device ID
            remote_path: Path on device
        """
        self.adb.delete_file(device_id, remote_path)

    def rename_file(self, device_id: str, old_path: str, new_path: str) -> None:
        """Rename a file on a device."""
        self.adb.rename_file(device_id, old_path, new_path)

    def move_file(self, device_id: str, src_path: str, dest_path: str) -> None:
        """Move a file on a device."""
        self.adb.move_file(device_id, src_path, dest_path)

    def copy_file(self, device_id: str, src_path: str, dest_path: str) -> None:
        """Copy a file on a device."""
        self.adb.copy_file(device_id, src_path, dest_path)

    def make_directory(self, device_id: str, path: str) -> None:
        """Create a directory on the device."""
        self.adb.make_directory(device_id, path)


    def generate_llm_report(self, device_id: str, progress_callback=None) -> str:
        """Generate a single information-dense report paragraph for LLM analysis."""
        return self.adb.generate_llm_report(device_id, progress_callback)
    
    def is_directory_writable(self, device_id: str, path: str) -> bool:
        """Check dynamically if a directory on the device is writable."""
        return self.adb.is_directory_writable(device_id, path)

    def enable_tcpip(self, device_id: str, port: int = 5555) -> str:
        """Enable ADB over TCP/IP on the device."""
        return self.adb.enable_tcpip(device_id, port)

    def get_device_ip(self, device_id: Optional[str] = None) -> Optional[str]:
        """Get the Wi-Fi or Hotspot IP address of the device or network."""
        return self.adb.get_device_ip(device_id)

    def connect_device(self, host: str, port: int = 5555) -> str:
        """Connect to an ADB device over network."""
        return self.adb.connect_device(host, port)

    def pair_device(self, host: str, port: int, pairing_code: str) -> str:
        """Pair with an Android device over Wi-Fi using a pairing code (Android 11+)."""
        return self.adb.pair_device(host, port, pairing_code)

    def disconnect_device(self, address: str) -> str:
        """Disconnect an ADB device over network."""
        return self.adb.disconnect_device(address)

    def get_logcat(self, device_id: str):
        """Start streaming `adb logcat -v brief` for a device."""
        return self.adb.get_logcat(device_id)

    def clear_logcat(self, device_id: str) -> None:
        """Clear the on-device logcat buffers (`adb logcat -c`)."""
        self.adb.clear_logcat(device_id)

    def run_shell_command(self, device_id: str, command: str, timeout: int = 30):
        """Run a single shell command on a device, returning (returncode, stdout, stderr)."""
        return self.adb.run_shell_command(device_id, command, timeout)

    def start_shell_session(self, device_id: str, allocate_tty: bool = True):
        """Start an interactive `adb shell` session for a device."""
        return self.adb.start_shell_session(device_id, allocate_tty)

    def capture_screenshot(self, device_id: str) -> bytes:
        """Capture the current screen as PNG bytes."""
        return self.adb.capture_screenshot(device_id)

    def start_screenrecord(self, device_id: str, remote_path: str, time_limit: int = 180,
                           bit_rate: Optional[str] = None, size: Optional[str] = None):
        """Start `adb shell screenrecord`, writing the video to a device path."""
        return self.adb.start_screenrecord(device_id, remote_path, time_limit, bit_rate, size)

    def stop_screenrecord(self, device_id: str) -> bool:
        """Ask an on-device screenrecord to stop and finalize the MP4."""
        return self.adb.stop_screenrecord(device_id)

    def cleanup(self) -> None:
        """Cleanup all resources."""
        self.scrcpy.stop_all()


