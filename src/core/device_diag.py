"""DeviceManager mixin: diagnostics, reports and device information."""


class _DeviceDiagMixin:
    """_DeviceDiagMixin (see device_manager.py)."""

    def get_display_info(self, device_id: str) -> str:
        """Fetch screen resolution and display characteristics."""
        return self.adb.get_display_info(device_id)

    def get_camera_info(self, device_id: str) -> str:
        """Fetch camera count, resolution, FPS, and sensor capabilities."""
        return self.adb.get_camera_info(device_id, scrcpy=self.scrcpy)

    def get_encoder_info(self, device_id: str) -> str:
        """Fetch media encoders from the device."""
        return self.adb.get_encoder_info(device_id, scrcpy=self.scrcpy)

    def get_os_security_info(self, device_id: str) -> str:
        """Fetch OS fingerprint, security patch dates, and bootloader status."""
        return self.adb.get_os_security_info(device_id)

    def get_apps_detailed_summary(self, device_id: str) -> str:
        """Fetch breakdown of system/user apps, sources, and target SDKs."""
        return self.adb.get_apps_detailed_summary(device_id)

    def get_app_permissions_info(self, device_id: str) -> str:
        """Fetch special app access counts and granted runtime permissions."""
        return self.adb.get_app_permissions_info(device_id)

    def get_background_activity_info(self, device_id: str) -> str:
        """Fetch background jobs, RTC alarms, and foreground services."""
        return self.adb.get_background_activity_info(device_id)

    def get_battery_power_info(self, device_id: str) -> str:
        """Fetch wakefulness, wakelocks, and per-UID power statistics."""
        return self.adb.get_battery_power_info(device_id)

    def get_stability_info(self, device_id: str) -> str:
        """Fetch reboot reasons, DropBox crashes/ANRs, and kernel errors."""
        return self.adb.get_stability_info(device_id)

    def get_connectivity_info(self, device_id: str) -> str:
        """Fetch Wi-Fi link speed, signal strength, and cellular network type."""
        return self.adb.get_connectivity_info(device_id)

    def get_audio_info(self, device_id: str) -> str:
        """Fetch audio devices, sample rates, channels, and codec capabilities."""
        return self.adb.get_audio_info(device_id)

    def get_sensors_info(self, device_id: str) -> str:
        """Fetch hardware sensors list, types, vendors, and sampling rates."""
        return self.adb.get_sensors_info(device_id)

    def generate_llm_report(self, device_id: str, progress_callback=None) -> str:
        """Generate a single information-dense report paragraph for LLM analysis."""
        return self.adb.generate_llm_report(device_id, progress_callback=progress_callback, scrcpy=self.scrcpy)

    def collect_bugreport(self, device_id: str, output_path: str) -> str:
        """Collect a bugreport from a device into a zip at output_path.

        Args:
            device_id: Device ID
            output_path: Host path the zip is written to
        """
        return self.adb.collect_bugreport(device_id, output_path)

    def build_bugreport_briefing(self, device_id: str, zip_path: str,
                                 elapsed_seconds: float) -> str:
        """Summarise a collected bugreport for the user to read.

        Args:
            device_id: Device ID
            zip_path: Host path of the collected zip
            elapsed_seconds: How long the collection took
        """
        return self.adb.build_bugreport_briefing(device_id, zip_path,
                                                 elapsed_seconds)

