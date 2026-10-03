"""Pure parsing helpers for health/battery/storage/bugreport output."""

import json
import re
import zipfile
from typing import Dict, Any, List, Optional, Tuple
# Reads the device state that a health dashboard shows, one entry per source.
UNAVAILABLE = 'Unavailable'

_BATTERY_STATUS = {1: 'Unknown', 2: 'Charging', 3: 'Discharging', 4: 'Not charging', 5: 'Full'}
_BATTERY_HEALTH = {1: 'Unknown', 2: 'Good', 3: 'Overheating', 4: 'Dead',
                   5: 'Over voltage', 6: 'Unspecified failure', 7: 'Cold'}
_THERMAL_STATUS = {0: 'None', 1: 'Light throttling', 2: 'Moderate throttling',
                   3: 'Severe throttling', 4: 'Critical', 5: 'Emergency',
                   6: 'Shutdown imminent'}

# A thermal entry holds mName and mValue in either order, and different Android
# releases disagree on which comes first. '[^{}]*?' keeps the two inside the same
# entry so a sensor cannot pick up its neighbour's reading.
_THERMAL_ENTRY = re.compile(
    r'mName=([^\s,}]+)[^{}]*?mValue=(-?\d+(?:\.\d+)?)'
    r'|mValue=(-?\d+(?:\.\d+)?)[^{}]*?mName=([^\s,}]+)')

# 'dumpsys diskstats' reports one bracketed array per kind of figure, each with
# one entry per installed package. Package names never contain a bracket, so a
# negated character class is enough to capture an array's contents.
_DISKSTATS_ARRAYS = re.compile(
    r'^(Package Names|App Sizes|App Data Sizes|Cache Sizes):\s*\[([^][]*)\]\s*$',
    re.MULTILINE)



# A bugreport opens with plain 'Key: value' lines before the dumpsys body. These
# are the ones worth quoting back to the user, mapped to the name used for them.

# dumpstate writes down whatever it could not gather, which is what explains a
# gap in a report, so those lines are worth surfacing rather than burying.

# The header sits within the first few kilobytes while the report itself runs to
# tens of megabytes, so only the head of it is ever read.

# dumpstate's own log runs to about a hundred kilobytes on a busy device.


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

def _decode_array(contents: str) -> List[Any]:
    """Decode one of diskstats' bracketed arrays, or nothing if it is malformed."""
    try:
        values = json.loads(f'[{contents}]')
    except ValueError:
        return []
    return values if isinstance(values, list) else []

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



