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
    
    def upload_file(self, device_id: str, local_path: str, remote_path: str) -> None:
        """Upload a file to a device.
        
        Args:
            device_id: Device ID
            local_path: Local file path
            remote_path: Destination path on device
        """
        self.adb.upload_file(device_id, local_path, remote_path)
    
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
    
    def cleanup(self) -> None:
        """Cleanup all resources."""
        self.scrcpy.stop_all()
