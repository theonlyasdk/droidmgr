"""One-click screenshot and screen recording, independent of scrcpy mirroring."""

from .capture_utils import (
    _default_dir,
    _existing_dir,
    _format_duration,
    _timestamp,
    _unique_path,
    open_path,
    remember_folder,
)

from .capture_screenshot import (
    _on_screenshot_saved,
    take_screenshot,
)

from .capture_record import (
    BIT_RATE_CHOICES,
    BIT_RATE_LABELS,
    SIZE_CHOICES,
    ScreenRecordDialog,
    ScreenRecordProgressDialog,
    record_screen,
)

__all__ = [
    'BIT_RATE_CHOICES',
    'BIT_RATE_LABELS',
    'SIZE_CHOICES',
    'ScreenRecordDialog',
    'ScreenRecordProgressDialog',
    '_default_dir',
    '_existing_dir',
    '_format_duration',
    '_on_screenshot_saved',
    '_timestamp',
    '_unique_path',
    'open_path',
    'record_screen',
    'remember_folder',
    'take_screenshot',
]
