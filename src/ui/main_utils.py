"""Shared constants and helpers for the MainWindow mixins."""

import ctypes
from ctypes import wintypes


_OFFLINE_ERROR_KEYWORDS = [
    'device offline', 'offline or unauthorized', 'device not found',
    'no devices/emulators found', 'disconnected', 'closed', 'unauthorized'
]

# The permission names a device quotes when it refuses to let adb wipe an app.
_CLEAR_DENIED_KEYWORDS = ['clear_app_user_data', 'clear_app_cache']

_CLEAR_DENIED_MESSAGE = (
    "This device does not let apps be cleared over adb.\n\n"
    "Its Android build withholds android.permission.CLEAR_APP_USER_DATA from the "
    "shell user, so the request is refused. Reaching app data on such a device "
    "needs root."
)

_MEMORY_UNITS = {
    'B': 1,
    'KB': 1024,
    'MB': 1024 * 1024,
    'GB': 1024 * 1024 * 1024
}

_MEMORY_LIMIT_BYTES = 300 * 1024 * 1024


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ('cb', ctypes.c_ulong),
        ('PageFaultCount', ctypes.c_ulong),
        ('PeakWorkingSetSize', ctypes.c_size_t),
        ('WorkingSetSize', ctypes.c_size_t),
        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
        ('QuotaPagedPoolUsage', ctypes.c_size_t),
        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
        ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
        ('PagefileUsage', ctypes.c_size_t),
        ('PeakPagefileUsage', ctypes.c_size_t),
        ('PrivateUsage', ctypes.c_size_t),
    ]


_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_kernel32.GetCurrentProcess.restype = wintypes.HANDLE
_psapi = ctypes.WinDLL('psapi', use_last_error=True)
_get_process_memory_info = _psapi.GetProcessMemoryInfo
_get_process_memory_info.argtypes = (
    wintypes.HANDLE, ctypes.POINTER(_ProcessMemoryCounters), wintypes.DWORD)
_get_process_memory_info.restype = wintypes.BOOL

CORE_SYSTEM_PACKAGES = {
    'com.android.settings', 'com.android.systemui', 'com.android.launcher',
    'com.android.launcher3', 'com.google.android.apps.nexuslauncher',
    'com.google.android.gms', 'com.android.vending', 'com.android.packageinstaller',
    'com.google.android.packageinstaller', 'com.android.phone', 'com.android.providers.telephony',
    'com.android.shell', 'com.android.bluetooth', 'com.android.camera2', 'com.android.keychain',
    'com.android.location.fused', 'com.android.nfc', 'com.android.se', 'com.android.inputmethod.latin'
}

SYSTEM_APP_PATHS = ('/system', '/product', '/vendor', '/system_ext', '/odm', '/apex')

# Times (ms) to refresh the device list after a reboot or an adb reconnect, while
# the device is still coming back.
_RECONNECT_POLL_DELAYS = (8000, 20000, 35000)

# Power menu actions: the label shown to the user, the adb reboot target (None for
# a normal reboot or a shutdown), and the detail shown in the confirmation prompt.
_POWER_ACTIONS = {
    'reboot': ('Reboot', None, 'The device will restart normally.'),
    'recovery': ('Reboot to Recovery', 'recovery', 'The device will restart into recovery.'),
    'bootloader': ('Reboot to Fastboot',
                   'bootloader',
                   'The device will restart into fastboot mode, where adb cannot talk '
                   'to it. Nothing in this app will work until it is booted back '
                   'into Android with "Reboot from Fastboot to Android".'),
    'shutdown': ('Shut Down', None, 'The device will power off and must be turned on by hand.'),
}


def _looks_like_system_package(package: str, app_path: str = '') -> bool:
    """Whether a package sits in a system image or is a known core app."""
    if app_path and app_path.startswith(SYSTEM_APP_PATHS):
        return True
    return (package in CORE_SYSTEM_PACKAGES
            or package.startswith(('com.android.', 'com.google.android.')))


def _is_offline_error(msg: str) -> bool:
    """Whether an exception message describes an unreachable or unauthorized device."""
    lower_msg = msg.lower()
    return any(keyword in lower_msg for keyword in _OFFLINE_ERROR_KEYWORDS)


def _is_clear_denied(msg: str) -> bool:
    """Whether an exception message is the device refusing to wipe an app."""
    lower_msg = msg.lower()
    return any(keyword in lower_msg for keyword in _CLEAR_DENIED_KEYWORDS)


def _format_bytes(num_bytes: int) -> str:
    """Render a byte count as a short human-readable size such as '12.4 MB'."""
    size = float(num_bytes or 0)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            if unit == 'B':
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _app_sort_key(app: dict, col: str):
    """Sort key for one app entry, keyed by the app list's column name.

    Sorting happens on the raw values rather than the rendered cells so that
    Size orders by exact bytes instead of the rounded '4.6 MB' text.
    """
    if col == 'Size':
        return app.get('size_bytes', 0)
    return str(app.get(col.lower(), '') or '').lower()


def _parse_memory(val: str) -> int:
    """Parse a process memory string such as '12.5 MB' into a byte count."""
    parts = str(val).split()
    num = float(parts[0])
    unit = parts[1].upper() if len(parts) > 1 else 'B'
    return int(num * _MEMORY_UNITS.get(unit, 1))


