"""ADBManager mixin: diagnostics summaries (apps, power, network, sensors)."""

import re
from typing import Dict, Any, List, Optional


class _DiagMixin:
    """_DiagMixin for ADBManager (see adb_manager.py)."""

    def get_apps_detailed_summary(self, device_id: str, step_cb=None) -> str:
        """Fetch breakdown of system/user apps, install sources, target SDKs, and enabled state."""
        try:
            if step_cb:
                step_cb("Classifying system packages...")
            sys_out = self._run_command(['shell', 'pm', 'list', 'packages', '-s'], device_id, timeout=5)
            sys_count = len([l for l in sys_out.splitlines() if l.startswith('package:')])

            if step_cb:
                step_cb("Classifying third-party packages and install sources...")
            user_out = self._run_command(['shell', 'pm', 'list', 'packages', '-3', '-i'], device_id, timeout=5)
            user_lines = [l for l in user_out.splitlines() if l.startswith('package:')]
            user_count = len(user_lines)

            if step_cb:
                step_cb("Checking disabled packages...")
            dis_out = self._run_command(['shell', 'pm', 'list', 'packages', '-d'], device_id, timeout=5)
            dis_count = len([l for l in dis_out.splitlines() if l.startswith('package:')])

            sources = {}
            user_pkgs = []
            for l in user_lines:
                pkg_m = re.search(r'package:([^\s]+)', l)
                inst_m = re.search(r'installer=([^\s]+)', l)
                pkg = pkg_m.group(1) if pkg_m else ''
                inst = inst_m.group(1) if inst_m else 'sideload/unknown'
                if inst == 'com.android.vending':
                    inst_label = 'Google Play'
                elif 'xiaomi' in inst:
                    inst_label = 'Xiaomi Store'
                elif inst in ('null', 'None'):
                    inst_label = 'Sideloaded'
                else:
                    inst_label = inst
                sources[inst_label] = sources.get(inst_label, 0) + 1
                if pkg:
                    user_pkgs.append(pkg)

            src_str = ", ".join(f"{k}: {v}" for k, v in sorted(sources.items())) if sources else "None"

            app_details = []
            for pkg in user_pkgs[:5]:
                try:
                    if step_cb:
                        step_cb(f"Inspecting package metadata for {pkg}...")
                    dump = self._run_command(['shell', 'dumpsys', 'package', pkg], device_id, timeout=4)
                    vname = re.search(r'versionName=([^\s]+)', dump)
                    vcode = re.search(r'versionCode=(\d+)', dump)
                    tsdk = re.search(r'targetSdk=(\d+)', dump)
                    vn = vname.group(1) if vname else '?'
                    vc = vcode.group(1) if vcode else '?'
                    ts = tsdk.group(1) if tsdk else '?'
                    app_details.append(f"{pkg} (v{vn} [{vc}], targetSDK={ts})")
                except Exception:
                    app_details.append(pkg)

            apps_detail_str = f" [Sample User Apps: {', '.join(app_details)}]" if app_details else ""
            return (f"Classification: {sys_count} system, {user_count} user ({dis_count} disabled); "
                    f"Install Sources: [{src_str}]{apps_detail_str}")
        except Exception:
            return "Unknown"

    def get_app_permissions_info(self, device_id: str, step_cb=None) -> str:
        """Fetch special app access counts and granted runtime permissions."""
        try:
            special_ops = [
                ('SYSTEM_ALERT_WINDOW', 'Overlay/AlertWindow'),
                ('REQUEST_INSTALL_PACKAGES', 'InstallUnknownApps'),
                ('WRITE_SETTINGS', 'WriteSettings'),
                ('MANAGE_EXTERNAL_STORAGE', 'AllFilesAccess')
            ]
            special_counts = []
            for op, label in special_ops:
                try:
                    if step_cb:
                        step_cb(f"Checking special app access: {label}...")
                    res = self._run_command(['shell', 'cmd', 'appops', 'query-op', op, 'allow'], device_id, timeout=3)
                    cnt = len([l for l in res.splitlines() if l.strip()])
                    special_counts.append(f"{label}: {cnt}")
                except Exception:
                    pass
            spec_str = ", ".join(special_counts) if special_counts else "Unavailable"

            if step_cb:
                step_cb("Querying user package runtime permissions...")
            user_out = self._run_command(['shell', 'pm', 'list', 'packages', '-3'], device_id, timeout=5)
            user_pkgs = [l.replace('package:', '').strip() for l in user_out.splitlines() if l.startswith('package:')]
            granted_summary = []
            for pkg in user_pkgs[:4]:
                try:
                    dump = self._run_command(['shell', 'dumpsys', 'package', pkg], device_id, timeout=4)
                    runtime_section = re.search(r'runtime permissions:(.*?)(?:\n\s*\n|Packages:|\Z)', dump, re.DOTALL)
                    if runtime_section:
                        granted = [m.split('.')[-1] for m in re.findall(r'([a-zA-Z0-9_.]+):\s*granted=true', runtime_section.group(1))]
                        if granted:
                            granted_summary.append(f"{pkg}: [{', '.join(granted)}]")
                except Exception:
                    pass
            grant_str = f"; User App Granted Runtime Permissions: [{'; '.join(granted_summary)}]" if granted_summary else "; User App Granted Runtime Permissions: [None]"
            return f"Special App Access: [{spec_str}]{grant_str}"
        except Exception:
            return "Unknown"

    def get_background_activity_info(self, device_id: str, step_cb=None) -> str:
        """Fetch background jobs, RTC alarms, and active foreground services."""
        try:
            if step_cb:
                step_cb("Checking JobScheduler registered and active jobs...")
            jobs_out = self._run_command(['shell', 'dumpsys', 'jobscheduler'], device_id, timeout=5)
            registered_jobs = len(re.findall(r'JOB #', jobs_out))
            active_jobs = len(re.findall(r'Active jobs:', jobs_out))

            if step_cb:
                step_cb("Inspecting AlarmManager wakeup alarms and batches...")
            alarm_out = self._run_command(['shell', 'dumpsys', 'alarm'], device_id, timeout=5)
            rtc_wakeups = len(re.findall(r'RTC_WAKEUP', alarm_out))
            total_alarms_m = re.search(r'Total number of alarms:\s*(\d+)', alarm_out)
            total_alarms = total_alarms_m.group(1) if total_alarms_m else 'N/A'

            if step_cb:
                step_cb("Inspecting active foreground services...")
            fgs_out = self._run_command(['shell', 'dumpsys', 'activity', 'services'], device_id, timeout=5)
            fgs_count = len(re.findall(r'isForeground=true', fgs_out))

            return (f"Scheduled Jobs: {registered_jobs} registered, {active_jobs} active; "
                    f"Alarms: {total_alarms} total ({rtc_wakeups} RTC_WAKEUP); "
                    f"Foreground Services: {fgs_count} active")
        except Exception:
            return "Unknown"

    def get_battery_power_info(self, device_id: str, step_cb=None) -> str:
        """Fetch wakefulness, active wakelocks, and per-UID power statistics."""
        try:
            if step_cb:
                step_cb("Checking power manager wakefulness and active wakelocks...")
            power_out = self._run_command(['shell', 'dumpsys', 'power'], device_id, timeout=5)
            wakefulness_m = re.search(r'mWakefulness=([A-Za-z]+)', power_out)
            wakefulness = wakefulness_m.group(1) if wakefulness_m else 'Unknown'
            wakelock_count_m = re.search(r'Wake Locks:\s*size=(\d+)', power_out)
            wl_count = wakelock_count_m.group(1) if wakelock_count_m else '0'
            partial_wl = re.findall(r'PARTIAL_WAKE_LOCK\s+\'([^\']+)\'', power_out)
            wl_summary = f"{wl_count} active" + (f" ({', '.join(partial_wl[:3])})" if partial_wl else "")

            if step_cb:
                step_cb("Reading per-UID battery drain and power consumption...")
            bstat_out = self._run_command(['shell', 'dumpsys', 'batterystats', '--charged'], device_id, timeout=5)
            drain_lines = []
            in_drain = False
            for line in bstat_out.splitlines():
                if 'Estimated power use (mAh):' in line:
                    in_drain = True
                    continue
                if in_drain:
                    if line.startswith('    ') and not line.startswith('      '):
                        clean_line = line.strip()
                        if clean_line and not clean_line.startswith('Capacity:'):
                            m = re.match(r'([^:]+):\s*([0-9.]+)', clean_line)
                            if m:
                                drain_lines.append(f"{m.group(1)}: {m.group(2)} mAh")
                            else:
                                drain_lines.append(clean_line.split('(')[0].strip())
                            if len(drain_lines) >= 4:
                                break
                    elif line and not line.startswith(' '):
                        break
            drain_str = f"; Top Power Drains: [{', '.join(drain_lines)}]" if drain_lines else ""

            return f"Wakefulness: {wakefulness}; Wakelocks: {wl_summary}{drain_str}"
        except Exception:
            return "Unknown"

    def get_stability_info(self, device_id: str, step_cb=None) -> str:
        """Fetch reboot reasons, DropBox crashes/ANRs, and kernel errors."""
        try:
            if step_cb:
                step_cb("Checking reboot reason and system boot parameters...")
            reboot_reason = self._run_command(['shell', 'getprop', 'sys.boot.reason'], device_id, timeout=3).strip()
            if not reboot_reason:
                reboot_reason = self._run_command(['shell', 'getprop', 'ro.boot.bootreason'], device_id, timeout=3).strip() or "Unknown"

            if step_cb:
                step_cb("Querying DropBox stability events, crashes, and ANRs...")
            dropbox = self._run_command(['shell', 'dumpsys', 'dropbox', '--print'], device_id, timeout=5)
            app_crashes = len(re.findall(r'(?:data_app_crash|system_app_crash)', dropbox))
            anrs = len(re.findall(r'(?:data_app_anr|system_app_anr)', dropbox))
            tombstones = len(re.findall(r'tombstone', dropbox))
            native_crashes = len(re.findall(r'system_server_crash|native_crash', dropbox))

            if step_cb:
                step_cb("Checking kernel panic and system error logs...")
            kmsg_err = self._run_command(['shell', 'dmesg -r | grep -iE "(panic|fatal|oops)" | tail -n 3 2>/dev/null || true'], device_id, timeout=3).strip()
            if not kmsg_err:
                kmsg_err = "None detected"

            return (f"Reboot Reason: {reboot_reason}; "
                    f"DropBox Stability Events: {app_crashes} app crash(es), {anrs} ANR(s), "
                    f"{tombstones} tombstone(s), {native_crashes} system server crash(es); "
                    f"Kernel Panic/Errors: {kmsg_err}")
        except Exception:
            return "Unknown"

    def get_connectivity_info(self, device_id: str, step_cb=None) -> str:
        """Fetch Wi-Fi link speed, signal strength, and cellular network type."""
        try:
            if step_cb:
                step_cb("Checking Wi-Fi link speed, signal strength, and SSID...")
            wifi_out = self._run_command(['shell', 'dumpsys', 'wifi'], device_id, timeout=5)
            ssid_m = re.search(r'SSID:\s*"?([^",\n]+)"?', wifi_out)
            rssi_m = re.search(r'RSSI:\s*(-?\d+)', wifi_out)
            speed_m = re.search(r'[Ll]ink speed:\s*(\d+\s*[Mm]bps)', wifi_out)
            freq_m = re.search(r'[Ff]requency:\s*(\d+\s*[Mm][Hh]z)', wifi_out)

            wifi_parts = []
            if ssid_m and ssid_m.group(1) not in ('<unknown ssid>', 'None'):
                wifi_parts.append(f"SSID: \"{ssid_m.group(1)}\"")
            if rssi_m and rssi_m.group(1) != '-127':
                wifi_parts.append(f"Signal: {rssi_m.group(1)} dBm")
            if speed_m:
                wifi_parts.append(f"Link Speed: {speed_m.group(1)}")
            if freq_m:
                wifi_parts.append(f"Freq: {freq_m.group(1)}")
            wifi_str = f"Wi-Fi: [{', '.join(wifi_parts)}]" if wifi_parts else "Wi-Fi: Disconnected/Idle"

            if step_cb:
                step_cb("Querying cellular network type and SIM state...")
            cell_type = self._run_command(['shell', 'getprop', 'gsm.network.type'], device_id, timeout=3).strip()
            if not cell_type or cell_type == 'Unknown,Unknown':
                tele_reg = self._run_command(['shell', 'dumpsys', 'telephony.registry'], device_id, timeout=4)
                data_net = re.search(r'mDataNetworkType=([^\s]+)', tele_reg)
                cell_type = data_net.group(1) if data_net else 'None/Unknown'

            return f"{wifi_str} | Cellular Network Type: {cell_type}"
        except Exception:
            return "Unknown"

    def get_audio_info(self, device_id: str, step_cb=None) -> str:
        """Fetch audio devices, supported sample rates, channel configurations, and codecs."""
        try:
            if step_cb:
                step_cb("Querying audio devices, sample rates, and channel masks...")
            ap_out = self._run_command(['shell', 'dumpsys', 'media.audio_policy'], device_id, timeout=5)
            devices = re.findall(r'tag name:\s*([^\n\r]+)', ap_out)
            primary_devs = sorted(set(d.strip() for d in devices if d.strip() in ['Earpiece', 'Speaker', 'Wired Headset', 'BT SCO', 'BT A2DP', 'USB Headset']))
            dev_str = ", ".join(primary_devs) if primary_devs else ", ".join(sorted(set(d.strip() for d in devices[:4])))

            rates_raw = re.findall(r'rates:\s*([^\n\r]+)', ap_out)
            all_rates = set()
            for r in rates_raw:
                for rate in r.split(','):
                    rate = rate.strip()
                    if rate.isdigit():
                        all_rates.add(int(rate))
            rates_str = ", ".join(f"{r}Hz" for r in sorted(all_rates)) if all_rates else "44100Hz, 48000Hz"

            channels = re.findall(r'channel masks:\s*([^\n\r]+)', ap_out)
            chan_types = set()
            for c in channels:
                if '0x0001' in c or '0x0010' in c:
                    chan_types.add('Mono')
                if '0x0003' in c or '0x000c' in c:
                    chan_types.add('Stereo')
                if '0x003f' in c or '5.1' in c:
                    chan_types.add('5.1 Surround')
            chan_str = ", ".join(sorted(chan_types)) if chan_types else "Mono, Stereo"

            if step_cb:
                step_cb("Querying audio codec formats and capabilities...")
            codecs_out = self._run_command(['shell', 'cat /vendor/etc/media_codecs*.xml /system/etc/media_codecs*.xml 2>/dev/null || true'], device_id, timeout=5)
            audio_codecs = sorted(set(re.findall(r'audio/([a-zA-Z0-9_\-]+)', codecs_out)))
            codec_str = ", ".join(audio_codecs) if audio_codecs else "AAC, AMR, FLAC, MP3, Opus, Vorbis"

            return f"Devices: [{dev_str}]; Sample Rates: [{rates_str}]; Channels: [{chan_str}]; Codecs: [{codec_str}]"
        except Exception:
            return "Unknown"

    def get_sensors_info(self, device_id: str, step_cb=None) -> str:
        """Fetch hardware sensors list including names, types, vendors, and sampling rates."""
        try:
            if step_cb:
                step_cb("Querying hardware sensors and sampling rates...")
            sensor_out = self._run_command(['shell', 'dumpsys', 'sensorservice'], device_id, timeout=5)
            lines = sensor_out.splitlines()
            sensors = []
            for i, l in enumerate(lines):
                m = re.match(r'0x[0-9a-fA-F]+\)\s+([^|]+)\|\s*([^|]+)\|\s*ver:\s*\d+\s*\|\s*type:\s*([^(|]+)', l)
                if m:
                    name = m.group(1).strip()
                    vendor = m.group(2).strip()
                    stype = m.group(3).strip()
                    rates = ""
                    if i + 1 < len(lines):
                        next_l = lines[i+1]
                        min_m = re.search(r'minRate=([0-9.]+Hz)', next_l)
                        max_m = re.search(r'maxRate=([0-9.]+Hz)', next_l)
                        if min_m and max_m:
                            rates = f", rates: {min_m.group(1)}-{max_m.group(1)}"
                        elif min_m:
                            rates = f", rate: {min_m.group(1)}"
                    sensors.append(f"{name} ({vendor}, {stype}{rates})")

            total_hw = len(sensors)
            if sensors:
                return f"{total_hw} hardware sensors: [{'; '.join(sensors)}]"
            return "None detected"
        except Exception:
            return "Unknown"

