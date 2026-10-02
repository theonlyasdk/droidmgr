"""UI components for droidmgr."""

from .main_window import MainWindow
from .init_dialog import InitDialog
from .about_dialog import AboutDialog
from .preferences_dialog import PreferencesDialog
from .file_manager import FileManager
from .scrcpy_output_dialog import ScrcpyOutputDialog
from .device_details_dialog import DeviceDetailsDialog
from .logcat_view import LogcatView
from .shell_view import ShellView
from .capture import (
    take_screenshot,
    record_screen,
    ScreenRecordDialog,
    ScreenRecordProgressDialog,
)
from .llm_report_dialog import LLMReportDialog, LLMReportProgressDialog
from .wireless_dialog import WirelessADBSetupDialog, ConnectWirelessDialog
from .dpi import (
    enable_dpi_awareness,
    get_dpi,
    get_scale_factor,
    scale_size,
    configure_dpi_styles,
    setup_window_dpi,
)

__all__ = [
    'MainWindow',
    'InitDialog',
    'AboutDialog',
    'PreferencesDialog',
    'FileManager',
    'ScrcpyOutputDialog',
    'DeviceDetailsDialog',
    'LogcatView',
    'ShellView',
    'take_screenshot',
    'record_screen',
    'ScreenRecordDialog',
    'ScreenRecordProgressDialog',
    'LLMReportDialog',
    'LLMReportProgressDialog',
    'WirelessADBSetupDialog',
    'ConnectWirelessDialog',
    'enable_dpi_awareness',
    'get_dpi',
    'get_scale_factor',
    'scale_size',
    'configure_dpi_styles',
    'setup_window_dpi',
]

