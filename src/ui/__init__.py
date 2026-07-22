"""UI components for droidmgr."""

from .main_window import MainWindow
from .init_dialog import InitDialog
from .about_dialog import AboutDialog
from .preferences_dialog import PreferencesDialog
from .file_manager import FileManager
from .scrcpy_output_dialog import ScrcpyOutputDialog
from .device_details_dialog import DeviceDetailsDialog
from .llm_report_dialog import LLMReportDialog, LLMReportProgressDialog

__all__ = ['MainWindow', 'InitDialog', 'AboutDialog', 'PreferencesDialog', 'FileManager', 'ScrcpyOutputDialog', 'DeviceDetailsDialog', 'LLMReportDialog', 'LLMReportProgressDialog']

