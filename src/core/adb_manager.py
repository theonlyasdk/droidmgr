"""Manages ADB operations for Android devices."""

import os
import subprocess
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import re
import time
import queue
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import hashlib
import posixpath
import shlex
import tempfile
import zipfile
from .audit_logger import AuditLogger
from . import apk_icon

# An app installed under one of these paths is part of the system image.
SYSTEM_APP_PATHS = ('/system', '/product', '/vendor', '/system_ext', '/odm', '/apex')

# Package ids that name their app something other than the last dotted segment.
# The device does not expose an app's label without parsing the APK's resources,
# so well-known apps are listed here and everything else is guessed from its id.
_KNOWN_APP_NAMES = {
    'com.android.settings': 'Settings',
    'com.android.systemui': 'System UI',
    'com.android.chrome': 'Chrome',
    'com.android.vending': 'Google Play Store',
    'com.android.packageinstaller': 'Package Installer',
    'com.android.permissioncontroller': 'Permission Controller',
    'com.android.shell': 'Shell',
    'com.android.phone': 'Phone',
    'com.android.dialer': 'Phone',
    'com.android.mms': 'Messages',
    'com.android.camera2': 'Camera',
    'com.android.gallery3d': 'Gallery',
    'com.android.documentsui': 'Files',
    'com.android.contacts': 'Contacts',
    'com.android.deskclock': 'Clock',
    'com.android.calendar': 'Calendar',
    'com.android.camera': 'Camera',
    'com.android.email': 'Email',
    'com.google.android.youtube': 'YouTube',
    'com.google.android.apps.maps': 'Google Maps',
    'com.google.android.keep': 'Google Keep',
    'com.google.android.calculator': 'Calculator',
    'com.google.android.calendar': 'Calendar',
    'com.google.android.contacts': 'Contacts',
    'com.google.android.deskclock': 'Clock',
    'com.google.android.dialer': 'Phone',
    'com.google.android.apps.photos': 'Google Photos',
    'com.google.android.apps.docs': 'Google Drive',
    'com.google.android.apps.messaging': 'Messages',
    'com.google.android.gm': 'Gmail',
    'com.google.android.googlequicksearchbox': 'Google Search',
    'com.google.android.apps.youtube.creator': 'YouTube Studio',
    'com.google.android.filemanager': 'Files',
    'com.google.android.apps.drive': 'Google Drive',
    'com.google.android.music': 'Google Play Music',
    'com.google.android.videos': 'Google TV',
    'com.google.android.apps.podcasts': 'Google Podcasts',
    'com.google.android.apps.books': 'Google Play Books',
    'com.google.android.apps.tachyon': 'Device Info HW',
    'com.google.android.gms': 'Google Play Services',
    'com.google.android.googlequicksearch': 'Google Search',
    'com.google.android.apps.translate': 'Google Translate',
    'com.google.android.apps.snapchat': 'Snapchat',
    'com.whatsapp': 'WhatsApp',
    'com.whatsapp.w4b': 'WhatsApp Business',
    'com.facebook.katana': 'Facebook',
    'com.facebook.orca': 'Messenger',
    'com.facebook.system': 'Facebook App Manager',
    'com.instagram.android': 'Instagram',
    'org.telegram.messenger': 'Telegram',
    'org.telegram.messenger.web': 'Telegram Web',
    'com.twitter.android': 'X (Twitter)',
    'com.linkedin.android': 'LinkedIn',
    'com.reddit.frontpage': 'Reddit',
    'com.pinterest': 'Pinterest',
    'com.snapchat.android': 'Snapchat',
    'com.zhiliaoapp.musically': 'TikTok',
    'com.spotify.music': 'Spotify',
    'com.netflix.mediaclient': 'Netflix',
    'com.amazon.mShop.android.shopping': 'Amazon Shopping',
    'com.amazon.mShop.android.hardwarereview': 'Amazon Reviews',
    'com.amazon.avod': 'Prime Video',
    'com.ubercab': 'Uber',
    'com.airbnb.android': 'Airbnb',
    'com.duolingo': 'Duolingo',
    'com.slack': 'Slack',
    'com.discord': 'Discord',
    'org.thoughtworks.secureshell': 'Termux',
    'com.termux': 'Termux',
    'org.mozilla.firefox': 'Firefox',
    'org.mozilla.klar': 'Firefox Focus',
    'org.chromium.chrome': 'Chromium',
    'org.videolan.vlc': 'VLC',
    'notion.id': 'Notion',
    'app.zophop': 'Chalo',
    'com.obsidian': 'Obsidian',
    'com.microsoft.teams': 'Microsoft Teams',
    'com.microsoft.office.outlook': 'Outlook',
    'com.microsoft.office.word': 'Word',
    'com.microsoft.office.excel': 'Excel',
    'com.microsoft.office.powerpoint': 'PowerPoint',
    'com.microsoft.office.onenote': 'OneNote',
    'com.dropbox.android': 'Dropbox',
    'com.paypal.android.p2pmobile': 'PayPal',
}

# Trailing package segments that say nothing about which app this is. Dropping
# them stops com.instagram.android from being shown as just "Android".
_GENERIC_PACKAGE_SEGMENTS = {
    'app', 'apps', 'android', 'mobile', 'client', 'application', 'main',
    'helper', 'service', 'services', 'provider', 'receiver', 'activity',
    'ui', 'core', 'common', 'base', 'util', 'utils',
}


def _display_app_name(package: str) -> str:
    """Best-effort display name for a package id.

    The real label lives in the APK's resource table, which adb cannot report,
    so this falls back to the most distinctive part of the package id.
    """
    known = _KNOWN_APP_NAMES.get(package)
    if known:
        return known

    segments = [seg for seg in package.split('.') if seg]
    while len(segments) > 1 and segments[-1].lower() in _GENERIC_PACKAGE_SEGMENTS:
        segments.pop()
    if not segments:
        return package

    return segments[-1].replace('_', ' ').replace('-', ' ').strip().title()


# Reads the device state that a health dashboard shows, one entry per source.
UNAVAILABLE = 'Unavailable'

_BATTERY_STATUS = {1: 'Unknown', 2: 'Charging', 3: 'Discharging', 4: 'Not charging', 5: 'Full'}
_BATTERY_HEALTH = {1: 'Unknown', 2: 'Good', 3: 'Overheating', 4: 'Dead',
                   5: 'Over voltage', 6: 'Unspecified failure', 7: 'Cold'}
_THERMAL_STATUS = {0: 'None', 1: 'Light throttling', 2: 'Moderate throttling',
                   3: 'Severe throttling', 4: 'Critical', 5: 'Emergency',
                   6: 'Shutdown imminent'}

_WIFI_SSID = re.compile(r'SSID:\s*(.*?)(?=,\s|\s+\w+:|$)')
_WIFI_RSSI = re.compile(r'RSSI:\s*(-?\d+)')
_WIFI_STATE = re.compile(r'[Ss]upplicant state:\s*(\w+)')
_WIFI_ON = re.compile(r'wi-?fi\s+is\s+enabled', re.I)
_WIFI_OFF = re.compile(r'wi-?fi\s+is\s+disabled', re.I)

# A thermal entry holds mName and mValue in either order, and different Android
# releases disagree on which comes first. '[^{}]*?' keeps the two inside the same
# entry so a sensor cannot pick up its neighbour's reading.
_THERMAL_ENTRY = re.compile(
    r'mName=([^\s,}]+)[^{}]*?mValue=(-?\d+(?:\.\d+)?)'
    r'|mValue=(-?\d+(?:\.\d+)?)[^{}]*?mName=([^\s,}]+)')


def _parse_battery_dump(output: str) -> Dict[str, Any]:
    """Pull level, charging state, health and temperature out of 'dumpsys battery'."""
    fields = {}
    for line in output.splitlines():
        if ':' not in line:
            continue
        key, _, value = line.partition(':')
        fields[key.strip().lower()] = value.strip()

    def as_int(key: str) -> Optional[int]:
        try:
            return int(fields.get(key, ''))
        except ValueError:
            return None

    powered = [label for key, label in (('ac powered', 'AC'), ('usb powered', 'USB'),
                                         ('wireless powered', 'Wireless'))
               if fields.get(key) == 'true']
    level = as_int('level')
    temperature = as_int('temperature')

    return {
        'level': level,
        'status': _BATTERY_STATUS.get(as_int('status'), UNAVAILABLE),
        'health': _BATTERY_HEALTH.get(as_int('health'), UNAVAILABLE),
        # dumpsys reports temperature in tenths of a degree Celsius
        'temperature': round(temperature / 10, 1) if temperature is not None else None,
        'voltage': as_int('voltage'),
        'technology': fields.get('technology') or UNAVAILABLE,
        'powered_by': ', '.join(powered) if powered else 'None',
    }


def _df_field_to_bytes(text: str) -> int:
    """Convert one 'df' size column to bytes, for both the 1K-block and -h forms."""
    text = text.strip()
    if not text:
        return 0
    units = {'K': 1024, 'M': 1024 ** 2, 'G': 1024 ** 3, 'T': 1024 ** 4}
    suffix = text[-1].upper()
    if suffix.isdigit():
        return int(text) * 1024
    multiplier = units.get(suffix)
    if multiplier is None:
        return 0
    try:
        return int(float(text[:-1]) * multiplier)
    except ValueError:
        return 0


def _parse_df(output: str) -> Dict[str, Any]:
    """Pull the primary user storage figures out of 'df' output.

    toybox wraps long filesystem names onto a second line, so fields are
    gathered across lines until a row's use% column turns up.
    """
    rows = []
    buffer: List[str] = []
    for line in output.splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0].lower().startswith('filesystem'):
            buffer = []
            continue
        buffer.extend(fields)
        if len(buffer) < 6 or not buffer[4].endswith('%'):
            continue
        try:
            percent = int(buffer[4].rstrip('%'))
        except ValueError:
            buffer = []
            continue
        rows.append({
            'mount': buffer[5],
            'total': _df_field_to_bytes(buffer[1]),
            'used': _df_field_to_bytes(buffer[2]),
            'free': _df_field_to_bytes(buffer[3]),
            'percent': percent,
        })
        buffer = []

    if not rows:
        return {}
    # /data holds installed apps and user media; / is the fallback.
    for preferred in ('/data', '/', '/storage/emulated/0'):
        for row in rows:
            if row['mount'] == preferred:
                return row
    return rows[0]


def _parse_thermal_dump(output: str) -> Dict[str, Any]:
    """Pull sensor temperatures out of 'dumpsys thermalservice'.

    The dump layout is rearranged between Android releases, so sensors are
    matched by key name wherever they appear rather than by line position.
    """
    sensors: Dict[str, float] = {}
    for match in _THERMAL_ENTRY.finditer(output):
        name = match.group(1) or match.group(4)
        value = match.group(2) or match.group(3)
        sensors[name] = float(value)
    if not sensors:
        return {}

    def pick(*needles: str) -> Optional[float]:
        for name, value in sensors.items():
            if any(needle in name.upper() for needle in needles):
                return value
        return None

    status = re.search(r'^\s*Thermal Status:\s*(\d+)', output, re.M)
    return {
        'cpu': pick('CPU', 'CPUS', 'SOC'),
        'battery': pick('BATTERY'),
        'skin': pick('SKIN'),
        'max': max(sensors.values()),
        'status': _THERMAL_STATUS.get(int(status.group(1)), UNAVAILABLE) if status else UNAVAILABLE,
    }


def _parse_uptime(output: str) -> float:
    """Seconds of uptime from /proc/uptime."""
    try:
        return float(output.split()[0])
    except (IndexError, ValueError):
        return 0.0


# 'dumpsys diskstats' reports one bracketed array per kind of figure, each with
# one entry per installed package. Package names never contain a bracket, so a
# negated character class is enough to capture an array's contents.
_DISKSTATS_ARRAYS = re.compile(
    r'^(Package Names|App Sizes|App Data Sizes|Cache Sizes):\s*\[([^][]*)\]\s*$',
    re.MULTILINE)


def _decode_array(contents: str) -> List[Any]:
    """Decode one of diskstats' bracketed arrays, or nothing if it is malformed."""
    try:
        values = json.loads(f'[{contents}]')
    except ValueError:
        return []
    return values if isinstance(values, list) else []


def _parse_diskstats(output: str) -> Dict[str, int]:
    """Map each package name to its APK size in bytes, from 'dumpsys diskstats'.

    Reading the files under /data/app is not an option: that directory belongs to
    the system user, so 'ls -l' answers "Permission denied" and every size comes
    back as zero. The disk stats service runs with the privileges needed and
    publishes one 'App Sizes' entry per package instead.

    A device with several users prints the whole group once per user, so the
    sizes of each group are added together. 'App Sizes' counts the code an app
    ships, which is what an app size means everywhere else in Android; packages
    with no APK of their own, such as theme plugins, legitimately come back zero.
    """
    sizes: Dict[str, int] = {}
    names: List[str] = []

    for label, contents in _DISKSTATS_ARRAYS.findall(output):
        if label == 'Package Names':
            names = [str(name) for name in _decode_array(contents)]
        elif label == 'App Sizes' and names:
            for index, size in enumerate(_decode_array(contents)):
                if index < len(names) and isinstance(size, int):
                    sizes[names[index]] = sizes.get(names[index], 0) + size
            names = []

    return sizes


# A bugreport opens with plain 'Key: value' lines before the dumpsys body. These
# are the ones worth quoting back to the user, mapped to the name used for them.
_BUGREPORT_HEADER_FIELDS = {
    'build': 'Build',
    'fingerprint': 'Build fingerprint',
    'bootloader': 'Bootloader',
    'radio': 'Radio',
    'network': 'Network',
    'kernel': 'Kernel',
    'uptime': 'Uptime',
    'format': 'Bugreport format version',
}

# dumpstate writes down whatever it could not gather, which is what explains a
# gap in a report, so those lines are worth surfacing rather than burying.
_DUMPSTATE_PROBLEM_MARKERS = (
    'Failed to find', 'No such file or directory', 'failed', 'Permission denied')

# The header sits within the first few kilobytes while the report itself runs to
# tens of megabytes, so only the head of it is ever read.
_BUGREPORT_HEADER_BYTES = 8192

# dumpstate's own log runs to about a hundred kilobytes on a busy device.
_DUMPSTATE_LOG_BYTES = 65536


def _human_bytes(num_bytes: float) -> str:
    """Render a byte count as a short human-readable size such as '12.4 MB'."""
    size = float(num_bytes or 0)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f"{int(size)} B" if unit == 'B' else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _format_elapsed(seconds: float) -> str:
    """Render a duration the way a stopwatch would: '45s', '2m 57s', '1h 04m'."""
    total = int(round(seconds or 0))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _parse_bugreport_header(text: str) -> Dict[str, str]:
    """Pull the opening 'Key: value' lines out of a bugreport's header."""
    fields: Dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition(':')
        if not separator:
            continue
        label = key.strip()
        for name, wanted in _BUGREPORT_HEADER_FIELDS.items():
            if label == wanted and name not in fields:
                fields[name] = value.strip().strip("'")
        if len(fields) == len(_BUGREPORT_HEADER_FIELDS):
            break
    return fields


def _parse_dumpstate_log(text: str) -> List[str]:
    """The lines where dumpstate records what it could not collect."""
    notes: List[str] = []
    for line in text.splitlines():
        note = line.strip()
        if not note or note in notes:
            continue
        if any(marker in note for marker in _DUMPSTATE_PROBLEM_MARKERS):
            notes.append(note)
        if len(notes) >= 6:
            break
    return notes


def _summarise_bugreport_archive(path: str) -> Dict[str, Any]:
    """Describe what a bugreport zip holds, without unpacking it.

    The entry list is read from the central directory and only a few kilobytes
    of two small text members are decompressed, so this stays cheap on a report
    that unpacks to tens of megabytes. Anything unreadable leaves the briefing
    short rather than failing a collection that already succeeded.
    """
    summary: Dict[str, Any] = {
        'entries': 0,
        'uncompressed': 0,
        'sections': [],
        'main_report': '',
        'header': {},
        'tombstones': 0,
        'anr_traces': 0,
        'largest': [],
        'collection_notes': [],
    }

    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [info.filename.replace('\\', '/') for info in infos]
            summary['entries'] = len(infos)
            summary['uncompressed'] = sum(info.file_size for info in infos)

            counts: Dict[str, int] = {}
            for name in names:
                section = name.split('/')[0] + ('/' if '/' in name else '')
                counts[section] = counts.get(section, 0) + 1
            summary['sections'] = sorted(counts.items(), key=lambda item: -item[1])

            for name in names:
                lowered = name.lower()
                if 'tombstone' in lowered:
                    summary['tombstones'] += 1
                if '/anr/' in lowered or lowered.endswith('traces.txt'):
                    summary['anr_traces'] += 1
                base = name.rsplit('/', 1)[-1]
                if base.startswith('bugreport-') and base.endswith('.txt'):
                    summary['main_report'] = name

            ranked = sorted(zip(names, infos), key=lambda pair: -pair[1].file_size)
            summary['largest'] = [(name, info.file_size) for name, info in ranked[:5]]

            if summary['main_report']:
                with archive.open(summary['main_report']) as handle:
                    head = handle.read(_BUGREPORT_HEADER_BYTES)
                summary['header'] = _parse_bugreport_header(
                    head.decode('utf-8', 'replace'))

            if 'dumpstate_log.txt' in names:
                with archive.open('dumpstate_log.txt') as handle:
                    log = handle.read(_DUMPSTATE_LOG_BYTES)
                summary['collection_notes'] = _parse_dumpstate_log(
                    log.decode('utf-8', 'replace'))
    except Exception:
        pass

    return summary


def _parse_forward_list(output: str) -> List[Dict[str, str]]:
    """Parse 'adb forward --list' / 'adb reverse --list' output.

    Every line is '<serial> <local> <remote>'; other lines are ignored so a
    warning adb prints alongside the list does not become a bogus entry.
    """
    entries = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        entries.append({'serial': parts[0], 'local': parts[1], 'remote': parts[2]})
    return entries


def _parse_wifi_status(output: str) -> Dict[str, Any]:
    """Pull SSID, signal and state out of 'cmd wifi status' or 'dumpsys wifi'."""
    text = output.strip()
    enabled = None
    if _WIFI_ON.search(text):
        enabled = True
    elif _WIFI_OFF.search(text):
        enabled = False

    ssid = _WIFI_SSID.search(text)
    rssi = _WIFI_RSSI.search(text)
    state = _WIFI_STATE.search(text)

    name = ssid.group(1).strip().strip('"') if ssid else ''
    if name.startswith('<'):
        name = ''

    return {
        'enabled': enabled,
        'ssid': name,
        'rssi': int(rssi.group(1)) if rssi else None,
        'state': state.group(1) if state else '',
    }





class ADBError(RuntimeError):
    """Base exception for ADB operations."""
    pass

class ADBNotFoundError(ADBError):
    """Raised when the ADB executable is not found on PATH or specified location."""
    pass

class ADBDeviceNotFoundError(ADBError):
    """Raised when a specified device is not found or disconnected."""
    pass


class ADBDeviceOfflineError(ADBError):
    """Raised when the target device is offline or unauthorized."""
    pass

class ADBCommandError(ADBError):
    """Raised when an ADB command fails execution."""
    pass

_PACKAGE_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z0-9_]+)+$')

def _validate_package(package: str) -> None:
    if not package or not _PACKAGE_RE.match(package):
        raise ValueError(f"Invalid package name: {package!r}")


class ADBManager:

    
    def __init__(self, adb_path: Path):
        self.adb_path = str(adb_path)
    
    @staticmethod
    def _sanitize_adb_error(err_text: str, device_id: Optional[str] = None) -> str:
        if not err_text:
            return ""
        # Strip ANSI escape sequences
        text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', err_text)
        # Redact device serial if present
        if device_id and device_id in text:
            text = text.replace(device_id, '[REDACTED_SERIAL]')
        text = text.strip()
        if len(text) > 500:
            text = text[:497] + '...'
        return text

    def _run_command(self, args: List[str], device_id: Optional[str] = None,
                     timeout: Optional[int] = None) -> str:
        cmd = [self.adb_path]
        
        if device_id:
            cmd.extend(['-s', device_id])
        
        cmd.extend(args)
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout
            )
            return result.stdout.strip()
        except FileNotFoundError:
            raise ADBNotFoundError(f"ADB executable not found at '{self.adb_path}'. Please verify the path in Preferences > External Tools.")
        except subprocess.TimeoutExpired:
            raise ADBCommandError(f"ADB command timed out: {' '.join(args)}")
        except subprocess.CalledProcessError as e:

            stderr = e.stderr.strip() if e.stderr else (e.stdout.strip() if e.stdout else str(e))
            clean_err = self._sanitize_adb_error(stderr, device_id)
            
            lower_err = stderr.lower()
            if 'device not found' in lower_err or 'no devices/emulators found' in lower_err:
                raise ADBDeviceNotFoundError(f"Device not found or disconnected: {clean_err}")
            elif 'device offline' in lower_err or 'device unauthorized' in lower_err:
                raise ADBDeviceOfflineError(f"Device is offline or unauthorized: {clean_err}")
            else:
                raise ADBCommandError(f"ADB command failed: {clean_err}")

    def _run_exec_out(self, args: List[str], device_id: str, timeout: int = 60) -> bytes:
        """Run a device command and return raw stdout bytes (for APK zip entries)."""
        cmd = [self.adb_path, '-s', device_id, 'exec-out'] + args
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except FileNotFoundError:
            raise ADBNotFoundError(
                f"ADB executable not found at '{self.adb_path}'. "
                "Please verify the path in Preferences > External Tools."
            )
        except subprocess.TimeoutExpired:
            raise ADBCommandError("ADB command timed out.")
        if result.returncode != 0 and not result.stdout:
            stderr = ''
            if result.stderr:
                stderr = result.stderr.decode('utf-8', errors='replace')
            raise ADBCommandError(
                f"ADB command failed: {self._sanitize_adb_error(stderr, device_id)}"
            )
        return result.stdout

    def get_devices(self) -> List[Dict[str, str]]:
        output = self._run_command(['devices', '-l'])
        devices = []
        
        for line in output.split('\n')[1:]:
            if not line.strip():
                continue
            
            parts = line.split()
            if len(parts) >= 2:
                device_id = parts[0]
                status = parts[1]
                
                info = {'id': device_id, 'status': status}
                
                for part in parts[2:]:
                    if ':' in part:
                        key, value = part.split(':', 1)
                        info[key] = value
                
                devices.append(info)
        
        return devices
    
    def get_device_model(self, device_id: str) -> str:
        try:
            return self._run_command(['shell', 'getprop', 'ro.product.model'], device_id)
        except RuntimeError:
            return "Unknown"

    def get_detailed_device_info(self, device_id: str) -> Dict[str, str]:
        """Fetch detailed non-confidential device information including CPU and RAM."""
        info = {}
        try:
            # Basic props
            info['model'] = self.get_device_model(device_id)
            info['manufacturer'] = self._run_command(['shell', 'getprop', 'ro.product.manufacturer'], device_id)
            info['android_version'] = self._run_command(['shell', 'getprop', 'ro.build.version.release'], device_id)
            info['android_codename'] = self._run_command(['shell', 'getprop', 'ro.build.version.codename'], device_id)
            info['build_id'] = self._run_command(['shell', 'getprop', 'ro.build.display.id'], device_id)
            info['kernel'] = self._run_command(['shell', 'uname', '-rs'], device_id)
            info['product_name'] = self._run_command(['shell', 'getprop', 'ro.product.name'], device_id)
            info['serial'] = device_id

            # CPU Info
            # Try ro.soc.model first (Android 12+)
            soc = self._run_command(['shell', 'getprop', 'ro.soc.model'], device_id).strip()
            if not soc:
                soc = self._run_command(['shell', 'getprop', 'ro.board.platform'], device_id).strip()
            
            # Extract from /proc/cpuinfo for more detail if needed
            cpuinfo = self._run_command(['shell', 'cat', '/proc/cpuinfo'], device_id)
            hardware = ""
            for line in cpuinfo.split('\n'):
                if line.startswith('Hardware'):
                    hardware = line.split(':', 1)[1].strip()
                    break
            
            info['cpu'] = soc if soc else (hardware if hardware else "Unknown")
            if hardware and soc and hardware.lower() != soc.lower():
                info['cpu'] = f"{soc} ({hardware})"

            # Memory Info
            meminfo = self._run_command(['shell', 'cat', '/proc/meminfo'], device_id)
            total_kb = 0
            avail_kb = 0
            for line in meminfo.split('\n'):
                if line.startswith('MemTotal:'):
                    total_kb = int(line.split()[1])
                elif line.startswith('MemAvailable:'):
                    avail_kb = int(line.split()[1])
            
            if total_kb:
                total_gb = total_kb / (1024 * 1024)
                avail_gb = avail_kb / (1024 * 1024)
                info['ram'] = f"{avail_gb:.1f} GB / {total_gb:.1f} GB free"
            else:
                info['ram'] = "Unknown"

        except Exception as e:
            info['error'] = str(e)
        return info

    def trigger_easter_egg(self, device_id: str) -> None:
        """Attempt to launch the Android Easter Egg activity."""
        # Common locations for Easter Egg
        activities = [
            "com.android.egg/.EasterEggActivity",
            "com.android.systemui/.DessertCase",
            "com.android.systemui/.BeanBag",
            "com.android.egg/com.android.egg.land.EasterEggActivity"
        ]
        
        for activity in activities:
            try:
                self._run_command(['shell', 'am', 'start', '-n', activity], device_id)
                return # Stop if one succeeds
            except:
                continue
        
        # Fallback to general intent
        try:
            self._run_command(['shell', 'am', 'start', '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.LAUNCHER', '-n', 'com.android.egg/.EasterEggActivity'], device_id)
        except:
            pass
    
    def get_running_processes(self, device_id: str) -> List[Dict[str, Any]]:
        try:
            output = self._run_command(['shell', 'top', '-n', '1', '-b'], device_id)
            return self._parse_top_output(output)
        except:
            try:
                output = self._run_command(['shell', 'ps', '-eo', 'pid,user,pcpu,vsz,args'], device_id)
                return self._parse_ps_extended(output)
            except:
                output = self._run_command(['shell', 'ps', '-A'], device_id)
                return self._parse_basic_processes(output)
    
    def _parse_top_output(self, output: str) -> List[Dict[str, Any]]:
        processes = []
        lines = output.split('\n')
        
        header_found = False
        header_line = None
        
        for i, line in enumerate(lines):
            if 'PID' in line.upper():
                header_found = True
                header_line = line
                continue
            
            if header_found and line.strip():
                parts = line.split()
                if len(parts) < 5:
                    continue
                
                try:
                    pid_idx = 0
                    user_idx = 1
                    cpu_idx = None
                    mem_idx = None
                    
                    for idx, part in enumerate(parts):
                        if '%' in part:
                            if cpu_idx is None:
                                cpu_idx = idx
                            elif mem_idx is None and idx != cpu_idx:
                                mem_idx = idx
                    
                    pid = parts[pid_idx] if parts[pid_idx].isdigit() else '0'
                    user = parts[user_idx] if len(parts) > user_idx else 'unknown'
                    cpu = parts[cpu_idx].replace('%', '') if cpu_idx and len(parts) > cpu_idx else '0'
                    
                    mem_val = '0'
                    if mem_idx and len(parts) > mem_idx:
                        mem_part = parts[mem_idx].replace('%', '')
                        try:
                            mem_pct = float(mem_part)
                            mem_val = f"{mem_pct:.1f}%"
                        except:
                            mem_val = mem_part
                    else:
                        # Improved heuristic: look for columns with memory suffixes
                        # Standard top: VIRT is column 4, RES is column 5.
                        # We prefer the second one found (RES) as it's closer to physical usage.
                        mem_candidates = []
                        for idx in range(len(parts)):
                            if any(suffix in parts[idx] for suffix in ['K', 'M', 'G']) and any(c.isdigit() for c in parts[idx]):
                                mem_candidates.append(parts[idx])
                        
                        if len(mem_candidates) >= 2:
                            mem_val = mem_candidates[1] # Use RES
                        elif mem_candidates:
                            mem_val = mem_candidates[0] # Fallback to VIRT
                    
                    # Locate ARGS column (typically starts after TIME+ which contains ':')
                    time_idx = -1
                    for idx, part in enumerate(parts):
                        if ':' in part and idx >= 5:
                            time_idx = idx
                            break
                            
                    if time_idx != -1 and len(parts) > time_idx + 1:
                        name = parts[time_idx + 1]
                    elif len(parts) > 11:
                        name = parts[11]
                    else:
                        name = parts[-1] if parts else 'unknown'
                    
                    if not pid.isdigit() or pid == '0':
                        continue
                    
                    process = {
                        'pid': pid,
                        'user': user if len(user) > 1 else 'sys',
                        'cpu': cpu,
                        'mem': self._format_memory(mem_val),
                        'name': name
                    }
                    processes.append(process)
                except:
                    continue
        
        if processes:
            return sorted(processes, key=lambda x: float(x.get('cpu', 0) or 0), reverse=True)[:50]
        
        return self._parse_basic_processes(output)
    
    def _parse_ps_extended(self, output: str) -> List[Dict[str, Any]]:
        processes = []
        lines = output.split('\n')
        
        for line in lines[1:]:
            if not line.strip():
                continue
            
            parts = line.split(None, 4)
            if len(parts) >= 5:
                cmd_parts = parts[4].split()
                name = cmd_parts[0] if cmd_parts else 'unknown'
                process = {
                    'pid': parts[0],
                    'user': parts[1],
                    'cpu': parts[2],
                    'mem': self._format_memory(parts[3]),
                    'name': name
                }
                processes.append(process)

        
        return processes[:50]
    
    def _parse_basic_processes(self, output: str) -> List[Dict[str, Any]]:
        processes = []
        lines = output.split('\n')
        
        for line in lines[1:]:
            if not line.strip():
                continue
            
            parts = line.split()
            if len(parts) >= 9:
                process = {
                    'pid': parts[1],
                    'user': parts[0],
                    'cpu': '0',
                    'mem': '0',
                    'name': parts[-1]
                }
                processes.append(process)
        
        return processes[:50]
    
    def _format_memory(self, mem_str: str) -> str:
        if not mem_str or mem_str == '0':
            return '0 KB'
        
        mem_str = mem_str.strip()
        
        if '%' in mem_str:
            return mem_str
        
        # Handle cases where it already has a suffix
        if 'G' in mem_str or 'M' in mem_str or 'K' in mem_str:
            return mem_str.replace('G', ' GB').replace('M', ' MB').replace('K', ' KB')
        
        try:
            mem_kb = int(mem_str)
            if mem_kb < 1024:
                return f"{mem_kb} KB"
            elif mem_kb < 1024 * 1024:
                return f"{mem_kb // 1024} MB"
            else:
                return f"{mem_kb / (1024 * 1024):.1f} GB"
        except ValueError:
            return mem_str

    def _format_file_size(self, size_str: str) -> str:
        try:
            size_bytes = int(size_str)
            if size_bytes < 1024:
                return f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                return f"{size_bytes / 1024:.1f} KB"
            elif size_bytes < 1024 * 1024 * 1024:
                return f"{size_bytes / (1024 * 1024):.1f} MB"
            else:
                return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
        except ValueError:
            return size_str
    
    def get_system_stats(self, device_id: str) -> Dict[str, Any]:
        stats = {}
        
        try:
            meminfo = self._run_command(['shell', 'cat', '/proc/meminfo'], device_id)
            total_kb = 0
            avail_kb = 0
            free_kb = 0
            for line in meminfo.split('\n'):
                if line.startswith('MemTotal:'):
                    total_kb = int(line.split()[1])
                elif line.startswith('MemAvailable:'):
                    avail_kb = int(line.split()[1])
                elif line.startswith('MemFree:'):
                    free_kb = int(line.split()[1])
                    
            target_avail = avail_kb if avail_kb > 0 else free_kb
            if target_avail > 0:
                stats['free_memory'] = self._format_memory(str(target_avail))
            if total_kb > 0:
                stats['total_memory'] = self._format_memory(str(total_kb))

        except:
            pass
        
        try:
            cpuinfo = self._run_command(['shell', 'cat', '/proc/cpuinfo'], device_id)
            cpu_count = cpuinfo.count('processor')
            stats['cpu_cores'] = cpu_count if cpu_count > 0 else 1
        except:
            stats['cpu_cores'] = 1
        
        return stats
    
    def kill_process(self, device_id: str, pid: str) -> None:
        AuditLogger.log(device_id, "KILL_PROCESS", f"PID: {pid}")
        self._run_command(['shell', 'kill', pid], device_id)

    
    def get_installed_apps(self, device_id: str) -> List[str]:
        output = self._run_command(['shell', 'pm', 'list', 'packages'], device_id)
        
        apps = []
        for line in output.split('\n'):
            if line.startswith('package:'):
                package = line.replace('package:', '').strip()
                apps.append(package)
        
        return sorted(apps)

    def _get_app_sizes(self, device_id: str, apps: List[Dict[str, Any]]) -> Dict[str, int]:
        """APK bytes per package, from one batched call to the disk stats service.

        Sizes are keyed by package name and cover system and user apps alike. A
        package the service does not list comes back as zero.
        """
        try:
            output = self._run_command(['shell', 'dumpsys', 'diskstats'], device_id)
        except Exception:
            return {}

        sizes = _parse_diskstats(output)
        return {app['package']: sizes.get(app['package'], 0) for app in apps}

    def get_installed_apps_details(self, device_id: str) -> List[Dict[str, Any]]:
        """Get installed apps with package, formatted name, path, type and APK size."""
        try:
            output = self._run_command(['shell', 'pm', 'list', 'packages', '-f'], device_id)
            apps = []

            for line in output.split('\n'):
                line = line.strip()
                if line.startswith('package:'):
                    line = line.replace('package:', '')
                    if '=' in line:
                        path, package = line.rsplit('=', 1)
                        is_system = path.startswith(SYSTEM_APP_PATHS)
                        apps.append({
                            'package': package,
                            'name': _display_app_name(package),
                            'path': path,
                            'is_system': is_system,
                            'type': 'System' if is_system else 'User'
                        })

            sizes = self._get_app_sizes(device_id, apps)
            for app in apps:
                app['size_bytes'] = sizes.get(app['package'], 0)

            apps.sort(key=lambda x: x['name'].lower())
            return apps
        except Exception:
            pkgs = self.get_installed_apps(device_id)
            return [{'package': p, 'name': _display_app_name(p), 'path': '',
                     'is_system': False, 'type': 'Unknown', 'size_bytes': 0} for p in pkgs]

    
    def get_app_info(self, device_id: str, package: str) -> Dict[str, str]:
        _validate_package(package)
        output = self._run_command(['shell', 'dumpsys', 'package', package], device_id)

        info = {'package': package}
        icon_ids = apk_icon.parse_icon_resource_ids_from_dumpsys(output)

        for line in output.split('\n'):
            line = line.strip()
            if 'versionName=' in line:
                info['version_name'] = line.split('=')[1]
            elif 'versionCode=' in line:
                # versionCode=123 minSdk=21 targetSdk=30
                info['version_code'] = line.split('=')[1].split()[0]
            elif 'firstInstallTime=' in line:
                info['install_time'] = line.split('=')[1]
            elif 'lastUpdateTime=' in line:
                info['update_time'] = line.split('=')[1]
            elif 'codePath=' in line:
                info['path'] = line.split('=')[1]
            elif 'installerPackageName=' in line:
                info['installer'] = line.split('=')[1]
            elif 'userId=' in line:
                info['user_id'] = line.split('=')[1]

        if icon_ids:
            info['icon_res_ids'] = icon_ids
        return info


    def install_apk(self, device_id: str, apk_path: str) -> None:
        path = Path(apk_path)
        if not path.exists():
            raise FileNotFoundError(f"APK file does not exist: {apk_path}")
        if not path.is_file():
            raise ValueError(f"Specified path is not a file: {apk_path}")
        if path.suffix.lower() != '.apk':
            raise ValueError(f"File does not have a .apk extension: {apk_path}")
        if not os.access(path, os.R_OK):
            raise PermissionError(f"APK file is not readable: {apk_path}")

        AuditLogger.log(device_id, "INSTALL_APK", str(path))
        output = self._run_command(['install', '-r', str(path)], device_id)
        if "Failure" in output or "Success" not in output:
            error_reason = output
            match = re.search(r'Failure\s*\[(.*?)\]', output)
            if match:
                code = match.group(1)
                friendly_messages = {
                    'INSTALL_FAILED_ALREADY_EXISTS': 'Application with the same package name already exists.',
                    'INSTALL_FAILED_INVALID_APK': 'The APK file is invalid or corrupted.',
                    'INSTALL_FAILED_INSUFFICIENT_STORAGE': 'Device has insufficient storage space.',
                    'INSTALL_FAILED_DUPLICATE_PACKAGE': 'Duplicate package name found on device.',
                    'INSTALL_FAILED_NO_SHARED_USER': 'Shared user does not exist.',
                    'INSTALL_FAILED_UPDATE_INCOMPATIBLE': 'Update is incompatible with currently installed version.',
                    'INSTALL_FAILED_SHARED_USER_INCOMPATIBLE': 'Shared user signature mismatch.',
                    'INSTALL_FAILED_MISSING_SHARED_LIBRARY': 'Required shared library is missing on device.',
                    'INSTALL_FAILED_REPLACE_COULDNT_DELETE': 'Failed to replace existing installation.',
                    'INSTALL_FAILED_DEXOPT': 'DEX optimization failed.',
                    'INSTALL_FAILED_OLDER_SDK': 'APK requires a newer Android version (minSdk higher than device SDK).',
                    'INSTALL_FAILED_CONFLICTING_PROVIDER': 'Conflicting content provider exists on device.',
                    'INSTALL_FAILED_NEWER_SDK': 'APK requires an older Android version.',
                    'INSTALL_FAILED_TEST_ONLY': 'APK is marked test-only.',
                    'INSTALL_FAILED_CPU_ABI_INCOMPATIBLE': 'Native CPU architecture (ABI) is incompatible with device.',
                    'INSTALL_PARSE_FAILED_INCONSISTENT_CERTIFICATES': 'Package certificates mismatch.',
                    'INSTALL_FAILED_VERSION_DOWNGRADE': 'Cannot downgrade application to an older version code.'
                }
                explanation = friendly_messages.get(code, code)
                error_reason = f"{code}: {explanation}"
            raise RuntimeError(f"Installation failed: {error_reason}")


    def get_apk_paths(self, device_id: str, package: str) -> List[Dict[str, str]]:
        """List the APK files behind an installed package using `pm path`.

        Returns one entry per file, in `pm path` order: the base APK comes
        first, then any splits. Each entry is
        {'split': '' for base.apk or the split name without its extension,
         'name': the on-device file name, 'path': the on-device path}.
        """
        _validate_package(package)
        output = self._run_command(['shell', 'pm', 'path', package], device_id)

        entries: List[Dict[str, str]] = []
        for line in output.splitlines():
            line = line.strip()
            if not line.startswith('package:'):
                continue
            remote_path = line.split(':', 1)[1].strip()
            if not remote_path:
                continue
            name = posixpath.basename(remote_path)
            stem = name[:-4] if name.lower().endswith('.apk') else name
            entries.append({
                'split': '' if stem == 'base' else stem,
                'name': name,
                'path': remote_path,
            })

        if not entries:
            raise ADBCommandError(
                f"'pm path {package}' reported no APK files. "
                "The app may be disabled, or not installed for the current user."
            )
        return entries


    def extract_apk(self, device_id: str, package: str, destination: str,
                    version: str = '') -> Dict[str, Any]:
        """Pull every APK behind an installed package into a local folder.

        A package with only a base APK is written as <package>_<version>.apk.
        A split package is bundled into <package>_<version>.apks, a zip holding
        base.apk plus each split_<name>.apk, which is what split-installers
        such as SAI expect. Returns {'path', 'members', 'is_split'}.
        """
        _validate_package(package)
        AuditLogger.log(device_id, "EXTRACT_APK", f"{package} -> {destination}")

        if not version:
            try:
                version = self.get_app_info(device_id, package).get('version_name', '') or ''
            except Exception:
                version = ''
        version = version.strip()
        # Version names such as "1.2.3 beta" are legal in a filename, but the
        # space makes the result awkward to type, so collapse whitespace runs.
        version = re.sub(r'\s+', '_', version)
        stem = f"{package}_{self._safe_ntfs_component(version)}" if version else package

        entries = self.get_apk_paths(device_id, package)
        target = Path(destination)
        target.mkdir(parents=True, exist_ok=True)

        if len(entries) == 1 and not entries[0]['split']:
            local_path = target / f"{stem}.apk"
            self.download_file(device_id, entries[0]['path'], str(local_path))
            return {'path': str(local_path), 'members': [entries[0]['name']], 'is_split': False}

        archive = target / f"{stem}.apks"
        members: List[str] = []
        # Pull into a scratch folder so the chosen destination only ever gains
        # the finished file, never the loose base.apk / split_*.apk.
        with tempfile.TemporaryDirectory(prefix='droidmgr-apk-') as scratch_dir:
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_STORED) as bundle:
                for entry in entries:
                    scratch = Path(scratch_dir) / entry['name']
                    self.download_file(device_id, entry['path'], str(scratch))
                    bundle.write(scratch, arcname=entry['name'])
                    members.append(entry['name'])
        return {'path': str(archive), 'members': members, 'is_split': True}



    def uninstall_app(self, device_id: str, package: str) -> None:
        """Uninstall an application from the device."""
        _validate_package(package)
        AuditLogger.log(device_id, "UNINSTALL_APP", package)
        self._run_command(['uninstall', package], device_id)

    
    def start_app(self, device_id: str, package: str) -> None:
        _validate_package(package)
        AuditLogger.log(device_id, "START_APP", package)
        self._run_command(
            ['shell', 'monkey', '-p', package, '-c', 'android.intent.category.LAUNCHER', '1'],
            device_id
        )
    
    def stop_app(self, device_id: str, package: str) -> None:
        _validate_package(package)
        AuditLogger.log(device_id, "STOP_APP", package)
        self._run_command(['shell', 'am', 'force-stop', package], device_id)

    def clear_app_data(self, device_id: str, package: str) -> None:
        """Delete an application's stored data, which takes its cache with it.

        Android offers no way to clear one app's cache on its own: the cache
        directory belongs to the app's uid, and the only shell-reachable route
        to it is 'pm clear', which empties the whole data directory. Some ROMs
        withhold CLEAR_APP_USER_DATA from the shell user, and this raises.
        """
        _validate_package(package)
        AuditLogger.log(device_id, "CLEAR_APP_DATA", package)
        self._run_command(['shell', 'pm', 'clear', package], device_id)

    
    def list_files(self, device_id: str, path: str = '/sdcard/', show_hidden: bool = True, use_exact_sizes: bool = False) -> List[Dict[str, Any]]:
        if not path.strip():
            path = "/"
        if not path.endswith('/'):
            path += '/'
            
        try:
            output = self._run_command(['shell', 'ls', '-la', f'"{path}"'], device_id)
        except RuntimeError as e:
            # Handle empty directories or access errors gracefully
            if "No such file or directory" in str(e):
                return []
            raise e
        
        lines = output.split('\n')
        files = []
        
        # Step 1: Detect metadata column count from '.' or '..' entries
        # This is the most robust way as metadata columns are fixed in a single 'ls' output
        metadata_cols = -1
        for line in lines:
            line = line.strip()
            if not line or line.startswith('total'):
                continue
            parts = line.split()
            # '.' and '..' are always single-part names at the end of the metadata
            if len(parts) >= 4 and parts[-1] in ('.', '..'):
                metadata_cols = len(parts) - 1
                break
                
        # Fallback if no '.' or '..' found (unlikely with -la)
        if metadata_cols == -1:
            metadata_cols = 7 # Standard toybox/toolbox default
            
        for line in lines:
            line = line.strip()
            if not line or line.startswith('total'):
                continue
            
            # Handle symlinks: split line to isolate name from target path
            if ' -> ' in line:
                line_parts = line.split(' -> ', 1)
                line = line_parts[0]
                
            parts = line.split()
            if not parts:
                continue
                
            # Skip inaccessible entries where permissions could not be read (e.g. l????????? or d?????????)
            if '?' in parts[0]:
                continue
                
            if len(parts) <= metadata_cols:
                continue
                
            permissions = parts[0]
            is_dir = permissions.startswith('d')
            is_symlink = permissions.startswith('l')
            if is_symlink:
                is_dir = True # Treat symlinks as something you can double click
                
            # Name is everything after the metadata columns
            name = ' '.join(parts[metadata_cols:])

            
            # Skip navigation entries in the final list
            if name in ('.', '..'):
                continue
            
            # Filter hidden files if requested
            if not show_hidden and name.startswith('.') and name != '..':
                continue
            
            # Metadata columns parsing
            user = parts[2] if len(parts) > 2 else "unknown"
            group = parts[3] if len(parts) > 3 else "unknown"
            
            # Date and Time are the last columns before name
            date_str = parts[metadata_cols-2] if metadata_cols >= 2 else ""
            time_str = parts[metadata_cols-1] if metadata_cols >= 1 else ""
            date_time = f"{date_str} {time_str}".strip()
            
            # Size candidate search
            size = '0'
            size_candidates = parts[max(0, metadata_cols-5):metadata_cols-1]
            for cand in reversed(size_candidates):
                if cand.isdigit():
                    size = cand
                    break
            
            display_size = f"{size} B" if use_exact_sizes else self._format_file_size(size)
                    
            file_info = {
                'permissions': permissions,
                'user': user,
                'group': group,
                'date_time': date_time,
                'size_raw': size,
                'size': display_size,
                'name': name,
                'is_dir': is_dir,
                'full_path': path + name
            }
            files.append(file_info)
            
        return sorted(files, key=lambda x: (not x.get('is_dir', False), (x.get('name') or '').lower()))
    
    def download_file(self, device_id: str, remote_path: str, local_path: str) -> None:
        self._run_command(['pull', remote_path, local_path], device_id)

    @staticmethod
    def _safe_ntfs_component(component: str) -> str:
        """Escape Windows-invalid names without making distinct Android names collide."""
        original = component or '_'
        encoded = []
        invalid = '<>:"/\\|?*%'
        for index, char in enumerate(original):
            is_trailing_dot_or_space = index == len(original) - 1 and char in '. '
            if char in invalid or ord(char) < 32 or is_trailing_dot_or_space:
                encoded.extend(f'%{byte:02X}' for byte in char.encode('utf-8'))
            else:
                encoded.append(char)
        safe = ''.join(encoded)
        if re.match(r'^(CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?$', safe, re.IGNORECASE):
            first = safe[0].encode('utf-8')
            safe = ''.join(f'%{byte:02X}' for byte in first) + safe[1:]

        max_units = 240
        if len(safe.encode('utf-16-le')) // 2 > max_units:
            suffix = '~' + hashlib.sha256(original.encode('utf-8', errors='replace')).hexdigest()[:10]
            shortened = []
            units = 0
            for char in safe:
                char_units = len(char.encode('utf-16-le')) // 2
                if units + char_units + len(suffix) > max_units:
                    break
                shortened.append(char)
                units += char_units
            safe = ''.join(shortened) + suffix
        return safe or '_'

    def backup_filesystem(self, device_id: str, destination: str, cancel_event, progress_callback=None,
                          remote_root: str = '/', parallelism: int = 4, exclusions=None, only_paths=None,
                          verify_checksums=False) -> bool:
        """Index one device storage area, then download its files with a small worker pool."""
        roots = ['/system', '/vendor', '/product', '/system_ext', '/odm', '/apex'] if remote_root == 'system' else [remote_root]
        os.makedirs(destination, exist_ok=True)
        exclusions = [path.rstrip('/') for path in (exclusions or []) if isinstance(path, str) and path.startswith('/')]
        if only_paths is not None:
            paths = list(only_paths)
        else:
            command = [self.adb_path, '-s', device_id, 'shell', 'find', *roots, '-type', 'f']
            paths = []
            scanned = 0
            output_lines = queue.Queue()
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                       encoding='utf-8', errors='replace')
            if hasattr(cancel_event, 'register'):
                cancel_event.register(process)

            def read_index():
                try:
                    for output_line in process.stdout:
                        output_lines.put(output_line)
                finally:
                    output_lines.put(None)

            reader = threading.Thread(target=read_index, daemon=True)
            reader.start()
            try:
                while True:
                    if cancel_event.is_set():
                        if process.poll() is None:
                            process.kill()
                        process.wait()
                        return False
                    try:
                        line = output_lines.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if line is None:
                        break
                    path = line.rstrip('\r\n')
                    excluded = False
                    if path.startswith('/'):
                        scanned += 1
                        excluded = any(path == rule or path.startswith(rule + '/') for rule in exclusions)
                        if not excluded:
                            paths.append(path)
                    if progress_callback and path.startswith('/'):
                        progress_callback('index_skipped' if excluded else 'index', scanned, 0, path, ())
                process.wait()
                if process.returncode and not paths and not cancel_event.is_set():
                    raise ADBCommandError("Could not index device filesystem. Check the device connection and ADB permissions.")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if hasattr(cancel_event, 'unregister'):
                    cancel_event.unregister(process)

            if cancel_event.is_set():
                return False

            cache_path = os.path.join(destination, '.droidmgr_index.json')
            temp_cache_path = cache_path + '.tmp'
            with open(temp_cache_path, 'w', encoding='utf-8') as cache_file:
                json.dump({'device_id': device_id, 'remote_root': remote_root,
                           'exclusions': exclusions, 'files': paths}, cache_file)
            os.replace(temp_cache_path, cache_path)

        if progress_callback:
            progress_callback('indexed', 0, len(paths), '', paths)
        if cancel_event.is_set():
            return False
        total = len(paths)
        if not total:
            if only_paths is None:
                manifest_path = os.path.join(destination, '.droidmgr_backup_manifest.json')
                with open(manifest_path, 'w', encoding='utf-8') as manifest_file:
                    json.dump({'files': []}, manifest_file)
                if progress_callback:
                    progress_callback('verification', 0, 0, '', {
                        'bytes': 0, 'invalid': [], 'failed': [],
                        'checksums': bool(verify_checksums), 'indexed': 0,
                    })
            return True

        pending = list(paths)
        active = set()
        completed = 0
        failures = []
        manifest_lock = threading.Lock()
        manifest = {}
        manifest_path = os.path.join(destination, '.droidmgr_backup_manifest.json')
        if only_paths is not None and os.path.isfile(manifest_path):
            try:
                with open(manifest_path, 'r', encoding='utf-8') as manifest_file:
                    manifest = {row['remote_path']: row for row in json.load(manifest_file).get('files', [])}
            except (OSError, ValueError, KeyError, TypeError):
                manifest = {}
        downloaded_bytes = 0
        byte_rate = 0.0
        byte_rate_sample_time = time.monotonic()
        byte_rate_sample_bytes = 0
        state_lock = threading.Lock()
        target_lock = threading.Lock()
        local_targets = set()

        def local_path_for(remote_path):
            if only_paths is not None and remote_path in manifest:
                return os.path.join(destination, manifest[remote_path]['local_path'])
            components = [self._safe_ntfs_component(part) for part in remote_path.split('/') if part]
            if not components:
                components = ['_']
            target = os.path.join(destination, *components)
            if len(os.path.abspath(target)) > 240:
                digest = hashlib.sha256(remote_path.encode('utf-8', errors='replace')).hexdigest()[:24]
                target = os.path.join(destination, '_long_paths', f'{digest}_{components[-1][:80]}')
            with target_lock:
                key = os.path.normcase(target).casefold()
                if key in local_targets:
                    leaf = components[-1]
                    suffix = '~' + hashlib.sha256(remote_path.encode('utf-8', errors='replace')).hexdigest()[:10]
                    components[-1] = self._safe_ntfs_component(leaf[:100] + suffix)
                    target = os.path.join(destination, *components)
                    if len(os.path.abspath(target)) > 240:
                        digest = hashlib.sha256(remote_path.encode('utf-8', errors='replace')).hexdigest()[:24]
                        target = os.path.join(destination, '_long_paths', f'{digest}_{components[-1][:80]}')
                    key = os.path.normcase(target).casefold()
                    counter = 1
                    while key in local_targets:
                        components[-1] = self._safe_ntfs_component(leaf[:90] + suffix + f'~{counter}')
                        target = os.path.join(destination, *components)
                        key = os.path.normcase(target).casefold()
                        counter += 1
                local_targets.add(key)
            return target

        def pull_one(remote_path):
            nonlocal completed, downloaded_bytes, byte_rate, byte_rate_sample_time, byte_rate_sample_bytes
            if cancel_event.is_set():
                return False
            with state_lock:
                pending.remove(remote_path)
                active.add(remote_path)
                if progress_callback:
                    progress_callback('download_current', completed, total, '\n'.join(active), list(pending))

            local_path = local_path_for(remote_path)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            pull = subprocess.Popen([self.adb_path, '-s', device_id, 'pull', remote_path, local_path],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    encoding='utf-8', errors='replace')
            if hasattr(cancel_event, 'register'):
                cancel_event.register(pull)
            try:
                last_size = 0
                while pull.poll() is None:
                    if cancel_event.is_set():
                        pull.kill()
                        pull.wait()
                        pull.communicate()
                        return False
                    try:
                        current_size = os.path.getsize(local_path)
                    except OSError:
                        current_size = 0
                    now = time.monotonic()
                    with state_lock:
                        if current_size > last_size:
                            downloaded_bytes += current_size - last_size
                            last_size = current_size
                        elapsed = now - byte_rate_sample_time
                        if elapsed >= 0.5:
                            byte_rate = (downloaded_bytes - byte_rate_sample_bytes) / elapsed
                            byte_rate_sample_time = now
                            byte_rate_sample_bytes = downloaded_bytes
                            if progress_callback:
                                progress_callback(
                                    'download_rate', completed, total, remote_path,
                                    (downloaded_bytes, byte_rate, list(pending), list(active))
                                )
                    time.sleep(0.1)
                stdout, stderr = pull.communicate()
                if cancel_event.is_set():
                    return False
                if pull.returncode:
                    raise ADBCommandError(f"Could not download {remote_path}: {stderr.strip() or stdout.strip()}")
                size = os.path.getsize(local_path)
                digest = None
                if verify_checksums:
                    hasher = hashlib.sha256()
                    with open(local_path, 'rb') as downloaded_file:
                        for chunk in iter(lambda: downloaded_file.read(1024 * 1024), b''):
                            hasher.update(chunk)
                    digest = hasher.hexdigest()
                with state_lock:
                    try:
                        current_size = os.path.getsize(local_path)
                    except OSError:
                        current_size = last_size
                    if current_size > last_size:
                        downloaded_bytes += current_size - last_size
                    completed += 1
                    active.discard(remote_path)
                    with manifest_lock:
                        manifest[remote_path] = {
                            'remote_path': remote_path,
                            'local_path': os.path.relpath(local_path, destination),
                            'size': size,
                            'sha256': digest,
                        }
                    if progress_callback:
                        progress_callback('download', completed, total, remote_path,
                                          (list(pending), list(active), downloaded_bytes))
                return True
            except Exception as exc:
                if cancel_event.is_set():
                    return False
                with state_lock:
                    completed += 1
                    active.discard(remote_path)
                    failures.append((remote_path, str(exc)))
                    if progress_callback:
                        progress_callback('download_failed', completed, total, remote_path,
                                          (str(exc), list(pending), list(active)))
                return False
            finally:
                if pull.poll() is None:
                    pull.kill()
                    pull.wait()
                if hasattr(cancel_event, 'unregister'):
                    cancel_event.unregister(pull)

        worker_count = max(1, min(int(parallelism), 16, total))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            path_iterator = iter(paths)
            futures = set()
            for _ in range(worker_count):
                futures.add(executor.submit(pull_one, next(path_iterator)))

            while futures:
                if cancel_event.is_set():
                    return False
                finished, futures = wait(futures, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in finished:
                    try:
                        future.result()
                    except Exception:
                        cancel_event.set()
                        raise
                    if cancel_event.is_set():
                        return False
                    try:
                        next_path = next(path_iterator)
                    except StopIteration:
                        continue
                    futures.add(executor.submit(pull_one, next_path))
        if not cancel_event.is_set():
            temp_manifest = manifest_path + '.tmp'
            with open(temp_manifest, 'w', encoding='utf-8') as manifest_file:
                json.dump({'files': list(manifest.values())}, manifest_file, indent=2)
            os.replace(temp_manifest, manifest_path)
            if progress_callback:
                progress_callback('verification_start', 0, len(manifest), '', ())
            verified = 0
            invalid = []
            verified_bytes = 0
            for record in manifest.values():
                local_path = os.path.join(destination, record['local_path'])
                try:
                    if os.path.getsize(local_path) != record['size']:
                        raise OSError('file size changed')
                    if record.get('sha256'):
                        hasher = hashlib.sha256()
                        with open(local_path, 'rb') as downloaded_file:
                            for chunk in iter(lambda: downloaded_file.read(1024 * 1024), b''):
                                hasher.update(chunk)
                        if hasher.hexdigest() != record['sha256']:
                            raise OSError('SHA-256 mismatch')
                    verified += 1
                    verified_bytes += record['size']
                except OSError as exc:
                    invalid.append((record['remote_path'], str(exc)))
            if progress_callback:
                progress_callback('verification', verified, len(manifest), '',
                                  {'bytes': verified_bytes, 'invalid': invalid,
                                   'failed': failures, 'checksums': bool(verify_checksums),
                                   'indexed': total})
        if progress_callback:
            progress_callback('download_summary', len(failures), total, '', failures)
        return not cancel_event.is_set()

    def estimate_filesystem_size(self, device_id: str, remote_root: str = '/', cancel_event=None) -> Optional[int]:
        """Return a conservative device-side `du` estimate in bytes, or None if unavailable."""
        roots = ['/system', '/vendor', '/product', '/system_ext', '/odm', '/apex'] if remote_root == 'system' else [remote_root]
        try:
            process = subprocess.Popen(
                [self.adb_path, '-s', device_id, 'shell', 'du', '-sk', *roots],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding='utf-8', errors='replace',
            )
            if cancel_event is not None and hasattr(cancel_event, 'register'):
                cancel_event.register(process)
            started = time.monotonic()
            try:
                while process.poll() is None:
                    if ((cancel_event is not None and cancel_event.is_set())
                            or time.monotonic() - started > 45):
                        process.kill()
                        process.wait()
                        process.communicate()
                        return None
                    time.sleep(0.05)
                stdout, _stderr = process.communicate()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if cancel_event is not None and hasattr(cancel_event, 'unregister'):
                    cancel_event.unregister(process)
            if cancel_event is not None and cancel_event.is_set():
                return None
            sizes = []
            for line in stdout.splitlines():
                parts = line.strip().split(None, 1)
                if parts and parts[0].isdigit():
                    sizes.append(int(parts[0]) * 1024)
            return sum(sizes) if sizes else None
        except (OSError, subprocess.SubprocessError):
            return None
    
    def upload_file(self, device_id: str, local_path: str, remote_path: str, cancel_event=None) -> None:
        def run(args, failure_message):
            process = subprocess.Popen([self.adb_path, '-s', device_id, *args],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       encoding='utf-8', errors='replace')
            if cancel_event is not None and hasattr(cancel_event, 'register'):
                cancel_event.register(process)
            try:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        if process.poll() is None:
                            process.kill()
                            process.wait()
                        process.communicate()
                        return False
                    try:
                        stdout, stderr = process.communicate(timeout=0.1)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if cancel_event is not None and cancel_event.is_set():
                    return False
                if process.returncode:
                    raise ADBCommandError(f"{failure_message}: {stderr.strip() or stdout.strip()}")
                return True
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if cancel_event is not None and hasattr(cancel_event, 'unregister'):
                    cancel_event.unregister(process)

        parent = posixpath.dirname(remote_path)
        if parent and not run(['shell', f'mkdir -p {shlex.quote(parent)}'],
                              f"Could not prepare restore path {parent}"):
            return
        run(['push', local_path, remote_path], f"Could not restore {remote_path}")
    
    PROTECTED_PATHS = {
        '/', '/system', '/system/app', '/system/priv-app', '/system/bin', '/system/etc',
        '/data', '/proc', '/dev', '/sbin', '/vendor', '/product', '/system_ext',
        '/odm', '/apex', '/sys', '/etc', '/bin', '/mnt', '/root'
    }

    def delete_file(self, device_id: str, remote_path: str) -> None:
        clean_path = remote_path.strip()
        if not clean_path or clean_path == '/':
            raise PermissionError("Deletion of root directory '/' is strictly prohibited.")
            
        norm_path = clean_path.rstrip('/')
        if not norm_path:
            norm_path = '/'

        if norm_path in self.PROTECTED_PATHS:
            raise PermissionError(f"Deletion of protected system path '{remote_path}' is strictly prohibited.")

        for protected in self.PROTECTED_PATHS:
            if protected != '/' and (protected == norm_path or protected.startswith(norm_path + '/')):
                raise PermissionError(f"Deletion of '{remote_path}' is prohibited because it is a parent of protected system path '{protected}'.")

        AuditLogger.log(device_id, "DELETE_FILE", remote_path)
        self._run_command(['shell', 'rm', '-rf', f'"{remote_path}"'], device_id)


    def rename_file(self, device_id: str, old_path: str, new_path: str) -> None:
        AuditLogger.log(device_id, "RENAME_FILE", f"From '{old_path}' to '{new_path}'")
        self._run_command(['shell', 'mv', f'"{old_path}"', f'"{new_path}"'], device_id)

    def move_file(self, device_id: str, src_path: str, dest_path: str) -> None:
        AuditLogger.log(device_id, "MOVE_FILE", f"From '{src_path}' to '{dest_path}'")
        self._run_command(['shell', 'mv', f'"{src_path}"', f'"{dest_path}"'], device_id)

    def copy_file(self, device_id: str, src_path: str, dest_path: str) -> None:
        AuditLogger.log(device_id, "COPY_FILE", f"From '{src_path}' to '{dest_path}'")
        self._run_command(['shell', 'cp', '-r', f'"{src_path}"', f'"{dest_path}"'], device_id)

    def make_directory(self, device_id: str, path: str) -> None:
        """Create a directory on the device."""
        AuditLogger.log(device_id, "MAKE_DIR", path)
        self._run_command(['shell', 'mkdir', '-p', f'"{path}"'], device_id)



    def get_storage_info(self, device_id: str) -> Dict[str, str]:
        """Fetch storage space and partition information."""
        info = {}
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

    def get_battery_info(self, device_id: str) -> str:
        """Fetch battery level and charging status."""
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

    def get_display_info(self, device_id: str) -> str:
        """Fetch screen resolution and density."""
        try:
            size_out = self._run_command(['shell', 'wm', 'size'], device_id).strip()
            density_out = self._run_command(['shell', 'wm', 'density'], device_id).strip()
            size = size_out.replace('Physical size:', '').strip()
            density = density_out.replace('Physical density:', '').strip()
            return f"Resolution: {size}, Density: {density}"
        except Exception:
            return "Unknown"

    def generate_llm_report(self, device_id: str, progress_callback=None) -> str:
        """Generate a single information-dense report paragraph for LLM analysis."""
        def update_p(pct, msg):
            if progress_callback:
                progress_callback(pct, msg)

        update_p(10, "Gathering device specs and system properties...")
        info = self.get_detailed_device_info(device_id)

        update_p(30, "Checking storage space and system health...")
        storage_info = self.get_storage_info(device_id)
        battery_info = self.get_battery_info(device_id)
        display_info = self.get_display_info(device_id)

        update_p(55, "Fetching active process list...")
        try:
            processes = self.get_running_processes(device_id)
        except Exception:
            processes = []

        update_p(75, "Retrieving installed applications...")
        try:
            apps = self.get_installed_apps(device_id)
        except Exception:
            apps = []

        update_p(90, "Formulating single information-dense paragraph report...")
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        def clean(val):
            return str(val).replace('\n', ' ').replace('\r', '').strip()

        proc_str_list = [
            f"{p['name']} (PID: {p['pid']}, User: {p['user']}, CPU: {p['cpu']}%, Mem: {p['mem']})"
            for p in processes
        ]
        proc_formatted = ", ".join(proc_str_list) if proc_str_list else "None detected"

        apps_formatted = ", ".join(apps) if apps else "None detected"

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
            f"Display: {clean(display_info)} | "
            f"Battery: {clean(battery_info)} | "
            f"Storage & Partition Free Space: {clean(storage_info.get('summary', 'Unknown'))} | "
            f"Active Running Processes ({len(processes)} total): [{proc_formatted}] | "
            f"Installed Applications ({len(apps)} total packages): [{apps_formatted}]."
        )

        update_p(100, "Report generation complete.")
        return report_paragraph

    # A bugreport bundles a full dumpstate collection on the device and then
    # pulls it back, which takes minutes rather than seconds on a typical phone
    # and reports nothing along the way. Half an hour is far past any normal
    # run, so anything past it is a device that has stopped answering.
    BUGREPORT_TIMEOUT = 1800

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

    def is_directory_writable(self, device_id: str, path: str) -> bool:
        """Check dynamically if a directory on the device is writable."""
        try:
            res = self._run_command(['shell', f'[ -w "{path}" ] && echo 1 || echo 0'], device_id)
            return res.strip() == '1'
        except Exception:
            return False

    @staticmethod
    def cleanup_icon_cache(output_dir: str, max_age_days: int = 7) -> None:
        """Purge icon files in output_dir older than max_age_days."""
        import time
        try:
            if not os.path.exists(output_dir):
                return
            cutoff = time.time() - (max_age_days * 86400)
            for entry in os.listdir(output_dir):
                filepath = os.path.join(output_dir, entry)
                if os.path.isfile(filepath):
                    try:
                        if os.path.getmtime(filepath) < cutoff:
                            os.remove(filepath)
                    except Exception:
                        pass
        except Exception:
            pass

    def extract_app_icon(
        self,
        device_id: str,
        package: str,
        output_dir: str,
        cache_token: Optional[str] = None,
        icon_res_ids: Optional[List[int]] = None,
    ) -> Optional[str]:
        """Extract the launcher icon declared in the installed APKs.

        Resolves android:icon / android:roundIcon from the binary manifest and
        resources.arsc (the same IDs PackageManager uses), including split APKs
        and adaptive-icon XML.         Returns a local PNG path, or None.
        """
        archive = None
        try:
            _validate_package(package)
            self.cleanup_icon_cache(output_dir, max_age_days=7)
            os.makedirs(output_dir, exist_ok=True)
            device_key = hashlib.sha256(device_id.encode('utf-8')).hexdigest()[:10]
            token = cache_token or ''
            token_key = hashlib.sha256(token.encode('utf-8')).hexdigest()[:10] if token else 'latest'
            local_icon_path = os.path.join(output_dir, f"{package}_{device_key}_{token_key}_icon.png")
            if os.path.isfile(local_icon_path) and os.path.getsize(local_icon_path) > 0:
                return local_icon_path

            path_output = self._run_command(['shell', 'pm', 'path', package], device_id)
            apk_paths = []
            for line in path_output.splitlines():
                line = line.strip()
                if line.startswith('package:'):
                    p = line.replace('package:', '').strip()
                    if p.endswith('.apk'):
                        apk_paths.append(p)
            if not apk_paths:
                return None
            apk_paths.sort(key=lambda path: (0 if posixpath.basename(path) == 'base.apk' else 1, path))

            archive = _DeviceApkArchive(self, device_id, apk_paths)
            table = apk_icon.ResourceTable()
            for apk_path in apk_paths:
                arsc = archive.read(apk_path, 'resources.arsc')
                if arsc:
                    table.merge(apk_icon.parse_resource_table(arsc))

            res_ids: List[int] = []
            manifest = archive.read_name('AndroidManifest.xml')
            if manifest:
                icons = apk_icon.parse_manifest_icons(manifest)
                res_ids.extend(icons.candidate_ids())
            if icon_res_ids:
                for res_id in icon_res_ids:
                    if res_id not in res_ids:
                        res_ids.append(res_id)

            if self._render_icon_from_resources(archive, table, res_ids, local_icon_path):
                return local_icon_path
            if self._render_icon_from_filename_fallback(archive, local_icon_path):
                return local_icon_path
        except Exception:
            pass
        finally:
            if archive is not None:
                archive.close()
        return None

    def _render_icon_from_resources(
        self,
        archive: '_DeviceApkArchive',
        table: apk_icon.ResourceTable,
        res_ids: List[int],
        destination: str,
    ) -> bool:
        all_entries = archive.all_entries()
        for res_id in res_ids:
            rasters, xmls, color, name = apk_icon.pick_paths_for_icon(table, res_id)
            if name:
                guessed = apk_icon.guess_paths_from_name(all_entries, name[0], name[1])
                rasters = apk_icon.sort_raster_paths(
                    rasters + [path for path in guessed if apk_icon._is_raster_path(path)]
                )
                xmls = list(dict.fromkeys(
                    xmls + [path for path in guessed if apk_icon._is_xml_path(path)]
                ))
            for path in rasters:
                data = archive.read_name(path)
                if data and apk_icon.decode_to_png(data, destination):
                    return True
            for xml_path in xmls:
                xml_data = archive.read_name(xml_path)
                if not xml_data:
                    continue
                drawable = apk_icon.parse_xml_drawable(xml_data)
                if drawable and self._render_xml_drawable(archive, table, drawable, destination, color):
                    return True
            if color and apk_icon.composite_adaptive_icon(None, None, color, destination):
                return True
        return False

    def _render_xml_drawable(
        self,
        archive: '_DeviceApkArchive',
        table: apk_icon.ResourceTable,
        drawable: apk_icon.XmlDrawable,
        destination: str,
        fallback_color: Optional[tuple] = None,
    ) -> bool:
        if drawable.kind == 'adaptive':
            fg_bytes, fg_color = self._resolve_drawable_layer(archive, table, drawable.foreground)
            bg_bytes, bg_color = self._resolve_drawable_layer(archive, table, drawable.background)
            background_color = bg_color or fallback_color
            if not fg_bytes and not bg_bytes and not background_color:
                return False
            return apk_icon.composite_adaptive_icon(
                fg_bytes, bg_bytes, background_color, destination, inset=drawable.inset,
            )
        layer_bytes, layer_color = self._resolve_drawable_layer(archive, table, drawable)
        if layer_bytes:
            return apk_icon.decode_to_png(layer_bytes, destination)
        if layer_color:
            return apk_icon.composite_adaptive_icon(None, None, layer_color, destination)
        return False

    def _resolve_drawable_layer(
        self,
        archive: '_DeviceApkArchive',
        table: apk_icon.ResourceTable,
        layer: Optional[apk_icon.XmlDrawable],
    ) -> Tuple[Optional[bytes], Optional[tuple]]:
        if layer is None:
            return None, None
        if layer.color:
            return None, layer.color
        if not layer.reference:
            return None, None
        rasters, xmls, color, name = apk_icon.pick_paths_for_icon(table, layer.reference)
        if name:
            guessed = apk_icon.guess_paths_from_name(archive.all_entries(), name[0], name[1])
            rasters = apk_icon.sort_raster_paths(
                rasters + [path for path in guessed if apk_icon._is_raster_path(path)]
            )
        for path in rasters:
            data = archive.read_name(path)
            if data:
                return data, color
        return None, color

    def _render_icon_from_filename_fallback(self, archive: '_DeviceApkArchive', destination: str) -> bool:
        preferred = (
            'ic_launcher', 'ic_launcher_round', 'launcher_icon', 'app_icon', 'icon', 'appicon',
        )
        layer_names = ('ic_launcher_foreground', 'ic_launcher_background')
        rasters: List[Tuple[int, str]] = []
        layers: Dict[str, List[str]] = {name: [] for name in layer_names}
        for entry in archive.all_entries():
            lowered = entry.lower()
            if not lowered.startswith('res/'):
                continue
            if not apk_icon._is_raster_path(lowered):
                continue
            folder = posixpath.basename(posixpath.dirname(lowered))
            if not (folder.startswith('mipmap') or folder.startswith('drawable')):
                continue
            stem = posixpath.splitext(posixpath.basename(lowered))[0]
            if any(part in stem for part in ('notification', 'monochrome', 'shortcut', 'tvbanner')):
                continue
            if stem in layer_names:
                layers[stem].append(entry)
                continue
            if stem not in preferred:
                continue
            score = 80 if folder.startswith('mipmap') else 40
            score += preferred.index(stem) * -5
            score += apk_icon._density_from_path(lowered)
            rasters.append((score, entry))
        rasters.sort(key=lambda row: row[0], reverse=True)
        for _, path in rasters:
            data = archive.read_name(path)
            if data and apk_icon.decode_to_png(data, destination):
                return True
        fg_paths = apk_icon.sort_raster_paths(layers['ic_launcher_foreground'])
        bg_paths = apk_icon.sort_raster_paths(layers['ic_launcher_background'])
        fg = archive.read_name(fg_paths[0]) if fg_paths else None
        bg = archive.read_name(bg_paths[0]) if bg_paths else None
        if fg or bg:
            return apk_icon.composite_adaptive_icon(fg, bg, (255, 255, 255, 255), destination)
        return False

    def _list_apk_zip_entries(self, device_id: str, apk_path: str) -> List[str]:
        try:
            listing = self._run_exec_out(
                ['sh', '-c', 'unzip -l -- "$1"', 'droidmgr', apk_path],
                device_id,
            )
            text = listing.decode('utf-8', errors='replace')
            entries = self._parse_unzip_list(text)
            if entries:
                return entries
        except Exception:
            pass
        try:
            listing = self._run_command(['shell', 'unzip', '-l', apk_path], device_id)
            entries = self._parse_unzip_list(listing)
            if entries:
                return entries
        except Exception:
            pass
        return []

    @staticmethod
    def _parse_unzip_list(listing: str) -> List[str]:
        entries: List[str] = []
        seen_header = False
        for line in listing.splitlines():
            stripped = line.strip()
            if not seen_header:
                if stripped.lower().endswith('name') and 'length' in stripped.lower():
                    seen_header = True
                continue
            if not stripped or stripped.startswith('-') or stripped.lower().endswith('files'):
                continue
            match = re.match(r'^\s*\d+\s+\S+\s+\S+\s+(.+)$', line)
            if not match:
                continue
            name = match.group(1).strip()
            if name and posixpath.normpath(name) == name and '..' not in name.split('/'):
                entries.append(name)
        return entries

    def _read_apk_zip_entry(
        self,
        device_id: str,
        apk_path: str,
        entry: str,
        archive: '_DeviceApkArchive',
    ) -> Optional[bytes]:
        if archive.has_local(apk_path):
            return archive.read_local(apk_path, entry)
        try:
            data = self._run_exec_out(
                ['sh', '-c', 'unzip -p -- "$1" "$2"', 'droidmgr', apk_path, entry],
                device_id,
            )
            if data and not _looks_like_unzip_error(data):
                return data
        except Exception:
            pass
        try:
            local_apk = archive.ensure_local(apk_path)
            return archive.read_local(apk_path, entry) if local_apk else None
        except Exception:
            return None

    def enable_tcpip(self, device_id: str, port: int = 5555) -> str:
        """Restart ADB daemon on the device in TCP/IP mode on specified port.

        Args:
            device_id: Device ID / serial number
            port: Port number (default 5555)

        Returns:
            Output message from ADB
        """
        if not isinstance(port, int) or port < 1024 or port > 65535:
            raise ValueError(f"Invalid TCP/IP port: {port}. Must be between 1024 and 65535.")
        return self._run_command(['tcpip', str(port)], device_id=device_id)

    @staticmethod
    def _get_host_wifi_gateway() -> Optional[str]:
        """Attempt to discover the default gateway of the host's Wi-Fi adapter or hotspot network."""
        import platform
        system = platform.system().lower()
        try:
            if system == 'windows':
                out = subprocess.run(['ipconfig'], capture_output=True, text=True, timeout=3).stdout
                sections = re.split(r'\r?\n(?=[^\s])', out)
                # First priority: Wireless / Wi-Fi adapter
                for sec in sections:
                    if re.search(r'wi-?fi|wireless', sec, re.IGNORECASE):
                        m = re.search(r'Default Gateway[ .]*:\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)', sec)
                        if m:
                            gw = m.group(1).strip()
                            if gw != '0.0.0.0' and not gw.startswith('127.'):
                                return gw
                # Second priority: any adapter with gateway starting with 192.168.
                for sec in sections:
                    m = re.search(r'Default Gateway[ .]*:\s*(192\.168\.[0-9]+\.[0-9]+)', sec)
                    if m:
                        return m.group(1).strip()
            else:
                out = subprocess.run(['ip', 'route', 'show', 'default'], capture_output=True, text=True, timeout=3).stdout
                m = re.search(r'default\s+via\s+([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)\s+dev\s+([a-zA-Z0-9_\-]+)', out)
                if m:
                    gw, dev = m.group(1), m.group(2).lower()
                    if re.search(r'^(wl|wifi|wlan|ap)', dev) or gw.startswith('192.168.'):
                        return gw
        except Exception:
            pass
        return None

    def get_device_ip(self, device_id: Optional[str] = None) -> Optional[str]:
        """Attempt to determine the Wi-Fi or Hotspot IP address of the connected device.

        Detects hotspot interfaces (ap0, softap0), Wi-Fi client interfaces (wlan0, wlan1),
        routing tables, network properties, and host gateway correlation (prioritizing 192.168.*).

        Args:
            device_id: Optional Device ID / serial number

        Returns:
            IP address string if found, None otherwise
        """
        host_gw = self._get_host_wifi_gateway()
        candidates: List[Any] = []

        if device_id:
            # 1. Parse ip -4 addr show block by block
            try:
                out = self._run_command(['shell', 'ip', '-4', 'addr', 'show'], device_id=device_id)
                current_iface = ''
                for line in out.splitlines():
                    m_iface = re.match(r'^\d+:\s+([a-zA-Z0-9_\-]+):', line)
                    if m_iface:
                        current_iface = m_iface.group(1).lower()
                        continue
                    m_inet = re.search(r'inet\s+([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)', line)
                    if m_inet:
                        ip = m_inet.group(1)
                        if ip != '127.0.0.1' and not ip.startswith('127.'):
                            candidates.append((current_iface, ip))
            except Exception:
                pass

            # 2. Query hotspot & Wi-Fi interfaces specifically
            for iface in ['ap0', 'ap1', 'softap0', 'softap1', 'wlan0', 'wlan1', 'wlan2', 'swlan0', 'rndis0', 'usb0', 'eth0']:
                try:
                    out = self._run_command(['shell', 'ip', '-f', 'inet', 'addr', 'show', iface], device_id=device_id)
                    m = re.search(r'inet\s+([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)', out)
                    if m and m.group(1) != '127.0.0.1' and not m.group(1).startswith('127.'):
                        candidates.append((iface, m.group(1)))
                except Exception:
                    pass

            # 3. Parse routing table for source IP
            try:
                out = self._run_command(['shell', 'ip', 'route'], device_id=device_id)
                for line in out.splitlines():
                    m_src = re.search(r'src\s+([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)', line)
                    m_dev = re.search(r'dev\s+([a-zA-Z0-9_\-]+)', line)
                    if m_src:
                        ip = m_src.group(1)
                        iface = m_dev.group(1).lower() if m_dev else 'route'
                        if ip != '127.0.0.1' and not ip.startswith('127.'):
                            candidates.append((iface, ip))
            except Exception:
                pass

            # 4. Check DHCP and network properties
            for prop in [
                'dhcp.ap0.ipaddress', 'dhcp.softap0.ipaddress',
                'dhcp.wlan0.ipaddress', 'dhcp.wlan1.ipaddress',
                'net.ap0.ip', 'net.softap0.ip',
                'net.wlan0.ip', 'net.wlan1.ip',
                'dhcp.rndis0.ipaddress'
            ]:
                try:
                    out = self._run_command(['shell', 'getprop', prop], device_id=device_id).strip()
                    if re.match(r'^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$', out) and not out.startswith('127.'):
                        candidates.append((prop, out))
                except Exception:
                    pass

        # 5. Score candidates
        def score_candidate(iface: str, ip: str) -> int:
            if re.search(r'^(ccmni|rmnet|pdp|wwan|dummy|lo|tun|sit)', iface):
                return -1000
            score = 0
            if re.search(r'^(ap|softap)', iface):
                score += 120  # Hotspot interfaces
            elif re.search(r'^(wlan|swlan|wifi)', iface):
                score += 90   # Wi-Fi client interfaces
            elif re.search(r'^(rndis|usb)', iface):
                score += 40   # USB tethering
            elif re.search(r'^(eth)', iface):
                score += 30   # Ethernet

            # Prioritize standard 192.168.x.x addresses (typical for hotspots & LANs)
            if ip.startswith('192.168.'):
                score += 80
            elif re.match(r'^172\.(1[6-9]|2[0-9]|3[0-1])\.', ip):
                score += 30
            elif ip.startswith('10.'):
                score += 15
            else:
                score -= 50

            # Direct match with PC Wi-Fi default gateway (highest confidence)
            if host_gw and ip == host_gw:
                score += 300

            return score

        scored_candidates = []
        seen = set()
        for iface, ip in candidates:
            if ip not in seen:
                seen.add(ip)
                s = score_candidate(iface, ip)
                if s > 0:
                    scored_candidates.append((s, ip))

        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        if scored_candidates:
            return scored_candidates[0][1]

        # 6. Fallback: Host Wi-Fi default gateway (phone is hotspot)
        if host_gw:
            return host_gw

        return None

    def connect_device(self, host: str, port: int = 5555) -> str:
        """Connect to an Android device over TCP/IP.

        Args:
            host: IP address or host string
            port: Port number (default 5555)

        Returns:
            Output from adb connect command
        """
        host = host.strip()
        if not host:
            raise ValueError("Host/IP address cannot be empty.")
        address = f"{host}:{port}" if ":" not in host else host
        output = self._run_command(['connect', address])
        lower_out = output.lower()
        if 'cannot connect' in lower_out or 'failed to connect' in lower_out or 'unable to connect' in lower_out:
            raise ADBCommandError(output)
        return output

    def pair_device(self, host: str, port: int, pairing_code: str) -> str:
        """Pair with an Android device over Wi-Fi using a pairing code (Android 11+).

        Args:
            host: IP address or hostname
            port: Pairing port number
            pairing_code: 6-digit Wi-Fi pairing code

        Returns:
            Output from adb pair command
        """
        host = host.strip()
        pairing_code = str(pairing_code).strip()
        if not host:
            raise ValueError("Host/IP address cannot be empty.")
        if not pairing_code:
            raise ValueError("Pairing code cannot be empty.")

        address = f"{host}:{port}" if ":" not in host else host
        output = self._run_command(['pair', address, pairing_code])
        lower_out = output.lower()
        if 'failed:' in lower_out or 'error:' in lower_out:
            raise ADBCommandError(output)
        return output

    def disconnect_device(self, address: str) -> str:
        """Disconnect from an ADB device over network.

        Args:
            address: IP:port or device ID

        Returns:
            Output from adb disconnect command
        """
        address = address.strip()
        if not address:
            raise ValueError("Device address cannot be empty.")
        return self._run_command(['disconnect', address])

    def reboot_device(self, device_id: str, target: Optional[str] = None) -> str:
        """Reboot a device, optionally into recovery or the bootloader.

        Args:
            device_id: Device ID / serial number
            target: 'recovery', 'bootloader', 'sideload' or None for a normal reboot

        Returns:
            Output from the adb reboot command
        """
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        args = ['reboot']
        if target:
            args.append(target)
        return self._run_command(args, device_id)

    def shutdown_device(self, device_id: str) -> str:
        """Power a device off.

        'svc power shutdown' is tried first because it is the tidiest way to ask
        for a power-off, but several Android releases reject the command and exit
        non-zero. 'reboot -p' is the same power-off on those builds.
        """
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        try:
            return self._run_command(['shell', 'svc', 'power', 'shutdown'], device_id)
        except ADBCommandError:
            return self._run_command(['reboot', '-p'], device_id)

    def get_root_status(self, device_id: str) -> Dict[str, Any]:
        """Report whether adb itself runs as root and whether an su binary exists.

        An su binary on the device is not proof of access: it may need a prompt
        on the device screen, or be restricted to specific apps.
        """
        status: Dict[str, Any] = {'adb_root': False, 'shell_uid': '', 'su_path': ''}
        try:
            status['shell_uid'] = self._run_command(['shell', 'id', '-u'], device_id).strip()
        except Exception:
            pass
        status['adb_root'] = status['shell_uid'] == '0'

        try:
            su = self._run_command(['shell', 'which', 'su'], device_id).strip()
        except Exception:
            su = ''
        if not su:
            # 'which' is not on every build, so try the usual locations directly.
            try:
                listing = self._run_command(
                    ['shell', 'ls', '/system/xbin/su', '/system/bin/su', '/sbin/su',
                     '/su/bin/su', '/system/sbin/su', '/debug_ramdisk/su'],
                    device_id
                ).strip()
                su = listing.splitlines()[0].strip() if listing else ''
            except Exception:
                su = ''
        status['su_path'] = su
        return status

    def reconnect_devices(self, offline: bool = False) -> str:
        """Ask the adb server to re-establish device connections.

        Args:
            offline: Also drop devices sitting in the 'offline' state

        Returns:
            Output from the adb reconnect command
        """
        args = ['reconnect']
        if offline:
            args.append('offline')
        return self._run_command(args)

    def list_forwards(self, reverse: bool = False) -> List[Dict[str, str]]:
        """List every forward (or reverse forward) known to the adb server.

        The listing covers all connected devices, so callers interested in one
        device must filter on the 'serial' field.

        Args:
            reverse: List reverse forwards (device to host) instead of forwards
        """
        args = ['reverse', '--list'] if reverse else ['forward', '--list']
        return _parse_forward_list(self._run_command(args))

    def add_forward(self, device_id: str, local: str, remote: str, reverse: bool = False) -> str:
        """Forward a host port to a device port, or the reverse.

        Args:
            device_id: Device ID / serial number
            local: Local endpoint, e.g. 'tcp:8080' or 'localabstract:mysocket'
            remote: Remote endpoint in the same form
            reverse: Set up a reverse forward (device to host) instead
        """
        args = ['reverse' if reverse else 'forward', local, remote]
        return self._run_command(args, device_id)

    def remove_forward(self, device_id: str, local: str, reverse: bool = False) -> str:
        """Remove the forward whose local endpoint matches.

        Args:
            device_id: Device ID / serial number
            local: The local endpoint used when the forward was added
            reverse: Remove a reverse forward instead
        """
        args = ['reverse' if reverse else 'forward', '--remove', local]
        return self._run_command(args, device_id)

    def remove_all_forwards(self, device_id: Optional[str] = None, reverse: bool = False) -> str:
        """Remove every forward, for one device or for all of them.

        Args:
            device_id: Limit the removal to this device; None means every device
            reverse: Remove reverse forwards instead
        """
        args = ['reverse' if reverse else 'forward', '--remove-all']
        return self._run_command(args, device_id)

    def get_logcat(self, device_id: str) -> subprocess.Popen:
        """Start streaming `adb logcat -v brief` for a device.

        Args:
            device_id: Device ID / serial number

        Returns:
            A running subprocess.Popen with line-buffered text stdout.
            Caller is responsible for terminating the process.
        """
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        cmd = [self.adb_path, '-s', device_id, 'logcat', '-v', 'brief']
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
            )
        except FileNotFoundError:
            raise ADBNotFoundError(
                f"ADB executable not found at '{self.adb_path}'. "
                "Please verify the path in Preferences > External Tools."
            )
        return process

    def clear_logcat(self, device_id: str) -> None:
        """Clear the on-device logcat buffers (`adb logcat -c`)."""
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        self._run_command(['logcat', '-c'], device_id)

    def run_shell_command(self, device_id: str, command: str, timeout: int = 30) -> Tuple[int, str, str]:
        """Run a single shell command on a device and return (returncode, stdout, stderr).

        The whole command string is handed to the device shell verbatim, so pipes,
        redirections and quoting work as typed. Unlike `_run_command`, a non-zero exit
        status is reported as a result instead of raised, because shell utilities such
        as `grep` fail legitimately and the caller shows the exit code inline.

        Args:
            device_id: Device ID / serial number
            command: Command line to run through the device shell
            timeout: Seconds to wait before giving up

        Returns:
            Tuple of (returncode, stdout, stderr). stderr carries the sanitized
            ADB error message when the command failed.
        """
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        if not command or not command.strip():
            return 0, '', ''
        try:
            stdout = self._run_command(['shell', command], device_id, timeout=timeout)
            return 0, stdout, ''
        except ADBCommandError as exc:
            # A failed shell command is data, not a control-flow error: the device
            # itself is reachable, it just returned non-zero (or timed out).
            return 1, '', str(exc)

    def start_shell_session(self, device_id: str, allocate_tty: bool = True) -> subprocess.Popen:
        """Start an interactive `adb shell` session for a device.

        Args:
            device_id: Device ID / serial number
            allocate_tty: Request a pty (`-t`) so the device shell behaves
                interactively. Disable for adb builds that reject the flag.

        Returns:
            A running subprocess.Popen with pipes attached to stdin/stdout and
            stderr merged into stdout (as a terminal would).
            Caller is responsible for terminating the process.
        """
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        cmd = [self.adb_path, '-s', device_id, 'shell']
        if allocate_tty:
            cmd.append('-t')
        try:
            return subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
            )
        except FileNotFoundError:
            raise ADBNotFoundError(
                f"ADB executable not found at '{self.adb_path}'. "
                "Please verify the path in Preferences > External Tools."
            )

    def capture_screenshot(self, device_id: str) -> bytes:
        """Capture the current screen as PNG bytes (`adb exec-out screencap -p`).

        Uses exec-out so the raw PNG stream is returned untouched, with no CRLF
        translation that would corrupt the image.
        """
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        data = self._run_exec_out(['screencap', '-p'], device_id, timeout=30)
        if not data.startswith(b'\x89PNG'):
            raise ADBCommandError(
                "Screen capture did not return a PNG image. "
                "The device may have refused the request."
            )
        return data

    def start_screenrecord(self, device_id: str, remote_path: str, time_limit: int = 180,
                           bit_rate: Optional[str] = None,
                           size: Optional[str] = None) -> subprocess.Popen:
        """Start `adb shell screenrecord`, writing the video to a device path.

        Args:
            device_id: Device ID / serial number
            remote_path: Absolute on-device path for the .mp4 file
            time_limit: Maximum duration in seconds (Android caps this at 180)
            bit_rate: Video bit rate (e.g. '8M'); device default when omitted
            size: Size limit as WIDTHxHEIGHT (e.g. '1280x720'); device default when omitted

        Returns:
            A running subprocess.Popen. The recording keeps going until the time
            limit is reached, or until stop_screenrecord() finalizes it.
        """
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        if not remote_path or not remote_path.strip():
            raise ValueError("Remote recording path cannot be empty.")

        args = ['shell', 'screenrecord']
        if time_limit:
            args.extend(['--time-limit', str(int(time_limit))])
        if bit_rate:
            args.extend(['--bit-rate', str(bit_rate)])
        if size:
            args.extend(['--size', str(size)])
        args.append(remote_path)

        cmd = [self.adb_path, '-s', device_id] + args
        try:
            return subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
            )
        except FileNotFoundError:
            raise ADBNotFoundError(
                f"ADB executable not found at '{self.adb_path}'. "
                "Please verify the path in Preferences > External Tools."
            )

    def stop_screenrecord(self, device_id: str) -> bool:
        """Ask an on-device screenrecord to stop so it finalizes the MP4.

        Terminating the local adb client would leave the device-side encoder
        running and the file unfinalized, so SIGINT is sent to the device process
        instead. screenrecord flushes and closes the file on SIGINT.

        Returns:
            True when the signal was delivered, False when the device-side
            process could not be found or signalled.
        """
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        try:
            output = self._run_command(['shell', 'pidof screenrecord'], device_id)
        except ADBError:
            return False
        pids = [token for token in output.split() if token.isdigit()]
        if not pids:
            return False
        try:
            self._run_command(['shell', 'kill', '-INT'] + pids, device_id)
        except ADBError:
            return False
        return True


def _looks_like_unzip_error(data: bytes) -> bool:
    if not data:
        return True
    prefix = data[:48].lstrip().lower()
    return prefix.startswith(b'unzip:') or prefix.startswith(b'toybox') or prefix.startswith(b'/system/bin')


class _DeviceApkArchive:
    """Lists and reads zip entries from on-device APKs, pulling locally if unzip is missing."""

    def __init__(self, adb: ADBManager, device_id: str, apk_paths: List[str]):
        self.adb = adb
        self.device_id = device_id
        self.apk_paths = apk_paths
        self._entries: Dict[str, List[str]] = {}
        self._local: Dict[str, str] = {}
        self._tmp: Optional[str] = None

    def entries(self, apk_path: str) -> List[str]:
        if apk_path not in self._entries:
            listed = self.adb._list_apk_zip_entries(self.device_id, apk_path)
            if not listed:
                local = self.ensure_local(apk_path)
                if local:
                    listed = self._list_local(local)
            self._entries[apk_path] = listed
        return self._entries[apk_path]

    def all_entries(self) -> List[str]:
        found: List[str] = []
        for apk_path in self.apk_paths:
            found.extend(self.entries(apk_path))
        return found

    def read(self, apk_path: str, entry: str) -> Optional[bytes]:
        names = self.entries(apk_path)
        if names and entry not in names:
            return None
        return self.adb._read_apk_zip_entry(self.device_id, apk_path, entry, self)

    def read_name(self, entry: str) -> Optional[bytes]:
        for apk_path in self.apk_paths:
            names = self.entries(apk_path)
            if names and entry not in names:
                continue
            data = self.read(apk_path, entry)
            if data:
                return data
        return None

    def has_local(self, apk_path: str) -> bool:
        return apk_path in self._local

    def ensure_local(self, apk_path: str) -> Optional[str]:
        import tempfile
        if apk_path in self._local and os.path.isfile(self._local[apk_path]):
            return self._local[apk_path]
        if self._tmp is None:
            self._tmp = tempfile.mkdtemp(prefix='droidmgr_apk_')
        local = os.path.join(
            self._tmp,
            hashlib.sha256(apk_path.encode('utf-8')).hexdigest()[:16] + '.apk',
        )
        self.adb.download_file(self.device_id, apk_path, local)
        if os.path.isfile(local) and os.path.getsize(local) > 0:
            self._local[apk_path] = local
            return local
        return None

    def read_local(self, apk_path: str, entry: str) -> Optional[bytes]:
        import zipfile
        local = self._local.get(apk_path)
        if not local:
            return None
        try:
            with zipfile.ZipFile(local, 'r') as zf:
                return zf.read(entry)
        except Exception:
            return None

    @staticmethod
    def _list_local(local_apk: str) -> List[str]:
        import zipfile
        try:
            with zipfile.ZipFile(local_apk, 'r') as zf:
                return [name for name in zf.namelist() if not name.endswith('/')]
        except Exception:
            return []

    def close(self) -> None:
        import shutil
        if self._tmp and os.path.isdir(self._tmp):
            shutil.rmtree(self._tmp, ignore_errors=True)
        self._local.clear()
        self._tmp = None





