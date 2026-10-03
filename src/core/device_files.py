"""DeviceManager mixin: file transfer and filesystem operations."""


class _DeviceFilesMixin:
    """_DeviceFilesMixin (see device_manager.py)."""

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

    def list_dir(self, device_id: str, path: str = '/sdcard/', show_hidden: bool = True,
                 use_exact_sizes: bool = False):
        """List a directory plus writability in one round trip (see ADBManager.list_dir)."""
        return self.adb.list_dir(device_id, path, show_hidden, use_exact_sizes)

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

    def is_directory_writable(self, device_id: str, path: str) -> bool:
        """Check dynamically if a directory on the device is writable."""
        return self.adb.is_directory_writable(device_id, path)

