"""Manages ADB operations for Android devices.

Facade: the implementation lives in the adb_* mixin modules (one concern
per file, each under 400 lines). Every name ever imported from here
(ADBManager, the ADBError hierarchy, SYSTEM_APP_PATHS) is re-exported, so
existing `from core import ...` and `from core.adb_manager import ...`
imports keep working unchanged.
"""

from .adb_base import (
    ADBError,
    ADBNotFoundError,
    ADBDeviceNotFoundError,
    ADBDeviceOfflineError,
    ADBCommandError,
    FastbootNotFoundError,
    _ADBBase,
)
from .adb_devices import _DevicesMixin
from .adb_processes import _ProcessesMixin
from .adb_apps import _AppsMixin, SYSTEM_APP_PATHS
from .adb_files import _FilesMixin
from .adb_backup import _BackupMixin
from .adb_health import _HealthMixin
from .adb_diag import _DiagMixin
from .adb_report import _ReportMixin
from .adb_network import _NetworkMixin
from .adb_ping import _PingMixin
from .adb_icons import _IconsMixin
from .adb_apk_render import _ApkRenderMixin
from .adb_wireless import _WirelessMixin
from .adb_forwards import _ForwardsMixin
from .adb_shell import _ShellMixin
from .adb_devopts import _DevOptsMixin


class ADBManager(
    _ADBBase,
    _DevicesMixin,
    _ProcessesMixin,
    _AppsMixin,
    _FilesMixin,
    _BackupMixin,
    _HealthMixin,
    _DiagMixin,
    _ReportMixin,
    _NetworkMixin,
    _PingMixin,
    _IconsMixin,
    _ApkRenderMixin,
    _WirelessMixin,
    _ForwardsMixin,
    _ShellMixin,
    _DevOptsMixin,
):
    """High-level manager coordinating all ADB operations (see adb_*.py)."""
