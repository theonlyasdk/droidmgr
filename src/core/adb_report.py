"""ADBManager mixin: camera/encoder info, LLM reports and bugreports."""

import os
import re
import time
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from .audit_logger import AuditLogger
from .adb_parse_health import (_human_bytes, _format_elapsed, UNAVAILABLE)
from .adb_parse_report import (_parse_bugreport_header, _parse_dumpstate_log,
    _summarise_bugreport_archive)


class _ReportMixin:
    """_ReportMixin for ADBManager (see adb_manager.py)."""

    # A bugreport bundles a full dumpstate collection on the device and then
    # pulls it back, which takes minutes rather than seconds on a typical phone
    # and reports nothing along the way. Half an hour is far past any normal
    # run, so anything past it is a device that has stopped answering.
    BUGREPORT_TIMEOUT = 1800

    def get_camera_info(self, device_id: str, scrcpy=None, step_cb=None) -> str:
        """Fetch camera details including IDs, orientation, max resolution, FPS, and sensor features."""
        cameras = []
        if step_cb:
            step_cb("Querying camera devices and stream capabilities...")
        if scrcpy is not None and hasattr(scrcpy, 'list_cameras'):
            try:
                out = scrcpy.list_cameras(device_id)
                if out and 'List of cameras:' in out:
                    for line in out.splitlines():
                        m = re.search(r'--camera-id=([^\s]+)\s+\(([^)]+)\)', line)
                        if m:
                            cam_id = m.group(1)
                            details = m.group(2)
                            cameras.append(f"Camera {cam_id} ({details})")
            except Exception:
                pass

        if step_cb:
            step_cb("Checking camera hardware features and sensor capabilities...")
        caps = []
        try:
            feat_out = self._run_command(['shell', 'pm', 'list', 'features'], device_id, timeout=5)
            if 'android.hardware.camera.front' in feat_out:
                caps.append('Front')
            if 'android.hardware.camera' in feat_out or 'android.hardware.camera.any' in feat_out:
                caps.append('Back')
            if 'android.hardware.camera.flash' in feat_out:
                caps.append('Flash')
            if 'android.hardware.camera.autofocus' in feat_out:
                caps.append('Autofocus')
            if 'android.hardware.camera.capability.raw' in feat_out:
                caps.append('RAW')
            if 'android.hardware.camera.capability.manual_sensor' in feat_out:
                caps.append('Manual Sensor')
            if 'android.hardware.camera.level.full' in feat_out:
                caps.append('Full Level')
        except Exception:
            pass

        cap_str = f" [Features: {', '.join(caps)}]" if caps else ""

        if cameras:
            return f"{len(cameras)} camera(s): [{'; '.join(cameras)}]{cap_str}"

        # Fallback to dumpsys media.camera
        try:
            count = 'Unknown'
            ids = []
            try:
                out = self._run_command(['shell', 'dumpsys', 'media.camera'], device_id, timeout=5)
                count_m = re.search(r'Number of camera devices:\s*(\d+)', out)
                if count_m:
                    count = count_m.group(1)
                ids = re.findall(r'Device\s+(\d+)\s+maps to', out)
                if not ids:
                    ids = re.findall(r'Camera device\s+(\d+)\s+dynamic info', out)
            except Exception:
                pass

            id_str = f" (IDs: {', '.join(ids)})" if ids else ""
            if count != 'Unknown' or caps:
                return f"{count} camera device(s){id_str}{cap_str}"
            return "None detected"
        except Exception:
            return "Unknown"

    def get_encoder_info(self, device_id: str, scrcpy=None, step_cb=None) -> str:
        """Fetch hardware and software media encoders using scrcpy if available, falling back to codecs config."""
        if step_cb:
            step_cb("Querying hardware and software media encoders...")
        if scrcpy is not None and hasattr(scrcpy, 'list_encoders'):
            try:
                out = scrcpy.list_encoders(device_id)
                if out and 'List of video encoders:' in out:
                    video_encs = []
                    audio_encs = []
                    current = None
                    for line in out.splitlines():
                        if 'List of video encoders:' in line:
                            current = video_encs
                        elif 'List of audio encoders:' in line:
                            current = audio_encs
                        elif current is not None:
                            m = re.search(r'--(?:video|audio)-encoder=([^\s]+)\s+(\((?:hw|sw)\))', line)
                            if m:
                                enc_name = m.group(1)
                                hw_sw = m.group(2)
                                codec_m = re.search(r'--(?:video|audio)-codec=([^\s]+)', line)
                                codec = codec_m.group(1) if codec_m else ''
                                alias = ' (alias)' if 'alias for' in line else ''
                                current.append(f"{codec}:{enc_name} {hw_sw}{alias}")
                    parts = []
                    if video_encs:
                        parts.append(f"Video: [{', '.join(video_encs)}]")
                    if audio_encs:
                        parts.append(f"Audio: [{', '.join(audio_encs)}]")
                    if parts:
                        return "; ".join(parts)
            except Exception:
                pass

        try:
            cmd = ['shell', 'sh', '-c', 'cat /vendor/etc/media_codecs*.xml /system/etc/media_codecs*.xml 2>/dev/null || true']
            out = self._run_command(cmd, device_id, timeout=5)
            codecs = re.findall(r'<MediaCodec\s+name=["\']([^"\']+)["\'](?:[^>]*type=["\']([^"\']+)["\'])?', out)
            encoders = sorted(set(name for name, _ in codecs if 'encoder' in name.lower()))
            if not encoders:
                return "None detected"
            hw = [e for e in encoders if not e.startswith('c2.android.') and not e.startswith('OMX.google.')]
            sw = [e for e in encoders if e.startswith('c2.android.') or e.startswith('OMX.google.')]
            parts = []
            if hw:
                parts.append(f"Hardware: [{', '.join(hw)}]")
            if sw:
                parts.append(f"Software: [{', '.join(sw)}]")
            return "; ".join(parts) if parts else ", ".join(encoders)
        except Exception:
            return "Unknown"

    def generate_llm_report(self, device_id: str, progress_callback=None, scrcpy=None) -> str:
        """Generate a single information-dense report paragraph for LLM analysis with granular progress."""
        total_steps = 35
        current_step = 0

        def step(msg: str):
            nonlocal current_step
            current_step += 1
            pct = min(int((current_step / total_steps) * 98), 98)
            if progress_callback:
                progress_callback(pct, msg)

        info = self.get_detailed_device_info(device_id, step_cb=step)
        os_sec_info = self.get_os_security_info(device_id, step_cb=step)
        storage_info = self.get_storage_info(device_id, step_cb=step)
        battery_info = self.get_battery_info(device_id, step_cb=step)
        battery_power_info = self.get_battery_power_info(device_id, step_cb=step)
        display_info = self.get_display_info(device_id, step_cb=step)
        camera_info = self.get_camera_info(device_id, scrcpy=scrcpy, step_cb=step)
        encoder_info = self.get_encoder_info(device_id, scrcpy=scrcpy, step_cb=step)
        audio_info = self.get_audio_info(device_id, step_cb=step)
        sensors_info = self.get_sensors_info(device_id, step_cb=step)
        conn_info = self.get_connectivity_info(device_id, step_cb=step)
        bg_info = self.get_background_activity_info(device_id, step_cb=step)
        stability_info = self.get_stability_info(device_id, step_cb=step)
        apps_detailed = self.get_apps_detailed_summary(device_id, step_cb=step)
        perms_info = self.get_app_permissions_info(device_id, step_cb=step)

        try:
            step("Enumerating all installed applications...")
            installed_apps = self.get_installed_apps(device_id)
        except Exception:
            installed_apps = []

        try:
            step("Sampling active running processes and CPU/memory...")
            processes = self.get_running_processes(device_id)
        except Exception:
            processes = []

        step("Formulating single information-dense paragraph report...")
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        def clean(val):
            return str(val).replace('\n', ' ').replace('\r', '').strip()

        proc_str_list = [
            f"{p['name']} (PID: {p['pid']}, User: {p['user']}, CPU: {p['cpu']}%, Mem: {p['mem']})"
            for p in processes
        ]
        proc_formatted = ", ".join(proc_str_list) if proc_str_list else "None detected"

        apps_formatted = ", ".join(installed_apps) if installed_apps else "None detected"

        report_paragraph = (
            f"DEVICE LLM SUMMARY REPORT [{timestamp}] | "
            f"Device ID/Serial: {clean(device_id)} | "
            f"Manufacturer: {clean(info.get('manufacturer', 'Unknown'))} | "
            f"Model: {clean(info.get('model', 'Unknown'))} | "
            f"Product Name: {clean(info.get('product_name', 'Unknown'))} | "
            f"Android Version: {clean(info.get('android_version', 'Unknown'))} (Codename: {clean(info.get('android_codename', 'Unknown'))}, Build ID: {clean(info.get('build_id', 'Unknown'))}) | "
            f"Linux Kernel: {clean(info.get('kernel', 'Unknown'))} | "
            f"CPU/SoC: {clean(info.get('cpu', 'Unknown'))} | "
            f"RAM: {clean(info.get('ram', 'Unknown'))} | "
            f"OS & Security: {clean(os_sec_info)} | "
            f"Displays: {clean(display_info)} | "
            f"Cameras: {clean(camera_info)} | "
            f"Audio Capabilities: {clean(audio_info)} | "
            f"Hardware Sensors: {clean(sensors_info)} | "
            f"Media Encoders: {clean(encoder_info)} | "
            f"Battery & Power: {clean(battery_info)}; {clean(battery_power_info)} | "
            f"Connectivity: {clean(conn_info)} | "
            f"Background Activity: {clean(bg_info)} | "
            f"System Stability: {clean(stability_info)} | "
            f"Storage Free Space: {clean(storage_info.get('summary', 'Unknown'))} | "
            f"App Classification & Packages: {clean(apps_detailed)} | "
            f"App Permissions & Access: {clean(perms_info)} | "
            f"Installed Applications ({len(installed_apps)} total packages): [{apps_formatted}] | "
            f"Active Running Processes ({len(processes)} total): [{proc_formatted}]."
        )

        if progress_callback:
            progress_callback(100, "Report generation complete.")
        return report_paragraph

    def collect_bugreport(self, device_id: str, output_path: str) -> str:
        """Collect a bugreport from a device into a zip at output_path.

        Returns the path written. The command reports its own progress on the
        way out, but there is nothing structured to hand back before it lands.
        """
        AuditLogger.log(device_id, "COLLECT_BUGREPORT",
                        os.path.basename(output_path))
        self._run_command(['bugreport', output_path], device_id,
                          timeout=self.BUGREPORT_TIMEOUT)
        if not os.path.isfile(output_path):
            raise RuntimeError(
                f"adb finished but wrote no bugreport at {output_path}")
        return output_path

    def get_adb_version(self) -> str:
        """The adb build in use, which belongs in anything filed as a bug."""
        try:
            first = self._run_command(['version']).strip().splitlines()[0]
            return first.replace('Android Debug Bridge version', '').strip()
        except Exception:
            return UNAVAILABLE

    def build_bugreport_briefing(self, device_id: str, zip_path: str,
                                 elapsed_seconds: float) -> str:
        """Write the summary shown beside a collected bugreport.

        The archive figures are read out of the report itself rather than
        guessed, and the readings taken alongside it describe the device as it
        stood at the moment of collection, which is usually what a bug report
        is really asking about.
        """
        archive = _summarise_bugreport_archive(zip_path)

        try:
            health = self.get_health_stats(device_id)
        except Exception:
            health = {}
        try:
            info = self.get_detailed_device_info(device_id)
        except Exception:
            info = {}

        import datetime

        lines: List[str] = []
        rows: List[str] = []

        def row(label: str, value) -> None:
            rows.append(f"  {label:<14} {value}")

        def heading(title: str) -> None:
            lines.append('')
            lines.append(title)
            lines.append('-' * len(title))

        def section(title: str) -> None:
            if rows:
                heading(title)
                lines.extend(rows)
                rows.clear()

        def degrees(value) -> str:
            return UNAVAILABLE if value is None else f"{value} C"

        def clip(text: str, limit: int = 118) -> str:
            text = ' '.join(str(text).split())
            return text if len(text) <= limit else text[:limit - 3] + '...'

        lines.append('BUG REPORT BRIEFING')
        lines.append('=' * 60)
        try:
            when = datetime.datetime.fromtimestamp(os.path.getmtime(zip_path))
        except OSError:
            when = datetime.datetime.now()
        row('Device', device_id)
        row('Collected', when.strftime('%Y-%m-%d %H:%M:%S'))
        row('Took', _format_elapsed(elapsed_seconds))
        row('adb', self.get_adb_version())
        row('Archive', os.path.basename(zip_path))
        try:
            on_disk = _human_bytes(os.path.getsize(zip_path))
        except OSError:
            on_disk = UNAVAILABLE
        row('Size', f"{on_disk} on disk, {_human_bytes(archive['uncompressed'])} "
                    f"in {archive['entries']} files")
        row('Held at', zip_path)
        section('COLLECTION')

        battery = health.get('battery') or {}
        storage = health.get('storage') or {}
        thermal = health.get('thermal') or {}
        wifi = health.get('wifi') or {}

        if info:
            row('Model', f"{info.get('manufacturer', '?')} {info.get('model', '?')}".strip())
            row('Android', f"{info.get('android_version', '?')} "
                           f"({info.get('build_id', '?')})")
            row('CPU', info.get('cpu', UNAVAILABLE))
            row('RAM', info.get('ram', UNAVAILABLE))
        if health.get('uptime'):
            row('Uptime', _format_elapsed(health['uptime']))
        if battery:
            level = battery.get('level')
            row('Battery', f"{level}%, {battery.get('status', '?')}, "
                           f"{battery.get('temperature', '?')} C, "
                           f"{battery.get('health', '?')}"
                           + (f", on {battery['powered_by']}"
                              if battery.get('powered_by') not in (None, '', 'None') else ''))
        if storage:
            row('Storage', f"{_human_bytes(storage.get('free', 0))} free of "
                           f"{_human_bytes(storage.get('total', 0))} "
                           f"({storage.get('percent', '?')}% used) on "
                           f"{storage.get('mount', '?')}")
        if thermal:
            # Android names its "no throttling" status 'None', which reads like
            # a missing value in a sentence.
            state = thermal.get('status') or UNAVAILABLE
            if state == 'None':
                state = 'no throttling'
            row('Temperature', f"CPU {degrees(thermal.get('cpu'))}, "
                               f"battery {degrees(thermal.get('battery'))}, "
                               f"peak {degrees(thermal.get('max'))} ({state})")
        if wifi:
            row('WiFi', f"{wifi.get('ssid') or 'not connected'} "
                        f"[{wifi.get('state') or UNAVAILABLE}]")
        section('DEVICE AT COLLECTION')

        header = archive['header']
        for label, key in (('Build', 'build'), ('Fingerprint', 'fingerprint'),
                           ('Radio', 'radio'), ('Bootloader', 'bootloader'),
                           ('Kernel', 'kernel'), ('Uptime', 'uptime'),
                           ('Format', 'format')):
            if header.get(key):
                row(label, clip(header[key]))
        section('AS THE REPORT SEES IT')

        heading('WHAT THE ARCHIVE HOLDS')
        for name, count in archive['sections']:
            lines.append(f"  {count:>5}  {name}")
        if archive['tombstones']:
            lines.append('')
            lines.append(f"  Includes {archive['tombstones']} tombstone file(s), "
                         f"each one a native crash worth reading first.")
        if archive['anr_traces']:
            lines.append(f"  Includes {archive['anr_traces']} ANR trace file(s): "
                         f"the app was not responding.")
        if archive['largest']:
            lines.append('')
            lines.append('  Largest members:')
            for name, size in archive['largest']:
                lines.append(f"    {_human_bytes(size):>10}  {name}")

        if archive['collection_notes']:
            heading('COLLECTION GAPS')
            lines.append('  dumpstate could not collect:')
            for note in archive['collection_notes']:
                lines.append(f"    - {note}")

        heading('NOTE')
        lines.append('  A bugreport can hold personal data: account names, contact')
        lines.append('  labels, message text and file listings. Read it before you')
        lines.append('  share it, and prefer the main .txt over the whole archive')
        lines.append('  when a report will do.')

        return '\n'.join(lines)

