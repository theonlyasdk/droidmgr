"""ADBManager mixin: storage, battery, display and OS security info."""

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional
from .adb_parse_health import (_parse_battery_dump, _parse_df, _parse_thermal_dump,
    _parse_uptime)
from .adb_parse_net import _parse_wifi_status, _WIFI_SSID


class _HealthMixin:
    """_HealthMixin for ADBManager (see adb_manager.py)."""

    def get_storage_info(self, device_id: str, step_cb=None) -> Dict[str, str]:
        """Fetch storage space and partition information."""
        info = {}
        if step_cb:
            step_cb("Inspecting filesystem storage and partition usage...")
        try:
            output = self._run_command(['shell', 'df', '-h'], device_id)
        except Exception:
            try:
                output = self._run_command(['shell', 'df'], device_id)
            except Exception as e:
                return {'summary': 'Storage info unavailable', 'raw': str(e)}
        
        info['raw'] = output
        mount_summaries = []
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith('Filesystem') or line.startswith('Sys. filesystem'):
                continue
            parts = line.split()
            if len(parts) >= 5:
                mounted_on = parts[-1]
                if any(m in mounted_on for m in ['/data', '/sdcard', '/storage', '/system', '/vendor', '/product']) or mounted_on == '/':
                    size = parts[1] if len(parts) >= 2 else '?'
                    used = parts[2] if len(parts) >= 3 else '?'
                    free = parts[3] if len(parts) >= 4 else '?'
                    use_pct = parts[4] if len(parts) >= 5 else '?'
                    mount_summaries.append(f"{mounted_on} ({free} free of {size}, {use_pct} used)")
        
        if mount_summaries:
            info['summary'] = ", ".join(mount_summaries)
        else:
            clean_lines = [l.strip() for l in output.splitlines() if l.strip() and not l.startswith('Filesystem')]
            info['summary'] = " | ".join(clean_lines[:5])
        return info

    def get_health_stats(self, device_id: str) -> Dict[str, Any]:
        """Battery, storage, temperature, uptime and WiFi in one pass.

        The five readings are independent, so their adb calls run concurrently.
        A device that refuses one of them still reports the rest: each section
        comes back empty or filled with UNAVAILABLE rather than raising.
        """
        jobs = {
            'battery': lambda: self._run_command(['shell', 'dumpsys', 'battery'], device_id, timeout=15),
            'storage': lambda: self._run_command(['shell', 'df'], device_id, timeout=15),
            'thermal': lambda: self._run_command(['shell', 'dumpsys', 'thermalservice'], device_id, timeout=15),
            'uptime': lambda: self._run_command(['shell', 'cat', '/proc/uptime'], device_id, timeout=15),
            'wifi': lambda: self._run_command(['shell', 'cmd', 'wifi', 'status'], device_id, timeout=15),
        }

        raw: Dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = {name: pool.submit(job) for name, job in jobs.items()}
            for name, future in futures.items():
                try:
                    raw[name] = future.result()
                except Exception:
                    raw[name] = ''

        # 'cmd wifi status' only exists from Android 10; older builds need the dump.
        if not _WIFI_SSID.search(raw['wifi']):
            try:
                raw['wifi'] = self._run_command(['shell', 'dumpsys', 'wifi'], device_id, timeout=15)
            except Exception:
                pass

        return {
            'battery': _parse_battery_dump(raw['battery']),
            'storage': _parse_df(raw['storage']),
            'thermal': _parse_thermal_dump(raw['thermal']),
            'uptime': _parse_uptime(raw['uptime']),
            'wifi': _parse_wifi_status(raw['wifi']),
        }

    def get_battery_info(self, device_id: str, step_cb=None) -> str:
        """Fetch battery level and charging status."""
        if step_cb:
            step_cb("Checking battery health, status, and charge level...")
        try:
            output = self._run_command(['shell', 'dumpsys', 'battery'], device_id)
            level = ""
            status = ""
            for line in output.splitlines():
                line = line.strip()
                if line.startswith('level:'):
                    level = line.split(':', 1)[1].strip() + "%"
                elif line.startswith('status:'):
                    st_val = line.split(':', 1)[1].strip()
                    st_map = {'1': 'Unknown', '2': 'Charging', '3': 'Discharging', '4': 'Not charging', '5': 'Full'}
                    status = st_map.get(st_val, f"Code {st_val}")
            if level:
                return f"Level: {level}" + (f", Status: {status}" if status else "")
            return "Unknown"
        except Exception:
            return "Unknown"

    def get_display_info(self, device_id: str, step_cb=None) -> str:
        """Fetch screen resolution, refresh rate modes, density, and display features."""
        try:
            if step_cb:
                step_cb("Querying display configuration and refresh-rate modes...")
            displays = []
            out = self._run_command(['shell', 'dumpsys', 'display'], device_id, timeout=5)
            for block in re.findall(r'DisplayDeviceInfo\{([^}]+)\}', out):
                name_m = re.search(r'"([^"]+)"', block)
                name = name_m.group(1) if name_m else 'Display'
                res_m = re.search(r'(\d+\s*x\s*\d+)', block)
                res = res_m.group(1).replace(' ', '') if res_m else ''
                fps_m = re.search(r'fps=([\d.]+)', block)
                fps = f"{float(fps_m.group(1)):.0f}Hz" if fps_m else ""
                density_m = re.search(r'density\s*(\d+)', block)
                density = f"{density_m.group(1)}dpi" if density_m else ""
                state_m = re.search(r'state\s+([A-Z_]+)', block)
                state = state_m.group(1) if state_m else ""

                parts = [p for p in [res, fps, density, f"state={state}" if state else ""] if p]
                displays.append(f"{name} ({', '.join(parts)})")

            modes = re.findall(r'supportedModes\s*\[([^\]]+)\]', out)
            modes_str = f" [Supported Modes: {modes[0].strip()}]" if modes else ""

            hdr_caps = re.search(r'HdrCapabilities\{([^}]+)\}', out)
            hdr_str = f" [HDR: {hdr_caps.group(1)}]" if hdr_caps and hdr_caps.group(1) else ""

            if displays:
                return "; ".join(displays) + modes_str + hdr_str

            size_out = self._run_command(['shell', 'wm', 'size'], device_id, timeout=5).strip()
            density_out = self._run_command(['shell', 'wm', 'density'], device_id, timeout=5).strip()
            size = size_out.replace('Physical size:', '').strip()
            density = density_out.replace('Physical density:', '').strip()
            return f"Resolution: {size}, Density: {density}"
        except Exception:
            return "Unknown"

    def get_os_security_info(self, device_id: str, step_cb=None) -> str:
        """Fetch OS fingerprint, security patch dates, and bootloader lock/verified state."""
        try:
            if step_cb:
                step_cb("Querying OS build fingerprint and security patch levels...")
            out = self._run_command(['shell', 'getprop'], device_id, timeout=5)
            props = {}
            for line in out.splitlines():
                if ':' in line:
                    k, _, v = line.partition(':')
                    props[k.strip('[] ')] = v.strip('[] ')
            fp = props.get('ro.build.fingerprint', 'Unknown')
            sec_patch = props.get('ro.build.version.security_patch', 'Unknown')
            vendor_patch = props.get('ro.vendor.build.security_patch', 'Unknown')

            if step_cb:
                step_cb("Checking bootloader lock status and verified boot state...")
            flash_locked_raw = props.get('ro.boot.flash.locked', props.get('ro.boot.vbmeta.device_state', ''))
            if flash_locked_raw in ('1', 'locked'):
                boot_lock = "Locked"
            elif flash_locked_raw in ('0', 'unlocked'):
                boot_lock = "Unlocked"
            else:
                boot_lock = flash_locked_raw or "Unknown"

            boot_state = props.get('ro.boot.verifiedbootstate', '')
            boot_str = f"{boot_lock} (Verified: {boot_state})" if boot_state else boot_lock

            parts = [
                f"Fingerprint: {fp}",
                f"Security Patch: {sec_patch}",
                f"Vendor Patch: {vendor_patch}",
                f"Bootloader: {boot_str}"
            ]
            return " | ".join(parts)
        except Exception:
            return "Unknown"

