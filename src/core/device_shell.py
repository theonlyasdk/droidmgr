"""DeviceManager mixin: shell, capture, wireless and input operations."""


class _DeviceShellMixin:
    """_DeviceShellMixin (see device_manager.py)."""

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

    def get_apk_paths(self, device_id: str, package: str) -> List[Dict[str, str]]:
        """List the APK files behind an installed package."""
        return self.adb.get_apk_paths(device_id, package)

    def extract_apk(self, device_id: str, package: str, destination: str,
                    version: str = '') -> Dict[str, Any]:
        """Pull an installed package's APK, and its splits, to a local folder."""
        return self.adb.extract_apk(device_id, package, destination, version)

    def send_keyevent(self, device_id: str, keycode: int) -> bool:
        """Send an Android keyevent to the device."""
        return self.adb.send_keyevent(device_id, keycode)

    def send_text(self, device_id: str, text: str) -> bool:
        """Send text input to the device."""
        return self.adb.send_text(device_id, text)

    def set_clipboard_text(self, device_id: str, text: str) -> bool:
        """Set device clipboard text."""
        return self.adb.set_clipboard_text(device_id, text)

    def rotate_display(self, device_id: str) -> int:
        """Rotate screen orientation to the next 90-degree step."""
        return self.adb.rotate_display(device_id)

    def cleanup(self) -> None:
        """Cleanup all resources."""
        self.scrcpy.stop_all()

