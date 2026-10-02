"""UI components for droidmgr."""

from .main_window import MainWindow
from .init_dialog import InitDialog
from .about_dialog import AboutDialog
from .preferences_dialog import PreferencesDialog
from .file_manager import FileManager
from .scrcpy_output_dialog import ScrcpyOutputDialog
from .device_details_dialog import DeviceDetailsDialog
from .process_graph import ProcessHistoryWindow
from .forward_dialog import ForwardDialog
from .file_drop import enable_file_drop
from .logcat_view import LogcatView
from .shell_view import ShellView
from .capture import (
    take_screenshot,
    record_screen,
    ScreenRecordDialog,
    ScreenRecordProgressDialog,
)
from .apk_extract import extract_apk
from .llm_report_dialog import LLMReportDialog, LLMReportProgressDialog
from .bugreport_dialog import BugReportDialog, BugReportProgressDialog
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
    'ProcessHistoryWindow',
    'ForwardDialog',
    'enable_file_drop',
    'LogcatView',
    'ShellView',
    'take_screenshot',
    'record_screen',
    'ScreenRecordDialog',
    'ScreenRecordProgressDialog',
    'extract_apk',
    'LLMReportDialog',
    'LLMReportProgressDialog',
    'BugReportDialog',
    'BugReportProgressDialog',
    'WirelessADBSetupDialog',
    'ConnectWirelessDialog',
    'enable_dpi_awareness',
    'get_dpi',
    'get_scale_factor',
    'scale_size',
    'configure_dpi_styles',
    'setup_window_dpi',
]

