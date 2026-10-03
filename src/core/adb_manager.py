"""Manages ADB operations for Android devices."""

import os
import sys
import subprocess
import uuid
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import ipaddress
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


# --- Process sampling --------------------------------------------------------

# 'top' is spelled differently by every build, so its columns are read from the
# header rather than assumed. Some labels pack two columns into one token:
# 'S[%CPU]' is the state column followed by the CPU column, which puts every
# reading after it one place earlier than the count of labels suggests.
_TOP_COLUMN_NAMES = {
    'PID': 'pid', 'USER': 'user', 'CPU': 'cpu', '%CPU': 'cpu', 'RES': 'mem',
    'MEM': 'mem', '%MEM': 'mem_percent', 'ARGS': 'name', 'CMDLINE': 'name',
    'CPULINE': 'name', 'NAME': 'name',
}

# The CPU time column, which looks like nothing else in a row. It is matched
# narrowly on purpose: a process name can hold a colon, as 'com.foo:remote'
# does, and that must not be mistaken for a time.
_TOP_CPU_TIME = re.compile(r'^\d+:\d{2}([.:]\d+)?$')


def _top_columns(header: str) -> Dict[str, int]:
    """Map each 'top' column label to the position its value sits at in a row."""
    labels: List[str] = []
    for token in header.split():
        left, bracket, right = token.partition('[')
        if bracket and right.endswith(']'):
            labels.extend(part for part in (left, right[:-1]) if part)
        else:
            labels.append(token)

    columns: Dict[str, int] = {}
    for index, label in enumerate(labels):
        key = _TOP_COLUMN_NAMES.get(label.upper())
        if key and key not in columns:
            columns[key] = index
    return columns


def _field_at(parts: List[str], index: Optional[int]) -> str:
    """One field out of a row, by the position its header label was found at."""
    if index is None or index >= len(parts):
        return ''
    return parts[index]


def _percentage_columns(parts: List[str]) -> Tuple[Optional[int], Optional[int]]:
    """Where the CPU and memory percentages sit, judged by the '%' they carry.

    This is the older guess, kept for a header that names no column to read: a
    build labelling its columns differently may still write the '%' into the
    values themselves, which is what this looks for.
    """
    cpu_index = None
    mem_index = None
    for index, part in enumerate(parts):
        if '%' not in part:
            continue
        if cpu_index is None:
            cpu_index = index
        elif mem_index is None:
            mem_index = index
    return cpu_index, mem_index


def _guess_res_column(parts: List[str]) -> str:
    """The resident size, for when the header names no column to read.

    'top' prints VIRT before RES, so of the two sizes it reports the second is
    the one counted against physical memory.
    """
    candidates = [part for part in parts
                  if any(unit in part for unit in 'KMG')
                  and any(char.isdigit() for char in part)]
    if len(candidates) >= 2:
        return candidates[1]
    return candidates[0] if candidates else '0'


def _guess_args_column(parts: List[str]) -> str:
    """The command name, which is whatever follows the CPU time '0:00.30'."""
    for index, part in enumerate(parts):
        if ':' in part and index >= 5 and index + 1 < len(parts):
            return parts[index + 1]
    return parts[-1] if parts else 'unknown'


def _process_cpu(process: Dict[str, Any]) -> float:
    """A process's CPU figure as a number, whichever way it was written."""
    try:
        return float(str(process.get('cpu', 0)).rstrip('%'))
    except (TypeError, ValueError):
        return 0.0


# toybox prints the device's own totals above the process table. The CPU line
# gives the capacity of every core at once, so the busy share is the busy part
# of that capacity: 100% there means every core is busy, which is the reading a
# task manager shows, while the per-process figures are each per single core.
_TOP_CPU_TOTALS = re.compile(
    r'([\d.]+)%\s*cpu\s+([\d.]+)%\s*user\s+([\d.]+)%\s*nice\s+'
    r'([\d.]+)%\s*sys\s+([\d.]+)%\s*idle')
_TOP_MEMORY_TOTALS = re.compile(
    r'Mem:\s+([\d.]+\s*[KMGT])\s+total,\s+([\d.]+\s*[KMGT])\s+used,'
    r'\s+([\d.]+\s*[KMGT])\s+free')
_SIZE_UNITS = {'K': 1024, 'M': 1024 ** 2, 'G': 1024 ** 3, 'T': 1024 ** 4}


def _size_to_bytes(text: str) -> int:
    """'3.6G' as the byte count it stands for."""
    text = (text or '').strip()
    if not text:
        return 0
    scale = _SIZE_UNITS.get(text[-1].upper(), 1)
    if scale != 1:
        text = text[:-1]
    try:
        return int(float(text) * scale)
    except ValueError:
        return 0


def _parse_top_cpu_totals(output: str) -> Dict[str, float]:
    """The device's CPU summary, read out of a 'top' run."""
    for line in output.splitlines():
        match = _TOP_CPU_TOTALS.search(line)
        if not match:
            continue
        total = float(match.group(1))
        idle = float(match.group(5))
        busy = 0.0
        if total > 0:
            busy = max(0.0, min(100.0, (total - idle) * 100.0 / total))
        return {
            'cores': total / 100.0,
            'user': float(match.group(2)),
            'nice': float(match.group(3)),
            'system': float(match.group(4)),
            'idle': idle,
            'busy': round(busy, 1),
        }
    return {}


def _parse_top_memory_totals(output: str) -> Dict[str, int]:
    """The device's memory summary, read out of a 'top' run, in bytes."""
    for line in output.splitlines():
        match = _TOP_MEMORY_TOTALS.search(line)
        if not match:
            continue
        return {
            'total_bytes': _size_to_bytes(match.group(1)),
            'used_bytes': _size_to_bytes(match.group(2)),
            'free_bytes': _size_to_bytes(match.group(3)),
        }
    return {}


# --- Fastboot ---------------------------------------------------------------

def _parse_fastboot_devices(output: str) -> List[str]:
    """The serials of the devices 'fastboot devices' reported.

    The command prints one entry per line and nothing at all when no device is
    in fastboot mode. Builds differ over whether the line carries a state word
    after the serial, so only the first field of each line is taken.
    """
    serials = []
    for line in output.splitlines():
        fields = line.split()
        if fields:
            serials.append(fields[0])
    return serials


# --- Network inspection -------------------------------------------------------

# 'ip addr' names the interface before its flags and repeats its state and MTU
# on the same line. The interface itself may carry an '@if' suffix when it sits
# on top of another, which is not part of its name.
_IP_INTERFACE = re.compile(r'^\d+:\s+([^:@]+)(?:@\S+)?:\s*<([^>]*)>')
_IP_MTU = re.compile(r'\bmtu (\d+)')
_IP_STATE = re.compile(r'\bstate (\w+)')
_IP_ADDRESS = re.compile(r'^\s+(inet6?)\s+(\S+)')
_IP_MAC = re.compile(r'^\s+link/\S+\s+([0-9a-fA-F:]+)')

# Only the default route matters for reaching anywhere off the device.
_IP_ROUTE_VIA = re.compile(r'\bvia (\S+)')
_IP_ROUTE_DEV = re.compile(r'\bdev (\S+)')
_IP_ROUTE_SRC = re.compile(r'\bsrc (\S+)')

# 'dumpsys netstats' is a run of titled sections. Each one reports the same
# bytes under a different grouping, so only 'UID stats' counts each app once.
_NETSTATS_SECTION = re.compile(r'^([A-Za-z][A-Za-z ]*):\s*$')
_NETSTATS_IDENT = re.compile(r'\buid=(-?\d+)\s')
_NETSTATS_NETWORK = re.compile(r'networkId="([^"]*)"')
_NETSTATS_BUCKET = re.compile(
    r'st=(-?\d+)\s+rb=(\d+)\s+rp=(\d+)\s+tb=(\d+)\s+tp=(\d+)\s+op=(\d+)')

# 'dumpsys connectivity' lists every registered network request. The kind of
# request says whether an app is asking for data, listening for it, or both.
_CONNECTIVITY_REQUEST = re.compile(
    r'uid/pid:(\d+)/(\d+)\s+NetworkRequest\s*\[\s*([A-Z_]+)\s+id=\d+,\s*\[')
_CONNECTIVITY_TRANSPORTS = re.compile(r'Transports:\s*([A-Z_|]+)')
_CONNECTIVITY_CAPABILITIES = re.compile(r'Capabilities:\s*([A-Z_&|]+)')

# The addresses a network hands out for name lookups live in the active
# network's link properties, which are absent while nothing is connected.
_CONNECTIVITY_DNS = re.compile(r'DnsAddresses:\s*\[([^\]]*)\]')
_CONNECTIVITY_DEFAULT = re.compile(r'Active default network:\s*(\S+)')

# ping answers in its own words: a reply line per packet, then a summary. The
# round-trip line is missing altogether when every packet was lost.
_PING_REPLY = re.compile(r'time[=<]\s*([\d.]+)\s*ms')
_PING_SUMMARY = re.compile(
    r'(\d+)\s+packets transmitted,\s*(\d+)(?:\s+packets)?\s+received')
_PING_LOSS = re.compile(r'([\d.]+)%\s*packet loss')
_PING_RTT = re.compile(
    r'rtt\s+min/avg/max(?:\S*)?\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)(?:/([\d.]+))?')

# 'ss' cannot be used: it wants a netlink socket the shell user may not open.
# '/proc/net' is world-readable and carries the same rows with their uid.
_TCP_STATES = {
    '01': 'ESTABLISHED', '02': 'SYN_SENT', '03': 'SYN_RECV', '04': 'FIN_WAIT1',
    '05': 'FIN_WAIT2', '06': 'TIME_WAIT', '07': 'CLOSE', '08': 'CLOSE_WAIT',
    '09': 'LAST_ACK', '0A': 'LISTEN', '0B': 'CLOSING',
}

# An address of all zeroes with port zero is how the kernel writes "nobody".
_UNSPECIFIED_ADDRESSES = frozenset({'0.0.0.0:0', ':::0', '[::]:0'})


def _parse_ip_addr(output: str) -> List[Dict[str, Any]]:
    """Read the interfaces and their addresses out of 'ip addr' output."""
    interfaces: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    for line in output.splitlines():
        heading = _IP_INTERFACE.match(line)
        if heading:
            current = {
                'name': heading.group(1).strip(),
                'flags': [flag for flag in heading.group(2).split(',') if flag],
                'mtu': None,
                'state': None,
                'mac': '',
                'ipv4': [],
                'ipv6': [],
            }
            mtu = _IP_MTU.search(line)
            if mtu:
                current['mtu'] = int(mtu.group(1))
            state = _IP_STATE.search(line)
            if state:
                current['state'] = state.group(1)
            interfaces.append(current)
            continue

        if current is None:
            continue

        address = _IP_ADDRESS.match(line)
        if address:
            family = 'ipv4' if address.group(1) == 'inet' else 'ipv6'
            current[family].append(address.group(2).split('/')[0])
            continue

        mac = _IP_MAC.match(line)
        if mac:
            current['mac'] = mac.group(1)

    return interfaces


def _pick_active_interface(interfaces: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The interface carrying the address a remote peer could reach.

    A phone may hold several up at once, so a routable address is the only
    reliable test, and loopback is not one: a device with nothing else up has no
    interface to report rather than one that only talks to itself. Wireless and
    cellular names come first so that a VPN or hotspot interface does not
    outrank the interface behind it.
    """
    preferred = ('wlan', 'rmnet', 'ccmni', 'eth', 'ap', 'swlan')

    def rank(interface: Dict[str, Any]) -> Tuple[int, int]:
        if interface['state'] not in ('UP', 'UNKNOWN'):
            return (2, 0)
        for index, prefix in enumerate(preferred):
            if interface['name'].startswith(prefix):
                return (index, 0)
        return (1, 0)

    candidates = [
        iface for iface in interfaces
        if iface['name'] != 'lo'
        and any(not address.startswith('127.') for address in iface['ipv4'])
    ]
    if not candidates:
        return None
    return min(candidates, key=rank)


def _parse_ip_route(output: str) -> Dict[str, str]:
    """The default route: where traffic goes, by which interface, from what address."""
    for line in output.splitlines():
        if not line.startswith('default'):
            continue
        via = _IP_ROUTE_VIA.search(line)
        dev = _IP_ROUTE_DEV.search(line)
        src = _IP_ROUTE_SRC.search(line)
        if not via:
            continue
        return {
            'gateway': via.group(1),
            'interface': dev.group(1) if dev else '',
            'source': src.group(1) if src else '',
            'line': line.strip(),
        }
    return {}


def _parse_netstats_uid_stats(output: str) -> Dict[int, Dict[str, Any]]:
    """Bytes moved per uid, from the 'UID stats' section of 'dumpsys netstats'.

    Only that section counts each app once. 'Dev stats' holds the device as a
    whole, 'UID tag stats' splits one app across per-socket tags, and the XT
    sections are the same bytes as the iptables layer saw them, so adding the
    sections together would multiply every total several times over.

    Within the section a uid appears once per network it used and again per
    state, and each of those carries an hourly bucket per entry, so every
    bucket is added into the one figure for that uid.
    """
    totals: Dict[int, Dict[str, Any]] = {}
    section = ''
    uid: Optional[int] = None

    for line in output.splitlines():
        heading = _NETSTATS_SECTION.match(line)
        if heading:
            section = heading.group(1)
            uid = None
            continue
        if section != 'UID stats':
            continue

        if 'ident=' in line:
            match = _NETSTATS_IDENT.search(line)
            uid = int(match.group(1)) if match else None
            if uid is not None and uid not in totals:
                totals[uid] = {
                    'rx_bytes': 0, 'rx_packets': 0,
                    'tx_bytes': 0, 'tx_packets': 0, 'operations': 0,
                    'networks': set(),
                }
            if uid is not None:
                network = _NETSTATS_NETWORK.search(line)
                if network and network.group(1):
                    totals[uid]['networks'].add(network.group(1))
            continue

        if uid is None:
            continue
        bucket = _NETSTATS_BUCKET.search(line)
        if bucket:
            entry = totals[uid]
            entry['rx_bytes'] += int(bucket.group(2))
            entry['rx_packets'] += int(bucket.group(3))
            entry['tx_bytes'] += int(bucket.group(4))
            entry['tx_packets'] += int(bucket.group(5))
            entry['operations'] += int(bucket.group(6))

    return totals


def _decode_socket_address(token: str) -> str:
    """Turn one '/proc/net' address into the dotted form a reader expects.

    The kernel writes each 32-bit word in the host's own order, so the bytes of
    a word are reversed. An IPv6 address holds four such words, each reversed in
    the same way while the words themselves stay in order.
    """
    address, _, port = token.partition(':')
    try:
        raw = bytes.fromhex(address)
    except ValueError:
        return token

    if len(raw) == 4:
        host = str(ipaddress.IPv4Address(raw[::-1]))
    elif len(raw) == 16:
        words = b''.join(raw[index:index + 4][::-1] for index in range(0, 16, 4))
        host = str(ipaddress.IPv6Address(words))
    else:
        return token

    try:
        number = int(port, 16)
    except ValueError:
        number = 0
    return f'{host}:{number}'


def _parse_proc_net(output: str, protocol: str, names: Dict[int, str]) -> List[Dict[str, Any]]:
    """One row per open socket, from a '/proc/net' table.

    The rows carry the uid of the app that owns the socket, which is what makes
    them worth reading: without it a table of addresses says nothing about which
    app is talking to whom.
    """
    sockets: List[Dict[str, Any]] = []

    for line in output.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 8:
            continue
        try:
            uid = int(fields[7])
        except ValueError:
            continue

        local = _decode_socket_address(fields[1])
        remote = _decode_socket_address(fields[2])
        no_peer = remote in _UNSPECIFIED_ADDRESSES or remote.endswith(':0')
        raw_state = fields[3].upper()

        if protocol == 'UDP':
            direction = 'Outbound' if not no_peer else 'Unconnected'
            state = 'UNCONN'
        elif raw_state == '0A':
            direction = 'Listening'
            state = _TCP_STATES[raw_state]
        elif no_peer:
            direction = 'No peer'
            state = _TCP_STATES.get(raw_state, raw_state)
        else:
            # A live TCP socket carries traffic both ways; it is not outgoing.
            direction = 'Connected'
            state = _TCP_STATES.get(raw_state, raw_state)

        local_host, _, local_port = local.rpartition(':')
        remote_host, _, remote_port = remote.rpartition(':')
        sockets.append({
            'protocol': protocol,
            'direction': direction,
            'state': state,
            'local': local_host,
            'local_port': local_port,
            'remote': remote_host,
            'remote_port': remote_port,
            'uid': uid,
            'package': names.get(uid, ''),
        })

    return sockets


def _parse_network_requests(output: str) -> Dict[int, Dict[str, Any]]:
    """Who has registered for network access, gathered per uid from connectivity.

    Each request sits on its own line, so one pass over the lines collects the
    kind of request, the transports it asked for and the capabilities it wants.
    An app that has both a plain request and a listen registered appears once,
    with everything it asked for merged in.
    """
    requests: Dict[int, Dict[str, Any]] = {}

    for raw in output.splitlines():
        line = raw.strip()
        match = _CONNECTIVITY_REQUEST.match(line)
        if not match:
            continue

        uid = int(match.group(1))
        entry = requests.get(uid)
        if entry is None:
            entry = {
                'pids': set(), 'kinds': set(), 'transports': set(),
                'capabilities': set(), 'internet': False, 'validated': False,
                'count': 0,
            }
            requests[uid] = entry

        entry['count'] += 1
        entry['pids'].add(int(match.group(2)))
        entry['kinds'].add(match.group(3))

        transports = _CONNECTIVITY_TRANSPORTS.search(line)
        if transports:
            entry['transports'].update(
                name for name in transports.group(1).split('|') if name)

        capabilities = _CONNECTIVITY_CAPABILITIES.search(line)
        if capabilities:
            wanted = capabilities.group(1).split('&')
            entry['capabilities'].update(name for name in wanted if name)
            if 'INTERNET' in wanted:
                entry['internet'] = True
            if 'VALIDATED' in wanted:
                entry['validated'] = True

    return requests


def _parse_dns_servers(output: str) -> List[str]:
    """The name servers offered by whichever network is up."""
    addresses: List[str] = []
    for group in _CONNECTIVITY_DNS.findall(output):
        for address in re.findall(r'[0-9a-fA-F:.]{3,}', group):
            if address not in addresses:
                addresses.append(address)
    return addresses


def _parse_ping(output: str, error: str, host: str, count: int) -> Dict[str, Any]:
    """Read a ping run out of its own output.

    A host that cannot be reached is an answer rather than a failure, so the
    statistics are allowed to be absent: an unreachable host reports no timings
    and no summary, and says why in its error line instead.
    """
    result: Dict[str, Any] = {
        'host': host,
        'requested': count,
        'times': [float(value) for value in _PING_REPLY.findall(output)],
        'sent': 0,
        'received': 0,
        'loss': None,
        'min': None,
        'avg': None,
        'max': None,
        'jitter': None,
        'error': '',
    }

    summary = _PING_SUMMARY.search(output)
    if summary:
        result['sent'] = int(summary.group(1))
        result['received'] = int(summary.group(2))

    loss = _PING_LOSS.search(output)
    if loss:
        result['loss'] = float(loss.group(1))
    elif result['sent']:
        result['loss'] = round(
            (result['sent'] - result['received']) * 100.0 / result['sent'], 1)

    rtt = _PING_RTT.search(output)
    if rtt:
        result['min'] = float(rtt.group(1))
        result['avg'] = float(rtt.group(2))
        result['max'] = float(rtt.group(3))
        result['jitter'] = float(rtt.group(4)) if rtt.group(4) else None

    if not result['times'] and not summary:
        for line in error.splitlines():
            if line.strip():
                result['error'] = line.strip()
                break
        if not result['error']:
            result['error'] = 'No reply from this host'

    return result


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
    """Pull SSID, signal, state, link speed, frequency, and BSSID out of wifi status/dump."""
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

    link_speed_m = re.search(r'[Ll]ink speed:\s*(\d+\s*[Mm]bps)', text)
    freq_m = re.search(r'[Ff]requency:\s*(\d+\s*[Mm][Hh]z)', text)
    bssid_m = re.search(r'BSSID:\s*([0-9a-fA-F:]{17})', text)
    mac_m = re.search(r'MAC:\s*([0-9a-fA-F:]{17})', text)

    return {
        'enabled': enabled,
        'ssid': name,
        'rssi': int(rssi.group(1)) if rssi else None,
        'state': state.group(1) if state else '',
        'link_speed': link_speed_m.group(1) if link_speed_m else '',
        'frequency': freq_m.group(1) if freq_m else '',
        'bssid': bssid_m.group(1) if bssid_m else '',
        'mac': mac_m.group(1) if mac_m else '',
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

class FastbootNotFoundError(ADBError):
    """Raised when the fastboot executable cannot be found."""
    pass

_PACKAGE_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z0-9_]+)+$')

def _validate_package(package: str) -> None:
    if not package or not _PACKAGE_RE.match(package):
        raise ValueError(f"Invalid package name: {package!r}")


class ADBManager:

    
    def __init__(self, adb_path: Path):
        self.adb_path = str(adb_path)
        self._fastboot_path: Optional[str] = None
    
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
                encoding='utf-8',
                errors='replace',
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

    def get_detailed_device_info(self, device_id: str, step_cb=None) -> Dict[str, str]:
        """Fetch detailed non-confidential device information including CPU and RAM."""
        info = {}
        try:
            if step_cb:
                step_cb("Querying device identity and system properties...")
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
            if step_cb:
                step_cb("Querying CPU architecture and SoC...")
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
            if step_cb:
                step_cb("Querying RAM and memory metrics...")
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
    
    def sample_process_load(self, device_id: str, timeout: int = 20) -> Dict[str, Any]:
        """One 'top' run read as a sample: the process table and the device totals.

        Both halves come out of a single command, so a sample costs one round
        trip and the totals describe the same instant as the processes listed
        under them. Two 'top' runs a moment apart never agree exactly, so reading
        the table and the totals separately would show that disagreement as
        real movement in a graph.
        """
        output = self._run_command(['shell', 'top', '-n', '1', '-b'],
                                   device_id, timeout=timeout)
        return {
            'processes': self._parse_top_output(output),
            'cpu': _parse_top_cpu_totals(output),
            'memory': _parse_top_memory_totals(output),
        }
    
    def _parse_top_output(self, output: str) -> List[Dict[str, Any]]:
        processes = []
        lines = output.split('\n')
        
        header_found = False
        columns: Dict[str, int] = {}
        
        for line in lines:
            if 'PID' in line.upper():
                header_found = True
                columns = _top_columns(line)
                continue
            
            if header_found and line.strip():
                parts = line.split()
                if len(parts) < 5 or not parts[0].isdigit() or parts[0] == '0':
                    continue
                
                try:
                    # Positions come from the header rather than from a search
                    # for a '%' in the row. toybox writes the values as bare
                    # numbers and keeps the '%' in the label above them, so a
                    # row-wide search finds nothing at all and every CPU figure
                    # comes back as zero.
                    cpu_index = columns.get('cpu')
                    mem_index = columns.get('mem')
                    if cpu_index is None or mem_index is None:
                        # A header that names no such column still gets the
                        # older guess, in case that build marks the values
                        # themselves with a '%'.
                        found_cpu, found_mem = _percentage_columns(parts)
                        if cpu_index is None:
                            cpu_index = found_cpu
                        if mem_index is None:
                            mem_index = found_mem
                    
                    cpu = _field_at(parts, cpu_index).rstrip('%') or '0'
                    mem = _field_at(parts, mem_index) or _guess_res_column(parts)
                    
                    # A header that does not match its own rows puts the name in
                    # the wrong place, and the CPU time is what it lands on, so
                    # that reading is thrown away rather than shown as a command.
                    name = _field_at(parts, columns.get('name'))
                    if _TOP_CPU_TIME.match(name):
                        name = ''
                    name = name or _guess_args_column(parts)
                    
                    process = {
                        'pid': parts[0],
                        'user': parts[1] if len(parts) > 1 else 'sys',
                        'cpu': cpu,
                        'mem': self._format_memory(mem),
                        'name': name
                    }
                    processes.append(process)
                except Exception:
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

            # Retrieve accurate, localized application labels via PackageManager API
            labels = {}
            device_key = hashlib.sha256(device_id.encode('utf-8')).hexdigest()[:10]
            cache_file = None
            try:
                from .config_manager import ConfigManager
                cache_dir = ConfigManager().get_cache_dir('labels')
                cache_file = os.path.join(cache_dir, f"labels_{device_key}.json")
                if os.path.isfile(cache_file):
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        cached = json.load(f)
                        if isinstance(cached, dict):
                            labels.update(cached)
            except Exception:
                pass

            all_pkgs = [a['package'] for a in apps]
            missing_pkgs = [p for p in all_pkgs if p not in labels]
            if missing_pkgs:
                query_pkgs = None if len(missing_pkgs) > len(all_pkgs) * 0.7 else missing_pkgs
                fetched = self.get_app_labels(device_id, query_pkgs)
                labels.update(fetched)
                if cache_file and fetched:
                    try:
                        with open(cache_file, 'w', encoding='utf-8') as f:
                            json.dump(labels, f, indent=2, ensure_ascii=False)
                    except Exception:
                        pass

            for app in apps:
                pkg = app['package']
                if pkg in labels and labels[pkg]:
                    app['name'] = labels[pkg]

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
                info['version_name'] = line.split('=', 1)[1]
            elif 'versionCode=' in line:
                # versionCode=123 minSdk=21 targetSdk=30
                info['version_code'] = line.split('=', 1)[1].split()[0]
            elif 'firstInstallTime=' in line:
                info['install_time'] = line.split('=', 1)[1]
            elif 'lastUpdateTime=' in line:
                info['update_time'] = line.split('=', 1)[1]
            elif 'codePath=' in line:
                info['path'] = line.split('=', 1)[1]
            elif 'installerPackageName=' in line:
                info['installer'] = line.split('=', 1)[1]
            elif 'userId=' in line:
                info['user_id'] = line.split('=', 1)[1]

        # Resolve exact APK file path via pm path
        try:
            pm_path_out = self._run_command(['shell', 'pm', 'path', package], device_id, timeout=8)
            for p_line in pm_path_out.splitlines():
                p_line = p_line.strip()
                if p_line.startswith('package:'):
                    info['path'] = p_line[8:].strip()
                    break
        except Exception:
            pass

        if icon_ids:
            info['icon_res_ids'] = icon_ids

        # Resolve display name
        device_key = hashlib.sha256(device_id.encode('utf-8')).hexdigest()[:10]
        try:
            from .config_manager import ConfigManager
            cache_file = os.path.join(ConfigManager().get_cache_dir('labels'), f"labels_{device_key}.json")
            if os.path.isfile(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    labels = json.load(f)
                    if package in labels and labels[package]:
                        info['name'] = labels[package]
        except Exception:
            pass

        if 'name' not in info:
            lbl = self.get_app_labels(device_id, [package]).get(package)
            info['name'] = lbl if lbl else _display_app_name(package)

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

    def _run_probe(self, args: List[str], device_id: Optional[str] = None,
                   timeout: Optional[int] = None) -> Tuple[str, str]:
        """Run a command and return its stdout and stderr, exit code ignored.

        Diagnostic commands report their findings by failing: an unreachable host
        is the answer to a ping, not a broken command, so raising on a non-zero
        exit would throw away the only useful part of the run.
        """
        cmd = [self.adb_path]
        if device_id:
            cmd.extend(['-s', device_id])
        cmd.extend(args)

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                check=False, timeout=timeout
            )
        except FileNotFoundError:
            raise ADBNotFoundError(f"ADB executable not found at '{self.adb_path}'. Please verify the path in Preferences > External Tools.")
        except subprocess.TimeoutExpired:
            raise ADBCommandError(f"ADB command timed out: {' '.join(args)}")

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        # A device that has gone away still fails the command, and that one
        # failure is worth the friendly message rather than a raw exit code.
        lower = (stderr or stdout).lower()
        if 'device not found' in lower or 'no devices/emulators found' in lower:
            raise ADBDeviceNotFoundError(f"Device not found or disconnected: {stderr}")
        if 'device offline' in lower or 'device unauthorized' in lower:
            raise ADBDeviceOfflineError(f"Device is offline or unauthorized: {stderr}")

        return stdout, stderr

    # 'pm list packages -U' walks every package on the device, and each of the
    # network tables needs the same answer, so it is held briefly rather than
    # asked for again every time a tab is opened.
    UID_MAP_TTL = 60

    def _get_uid_map(self, device_id: str) -> Dict[int, str]:
        """Map each app's uid to its package name, cached for a minute."""
        cached = getattr(self, '_uid_map_cache', None)
        now = time.time()
        if cached and cached[0] == device_id and now - cached[1] < self.UID_MAP_TTL:
            return cached[2]

        mapping: Dict[int, str] = {}
        try:
            output = self._run_command(
                ['shell', 'pm', 'list', 'packages', '-U'], device_id, timeout=30)
        except Exception:
            output = ''

        for package, uid in re.findall(r'package:(\S+)\s+uid:(\d+)', output):
            mapping[int(uid)] = package

        self._uid_map_cache = (device_id, now, mapping)
        return mapping

    def get_cellular_info(self, device_id: str) -> Dict[str, Any]:
        """Fetch cellular telephony status including SIM state, carrier, network type, and signal."""
        try:
            sim = self._run_command(['shell', 'getprop', 'gsm.sim.state'], device_id, timeout=3).strip()
            sim_val = 'Ready' if 'READY' in sim else ('Absent' if 'ABSENT' in sim else (sim or 'Unknown'))

            operator = self._run_command(['shell', 'getprop', 'gsm.operator.alpha'], device_id, timeout=3).strip()
            if not operator:
                operator = self._run_command(['shell', 'getprop', 'gsm.sim.operator.alpha'], device_id, timeout=3).strip()

            net_type = self._run_command(['shell', 'getprop', 'gsm.network.type'], device_id, timeout=3).strip()
            if not net_type or net_type == 'Unknown,Unknown':
                net_type = 'None/Unknown'

            tele = self._run_command(['shell', 'dumpsys', 'telephony.registry'], device_id, timeout=4)
            data_state_m = re.search(r'mDataConnectionState=(\d+)', tele)
            state_map = {'0': 'Disconnected', '1': 'Connecting', '2': 'Connected', '3': 'Suspended'}
            data_state = state_map.get(data_state_m.group(1), 'Disconnected') if data_state_m else 'Disconnected'

            data_net_m = re.search(r'mDataNetworkType=([^\s]+)', tele)
            if data_net_m and data_net_m.group(1) != 'Unknown':
                net_type = data_net_m.group(1)

            sig_m = re.search(r'SignalStrength:\{([^}]+)\}', tele)
            sig_str = 'N/A'
            if sig_m:
                dbm_m = re.search(r'(?:lteDbm|gsmDbm|nrDbm|cdmaDbm)=(-?\d+)', sig_m.group(1))
                if dbm_m and dbm_m.group(1) not in ('2147483647', '99', '-1'):
                    sig_str = f"{dbm_m.group(1)} dBm"

            return {
                'sim_state': sim_val,
                'operator': operator or 'No carrier',
                'data_state': data_state,
                'network_type': net_type,
                'signal': sig_str,
            }
        except Exception as e:
            return {
                'sim_state': 'Unknown',
                'operator': 'Unknown',
                'data_state': 'Unknown',
                'network_type': 'Unknown',
                'signal': 'N/A',
                'error': str(e),
            }

    def get_routing_table(self, device_id: str) -> List[Dict[str, Any]]:
        """Fetch all routing table entries across tables."""
        try:
            out = self._run_command(['shell', 'ip', 'route', 'show', 'table', 'all'], device_id, timeout=5)
            routes = []
            for line in out.splitlines():
                line = line.strip()
                if not line or line.startswith('unreachable') or line.startswith('broadcast') or 'error' in line:
                    continue
                parts = line.split()
                dest = parts[0]
                via = ''
                dev = ''
                table = ''
                proto = ''
                metric = ''
                scope = ''
                src = ''

                i = 1
                while i < len(parts):
                    if parts[i] == 'via' and i + 1 < len(parts):
                        via = parts[i+1]; i += 2
                    elif parts[i] == 'dev' and i + 1 < len(parts):
                        dev = parts[i+1]; i += 2
                    elif parts[i] == 'table' and i + 1 < len(parts):
                        table = parts[i+1]; i += 2
                    elif parts[i] == 'proto' and i + 1 < len(parts):
                        proto = parts[i+1]; i += 2
                    elif parts[i] == 'metric' and i + 1 < len(parts):
                        metric = parts[i+1]; i += 2
                    elif parts[i] == 'scope' and i + 1 < len(parts):
                        scope = parts[i+1]; i += 2
                    elif parts[i] == 'src' and i + 1 < len(parts):
                        src = parts[i+1]; i += 2
                    else:
                        i += 1
                routes.append({
                    'destination': dest,
                    'gateway': via or 'Direct',
                    'interface': dev or 'lo',
                    'table': table or 'main',
                    'metric': metric or '-',
                    'scope': scope or proto or '-',
                    'source': src or '-',
                })
            return routes
        except Exception:
            return []

    def get_connectivity_history(self, device_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch timestamped connectivity requests and state changes."""
        try:
            out = self._run_command(['shell', 'dumpsys', 'connectivity'], device_id, timeout=10)
            events = []
            in_log = False
            log_type = 'NetworkRequest'
            for line in out.splitlines():
                if 'mNetworkRequestInfoLogs' in line:
                    in_log = True
                    log_type = 'NetworkRequest'
                    continue
                elif 'mNetworkInfoBlockingLogs' in line:
                    in_log = True
                    log_type = 'NetworkBlocking'
                    continue
                elif 'NetworkStackClient logs:' in line:
                    in_log = True
                    log_type = 'NetworkStack'
                    continue
                elif in_log and line.strip().endswith(':'):
                    if not any(k in line for k in ['NetworkRequest', 'Blocking', 'NetworkStack']):
                        in_log = False

                if in_log:
                    clean_l = line.strip()
                    if not clean_l or clean_l.startswith('total') or clean_l.startswith('bandwidth'):
                        continue
                    m = re.match(r'([0-9T:.\-]+)\s*-\s*(.+)', clean_l)
                    if m:
                        ts = m.group(1).replace('T', ' ')
                        rest = m.group(2)
                        action_m = re.match(r'([A-Za-z_]+)\s*(.*)', rest)
                        action = action_m.group(1) if action_m else log_type
                        details = action_m.group(2) if action_m else rest
                        events.append({
                            'timestamp': ts,
                            'category': log_type,
                            'event': action,
                            'details': details,
                        })
                        if len(events) >= limit:
                            break
            return events
        except Exception:
            return []

    def get_network_info(self, device_id: str) -> Dict[str, Any]:
        """Everything about the connection in one pass.

        The sources are independent, so they run together. A device that
        refuses one of them still reports the rest, since being able to say which
        half is missing is what makes the rest useful.
        """
        jobs = {
            'addresses': lambda: self._run_command(
                ['shell', 'ip', 'addr', 'show'], device_id, timeout=15),
            'route': lambda: self._run_command(
                ['shell', 'ip', 'route'], device_id, timeout=15),
            'wifi': lambda: self._run_command(
                ['shell', 'cmd', 'wifi', 'status'], device_id, timeout=15),
            'connectivity': lambda: self._run_command(
                ['shell', 'dumpsys', 'connectivity'], device_id, timeout=25),
            'cellular': lambda: self.get_cellular_info(device_id),
        }

        raw: Dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = {name: pool.submit(job) for name, job in jobs.items()}
            for name, future in futures.items():
                try:
                    raw[name] = future.result()
                except Exception:
                    raw[name] = ''

        # 'cmd wifi status' needs a privilege the shell does not have on some
        # builds, where the full dump is the only way to the network's name.
        wifi_raw = raw.get('wifi') or ''
        wifi = _parse_wifi_status(wifi_raw) if isinstance(wifi_raw, str) else {}
        if not wifi.get('ssid') and not wifi.get('state'):
            try:
                wifi = _parse_wifi_status(self._run_command(
                    ['shell', 'dumpsys', 'wifi'], device_id, timeout=20))
            except Exception:
                pass

        addr_raw = raw.get('addresses') or ''
        interfaces = _parse_ip_addr(addr_raw) if isinstance(addr_raw, str) else []
        route_raw = raw.get('route') or ''
        route = _parse_ip_route(route_raw) if isinstance(route_raw, str) else {}
        active = _pick_active_interface(interfaces)

        conn_raw = raw.get('connectivity') or ''
        default_network = _CONNECTIVITY_DEFAULT.search(conn_raw) if isinstance(conn_raw, str) else None
        cellular = raw.get('cellular') if isinstance(raw.get('cellular'), dict) else self.get_cellular_info(device_id)

        return {
            'wifi': wifi,
            'cellular': cellular,
            'interfaces': interfaces,
            'active_interface': active,
            'gateway': route.get('gateway', ''),
            'route_interface': route.get('interface', ''),
            'source_address': route.get('source', ''),
            'dns': _parse_dns_servers(conn_raw) if isinstance(conn_raw, str) else [],
            'default_network': default_network.group(1) if default_network else '',
        }

    def get_app_network_usage(self, device_id: str) -> List[Dict[str, Any]]:
        """Bytes each app has received and sent since boot, largest first.

        The figures cover the device's own history rather than the last refresh,
        so this answers what an app has been doing over the life of the boot
        rather than what it did in the last few seconds.
        """
        output = self._run_command(
            ['shell', 'dumpsys', 'netstats', 'detail'], device_id, timeout=45)
        totals = _parse_netstats_uid_stats(output)
        names = self._get_uid_map(device_id)

        rows: List[Dict[str, Any]] = []
        for uid, entry in totals.items():
            received = entry['rx_bytes']
            sent = entry['tx_bytes']
            if not received and not sent:
                continue
            rows.append({
                'uid': uid,
                'package': names.get(uid, ''),
                'rx_bytes': received,
                'tx_bytes': sent,
                'total_bytes': received + sent,
                'rx_packets': entry['rx_packets'],
                'tx_packets': entry['tx_packets'],
                'networks': ', '.join(sorted(entry['networks'])),
            })

        rows.sort(key=lambda row: -row['total_bytes'])
        return rows

    def get_active_connections(self, device_id: str) -> List[Dict[str, Any]]:
        """The sockets the device holds open, with the app behind each one."""
        names = self._get_uid_map(device_id)
        sockets: List[Dict[str, Any]] = []

        for table, protocol in (('tcp', 'TCP'), ('tcp6', 'TCP'),
                                ('udp', 'UDP'), ('udp6', 'UDP')):
            try:
                output = self._run_command(['shell', 'cat', f'/proc/net/{table}'],
                                           device_id, timeout=15)
            except Exception:
                continue
            sockets.extend(_parse_proc_net(output, protocol, names))

        sockets.sort(key=lambda row: (row['protocol'], row['state'],
                                      row['remote'], row['remote_port']))
        return sockets

    def get_network_requests(self, device_id: str) -> List[Dict[str, Any]]:
        """Which apps have registered for network access, and on what."""
        output = self._run_command(
            ['shell', 'dumpsys', 'connectivity'], device_id, timeout=25)
        requests = _parse_network_requests(output)
        names = self._get_uid_map(device_id)

        rows = []
        for uid, entry in requests.items():
            rows.append({
                'uid': uid,
                'package': names.get(uid, ''),
                'pids': ', '.join(str(pid) for pid in sorted(entry['pids'])),
                'kinds': ', '.join(sorted(entry['kinds'])),
                'transports': ', '.join(sorted(entry['transports'])),
                'internet': entry['internet'],
                'validated': entry['validated'],
                'count': entry['count'],
            })
        rows.sort(key=lambda row: (not row['internet'], row['package'], row['uid']))
        return rows

    def ping_host(self, device_id: str, host: str, count: int = 4) -> Dict[str, Any]:
        """Time the round trip to a host from the device itself.

        Pinged from the device rather than from the host, because the route to
        the internet is the device's and not the workstation's.
        """
        target = (host or '').strip()
        if not target:
            return _parse_ping('', 'No host given', '', count)

        try:
            packets = max(1, min(10, int(count)))
        except (TypeError, ValueError):
            packets = 4

        # Each packet waits up to two seconds for a reply, with slack for the
        # interval between them and for the shell round trip itself.
        stdout, stderr = self._run_probe(
            ['shell', 'ping', '-c', str(packets), '-W', '2', target],
            device_id, timeout=packets * 3 + 15)
        return _parse_ping(f'{stdout}\n{stderr}', stderr, target, packets)

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

    def _ensure_icon_extractor(self, device_id: str) -> bool:
        """Ensure icon_extractor.jar is available on device at /data/local/tmp/droidmgr_icon.jar."""
        if not hasattr(self, '_icon_extractor_ready'):
            self._icon_extractor_ready = set()
        if device_id in self._icon_extractor_ready:
            return True

        jar_candidates = [
            Path(__file__).resolve().parent.parent / 'assets' / 'icon_extractor.jar',
            Path(__file__).resolve().parent.parent / 'ui' / 'assets' / 'icon_extractor.jar',
            Path(getattr(sys, '_MEIPASS', '')) / 'assets' / 'icon_extractor.jar',
        ]
        local_jar = None
        for p in jar_candidates:
            if p.is_file():
                local_jar = str(p)
                break
        if not local_jar:
            return False

        try:
            self._run_command(['push', local_jar, '/data/local/tmp/droidmgr_icon.jar'], device_id, timeout=10)
            self._icon_extractor_ready.add(device_id)
            return True
        except Exception:
            return False

    def get_app_labels(self, device_id: str, packages: Optional[List[str]] = None) -> Dict[str, str]:
        """Query official, localized application labels via on-device PackageManager."""
        labels: Dict[str, str] = {}
        if not device_id or not self._ensure_icon_extractor(device_id):
            return labels

        try:
            cmd = [
                'shell',
                'CLASSPATH=/data/local/tmp/droidmgr_icon.jar',
                'app_process', '/',
                'com.droidmgr.IconExtractor',
                '--labels'
            ]
            if packages:
                chunk_size = 50
                for i in range(0, len(packages), chunk_size):
                    chunk = packages[i:i + chunk_size]
                    out = self._run_command([*cmd, *chunk], device_id, timeout=15)
                    for line in out.splitlines():
                        if line.startswith('LABEL:'):
                            parts = line[6:].split('\t', 1)
                            if len(parts) == 2 and parts[1].strip():
                                labels[parts[0].strip()] = parts[1].strip()
            else:
                out = self._run_command(cmd, device_id, timeout=25)
                for line in out.splitlines():
                    if line.startswith('LABEL:'):
                        parts = line[6:].split('\t', 1)
                        if len(parts) == 2 and parts[1].strip():
                            labels[parts[0].strip()] = parts[1].strip()
        except Exception:
            pass

        return labels

    def get_dev_options(self, device_id: str) -> Dict[str, Any]:
        """Query Developer Options and QA toggles (animation scales, touches, density, etc.)."""
        opts: Dict[str, Any] = {
            'window_animation_scale': '1.0',
            'transition_animation_scale': '1.0',
            'animator_duration_scale': '1.0',
            'show_touches': False,
            'pointer_location': False,
            'stay_awake': False,
            'font_scale': '1.0',
            'night_mode': 'auto',
            'density': '',
            'density_override': '',
            'size': '',
            'size_override': '',
        }
        if not device_id:
            return opts

        try:
            batch_cmd = (
                "echo WIN:$(settings get global window_animation_scale 2>/dev/null); "
                "echo TRANS:$(settings get global transition_animation_scale 2>/dev/null); "
                "echo ANIM:$(settings get global animator_duration_scale 2>/dev/null); "
                "echo TAPS:$(settings get system show_touches 2>/dev/null); "
                "echo PTR:$(settings get system pointer_location 2>/dev/null); "
                "echo AWAKE:$(settings get global stay_on_while_plugged_in 2>/dev/null); "
                "echo FONT:$(settings get system font_scale 2>/dev/null); "
                "echo NIGHT:$(settings get secure ui_night_mode 2>/dev/null); "
                "echo DENSITY:$(wm density 2>/dev/null); "
                "echo SIZE:$(wm size 2>/dev/null)"
            )
            out = self._run_command(['shell', batch_cmd], device_id, timeout=10)
            for line in out.splitlines():
                line = line.strip()
                if line.startswith('WIN:'):
                    val = line[4:].strip()
                    if val and val != 'null':
                        opts['window_animation_scale'] = val
                elif line.startswith('TRANS:'):
                    val = line[6:].strip()
                    if val and val != 'null':
                        opts['transition_animation_scale'] = val
                elif line.startswith('ANIM:'):
                    val = line[5:].strip()
                    if val and val != 'null':
                        opts['animator_duration_scale'] = val
                elif line.startswith('TAPS:'):
                    opts['show_touches'] = line[5:].strip() == '1'
                elif line.startswith('PTR:'):
                    opts['pointer_location'] = line[4:].strip() == '1'
                elif line.startswith('AWAKE:'):
                    val = line[6:].strip()
                    try:
                        opts['stay_awake'] = int(val) > 0
                    except (ValueError, TypeError):
                        opts['stay_awake'] = False
                elif line.startswith('FONT:'):
                    val = line[5:].strip()
                    if val and val != 'null':
                        opts['font_scale'] = val
                elif line.startswith('NIGHT:'):
                    val = line[6:].strip()
                    if val in ('2', 'yes'):
                        opts['night_mode'] = 'dark'
                    elif val in ('1', 'no'):
                        opts['night_mode'] = 'light'
                    else:
                        opts['night_mode'] = 'auto'
                elif line.startswith('DENSITY:') or 'density:' in line.lower():
                    for sub in line.split('\n'):
                        if 'Physical density:' in sub:
                            opts['density'] = sub.split(':', 1)[1].strip()
                        elif 'Override density:' in sub:
                            opts['density_override'] = sub.split(':', 1)[1].strip()
                elif line.startswith('SIZE:') or 'size:' in line.lower():
                    for sub in line.split('\n'):
                        if 'Physical size:' in sub:
                            opts['size'] = sub.split(':', 1)[1].strip()
                        elif 'Override size:' in sub:
                            opts['size_override'] = sub.split(':', 1)[1].strip()
        except Exception:
            pass

        return opts

    def set_dev_option(self, device_id: str, key: str, value: Any) -> Tuple[bool, str]:
        """Apply a Developer Option / QA toggle on the device.

        Returns (success: bool, error_or_output_msg: str).
        """
        if not device_id:
            return False, "No device selected."

        cmd = ""
        if key == 'window_animation_scale':
            cmd = f"settings put global window_animation_scale {value}"
        elif key == 'transition_animation_scale':
            cmd = f"settings put global transition_animation_scale {value}"
        elif key == 'animator_duration_scale':
            cmd = f"settings put global animator_duration_scale {value}"
        elif key == 'all_animation_scales':
            cmd = (
                f"settings put global window_animation_scale {value}; "
                f"settings put global transition_animation_scale {value}; "
                f"settings put global animator_duration_scale {value}"
            )
        elif key == 'show_touches':
            v = '1' if value else '0'
            cmd = f"settings put system show_touches {v}"
        elif key == 'pointer_location':
            v = '1' if value else '0'
            cmd = f"settings put system pointer_location {v}"
        elif key == 'stay_awake':
            v = '7' if value else '0'
            cmd = f"settings put global stay_on_while_plugged_in {v}"
        elif key == 'font_scale':
            cmd = f"settings put system font_scale {value}"
        elif key == 'night_mode':
            if str(value).lower() in ('dark', 'yes', '2', 'true'):
                cmd = "cmd uimode night yes; settings put secure ui_night_mode 2"
            elif str(value).lower() in ('light', 'no', '1', 'false'):
                cmd = "cmd uimode night no; settings put secure ui_night_mode 1"
            else:
                cmd = "cmd uimode night auto; settings put secure ui_night_mode 0"
        elif key == 'density':
            if str(value).lower() == 'reset':
                cmd = "wm density reset"
            else:
                cmd = f"wm density {value}"
        elif key == 'size':
            if str(value).lower() == 'reset':
                cmd = "wm size reset"
            else:
                cmd = f"wm size {value}"
        else:
            return False, f"Unknown developer option key: '{key}'"

        try:
            out = self._run_command(['shell', cmd], device_id, timeout=10)
            lowered = out.lower()
            if 'securityexception' in lowered or 'permission denial' in lowered or 'write_secure_settings' in lowered:
                return False, (
                    "Permission Denial: Writing system settings via ADB requires enabling "
                    "'USB debugging (Security settings)' in Developer Options on your phone "
                    "(common on Xiaomi/MIUI/realme), or granting WRITE_SECURE_SETTINGS via ADB."
                )
            if 'error' in lowered or 'exception' in lowered:
                return False, out.strip() or "Failed to update setting"
            return True, "OK"
        except Exception as ex:
            return False, str(ex)

    def get_users(self, device_id: str) -> List[Dict[str, Any]]:
        """List Android user profiles (pm list users, am get-current-user)."""
        users: List[Dict[str, Any]] = []
        if not device_id:
            return users
        try:
            out = self._run_command(['shell', 'pm list users; echo CURRENT:$(am get-current-user 2>/dev/null)'], device_id, timeout=10)
            current_id = None
            for line in out.splitlines():
                line = line.strip()
                if line.startswith('CURRENT:'):
                    current_id = line.split(':', 1)[1].strip()

            user_pattern = re.compile(r'UserInfo\{(\d+):([^:]+):([0-9a-fA-Fx]+)\}(.*)')
            for line in out.splitlines():
                line = line.strip()
                m = user_pattern.search(line)
                if m:
                    u_id, u_name, u_flags, rest = m.groups()
                    is_running = 'running' in rest.lower()
                    is_current = (u_id == current_id)
                    users.append({
                        'id': u_id,
                        'name': u_name,
                        'flags': u_flags,
                        'running': is_running,
                        'current': is_current,
                        'raw': line
                    })
        except Exception:
            pass
        return users

    def switch_user(self, device_id: str, user_id: str) -> Tuple[bool, str]:
        """Switch active user via am switch-user."""
        if not device_id:
            return False, "No device selected."
        try:
            out = self._run_command(['shell', f'am switch-user {user_id}'], device_id, timeout=10)
            if 'error' in out.lower() or 'exception' in out.lower():
                return False, out.strip()
            return True, "Switched user successfully."
        except Exception as ex:
            return False, str(ex)

    def create_user(self, device_id: str, name: str, user_type: str = 'standard') -> Tuple[bool, str]:
        """Create new user profile (pm create-user).
        user_type can be 'standard', 'guest', or 'managed' (work profile).
        """
        if not device_id:
            return False, "No device selected."
        name = name.strip()
        if not name:
            return False, "User name cannot be empty."
        flags = ""
        if user_type == 'guest':
            flags = "--guest "
        elif user_type == 'managed':
            flags = "--profileOf 0 --managed "
        
        try:
            out = self._run_command(['shell', f'pm create-user {flags}"{name}"'], device_id, timeout=15)
            if 'success' in out.lower():
                return True, out.strip()
            return False, out.strip() or "Failed to create user."
        except Exception as ex:
            return False, str(ex)

    def remove_user(self, device_id: str, user_id: str) -> Tuple[bool, str]:
        """Remove a user profile via pm remove-user."""
        if not device_id:
            return False, "No device selected."
        if str(user_id) == '0':
            return False, "Cannot remove primary owner (User 0)."
        try:
            out = self._run_command(['shell', f'pm remove-user {user_id}'], device_id, timeout=15)
            if 'success' in out.lower():
                return True, out.strip()
            return False, out.strip() or f"Failed to remove user {user_id}."
        except Exception as ex:
            return False, str(ex)

    def extract_app_icons_batch(
        self,
        device_id: str,
        packages: List[str],
        output_dir: str,
        cancel_check: Optional[any] = None,
    ) -> Dict[str, str]:
        """Batch extract launcher icons using on-device PackageManager via app_process.
        
        Returns a mapping of {package_name: local_png_path} for all successfully extracted icons.
        """
        results: Dict[str, str] = {}
        if not packages or not device_id:
            return results

        os.makedirs(output_dir, exist_ok=True)
        device_key = hashlib.sha256(device_id.encode('utf-8')).hexdigest()[:10]

        to_fetch = []
        for pkg in packages:
            local_icon_path = os.path.join(output_dir, f"{pkg}_{device_key}_latest_icon.png")
            if os.path.isfile(local_icon_path) and os.path.getsize(local_icon_path) > 0:
                results[pkg] = local_icon_path
            else:
                to_fetch.append(pkg)

        if not to_fetch or not self._ensure_icon_extractor(device_id):
            return results

        chunk_size = 40
        for i in range(0, len(to_fetch), chunk_size):
            if cancel_check and cancel_check():
                break
            chunk = to_fetch[i:i + chunk_size]
            try:
                cmd = [
                    'shell',
                    'CLASSPATH=/data/local/tmp/droidmgr_icon.jar',
                    'app_process', '/',
                    'com.droidmgr.IconExtractor',
                    '--out=/data/local/tmp/droidmgr_icons',
                    *chunk
                ]
                out = self._run_command(cmd, device_id, timeout=25)
                succeeded = []
                for line in out.splitlines():
                    if line.startswith("OK:"):
                        parts = line.split(":", 1)
                        if len(parts) > 1:
                            succeeded.append(parts[1].strip())

                if succeeded:
                    staging_dir = tempfile.mkdtemp(prefix='droidmgr_icons_pull_')
                    try:
                        remote_paths = [f"/data/local/tmp/droidmgr_icons/{p}.png" for p in succeeded]
                        try:
                            self._run_command(['pull', *remote_paths, staging_dir], device_id, timeout=15)
                        except Exception:
                            for p in succeeded:
                                try:
                                    self._run_command(['pull', f'/data/local/tmp/droidmgr_icons/{p}.png', os.path.join(staging_dir, f"{p}.png")], device_id, timeout=5)
                                except Exception:
                                    pass

                        for pkg_ok in succeeded:
                            if cancel_check and cancel_check():
                                break
                            staged_file = os.path.join(staging_dir, f"{pkg_ok}.png")
                            if os.path.isfile(staged_file) and os.path.getsize(staged_file) > 0:
                                target_path = os.path.join(output_dir, f"{pkg_ok}_{device_key}_latest_icon.png")
                                shutil.move(staged_file, target_path)
                                results[pkg_ok] = target_path
                    finally:
                        shutil.rmtree(staging_dir, ignore_errors=True)
            except Exception:
                pass

        return results

    def extract_app_icon(
        self,
        device_id: str,
        package: str,
        output_dir: str,
        cache_token: Optional[str] = None,
        icon_res_ids: Optional[List[int]] = None,
        known_apk_path: Optional[str] = None,
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

            # Fast path: Use on-device PackageManager via app_process
            if self._ensure_icon_extractor(device_id):
                try:
                    cmd = [
                        'shell',
                        'CLASSPATH=/data/local/tmp/droidmgr_icon.jar',
                        'app_process', '/',
                        'com.droidmgr.IconExtractor',
                        '--out=/data/local/tmp/droidmgr_icons',
                        package
                    ]
                    res = self._run_command(cmd, device_id, timeout=8)
                    if f"OK:{package}" in res:
                        self._run_command(['pull', f'/data/local/tmp/droidmgr_icons/{package}.png', local_icon_path], device_id, timeout=6)
                        if os.path.isfile(local_icon_path) and os.path.getsize(local_icon_path) > 0:
                            return local_icon_path
                except Exception:
                    pass

            if known_apk_path and known_apk_path.endswith('.apk'):
                apk_paths = [known_apk_path]
            else:
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
                out = subprocess.run(['ipconfig'], capture_output=True, text=True,
                                     encoding='utf-8', errors='replace', timeout=3).stdout
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
                out = subprocess.run(['ip', 'route', 'show', 'default'], capture_output=True, text=True,
                                     encoding='utf-8', errors='replace', timeout=3).stdout
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

    def _fastboot_executable(self) -> Optional[str]:
        """The fastboot binary belonging to the adb this manager is using.

        fastboot ships inside the same platform-tools package as adb, so it is
        looked for beside the adb already configured before falling back to
        whatever is on PATH. None means fastboot is not installed, which is
        reported as a missing tool rather than a missing device.

        The answer is remembered, including when it is None, so a machine
        without fastboot costs one lookup rather than one per refresh.
        """
        if self._fastboot_path is not None:
            return self._fastboot_path or None

        executable = 'fastboot.exe' if os.name == 'nt' else 'fastboot'
        beside_adb = Path(self.adb_path).parent / executable
        if beside_adb.exists():
            self._fastboot_path = str(beside_adb)
            return self._fastboot_path

        on_path = shutil.which(executable)
        self._fastboot_path = on_path or ''
        return self._fastboot_path or None

    def _require_fastboot(self) -> str:
        executable = self._fastboot_executable()
        if not executable:
            raise FastbootNotFoundError(
                "fastboot was not found. It ships in Android platform-tools "
                "alongside adb; install platform-tools or put fastboot on PATH."
            )
        return executable

    def _run_fastboot(self, args: List[str], timeout: Optional[int] = None,
                      check: bool = False) -> Tuple[str, str]:
        """Run fastboot and return its stdout and stderr.

        With check off the exit code is ignored, for the listing command where a
        device that is not there is an answer rather than a failure.
        """
        executable = self._require_fastboot()
        try:
            result = subprocess.run(
                [executable] + args,
                capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                check=False,
                timeout=timeout
            )
        except FileNotFoundError:
            raise FastbootNotFoundError(f"fastboot executable not found at '{executable}'.")
        except subprocess.TimeoutExpired:
            raise ADBCommandError(f"fastboot command timed out: {' '.join(args)}")

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if check and result.returncode != 0:
            detail = self._sanitize_adb_error(stderr, args[1] if len(args) > 1 else None)
            raise ADBCommandError(f"fastboot failed: {detail or 'unknown error'}")

        return stdout, stderr

    def get_fastboot_devices(self, timeout: Optional[int] = 10) -> List[str]:
        """Serials of the devices currently sitting in fastboot mode.

        adb cannot talk to a fastboot device, so its own device list says
        nothing useful about one. This asks the fastboot binary directly, and
        reports no devices at all when fastboot is not installed, since without
        the tool there is nothing that could be in fastboot mode through here.
        """
        try:
            executable = self._fastboot_executable()
            if not executable:
                return []
            stdout, _ = self._run_fastboot(['devices'], timeout=timeout)
        except (FastbootNotFoundError, ADBCommandError):
            return []
        return _parse_fastboot_devices(stdout)

    def fastboot_reboot(self, device_id: str, timeout: Optional[int] = 30) -> str:
        """Restart a fastboot-mode device back into Android.

        This is the way back out of fastboot: the device leaves fastboot mode and
        comes up as an ordinary adb device. fastboot says nothing at all on
        success, so an empty result is the expected one rather than a failure.
        """
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        self._require_fastboot()

        known = self.get_fastboot_devices(timeout=timeout)
        if device_id not in known:
            raise ADBDeviceNotFoundError(
                f"Device '{device_id}' is not in fastboot mode, so it cannot be "
                f"rebooted from there. fastboot currently sees: "
                f"{', '.join(known) if known else 'no devices'}."
            )

        stdout, stderr = self._run_fastboot(['-s', device_id, 'reboot'],
                                            timeout=timeout, check=True)
        return stdout or stderr or f'{device_id} is rebooting'

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

    def send_keyevent(self, device_id: str, keycode: int) -> bool:
        """Send an Android keyevent to the device."""
        try:
            self._run_command(['shell', 'input', 'keyevent', str(keycode)], device_id, timeout=8)
            return True
        except Exception:
            return False

    def send_text(self, device_id: str, text: str) -> bool:
        """Send text input to the device via adb shell input text."""
        try:
            escaped = text.replace(' ', '%s').replace('&', '\\&').replace('"', '\\"').replace("'", "\\'")
            self._run_command(['shell', 'input', 'text', escaped], device_id, timeout=8)
            return True
        except Exception:
            return False

    def set_clipboard_text(self, device_id: str, text: str) -> bool:
        """Set device clipboard text via cmd clipboard set-text."""
        try:
            self._run_command(['shell', 'cmd', 'clipboard', 'set-text', text], device_id, timeout=8)
            return True
        except Exception:
            return False

    def rotate_display(self, device_id: str) -> int:
        """Rotate screen orientation to the next 90-degree step."""
        try:
            cur = self._run_command(['shell', 'settings', 'get', 'system', 'user_rotation'], device_id, timeout=8).strip()
            val = int(cur) if cur.isdigit() else 0
            nxt = (val + 1) % 4
            self._run_command(['shell', 'settings', 'put', 'system', 'accelerometer_rotation', '0'], device_id, timeout=8)
            self._run_command(['shell', 'settings', 'put', 'system', 'user_rotation', str(nxt)], device_id, timeout=8)
            return nxt
        except Exception:
            return 0



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





