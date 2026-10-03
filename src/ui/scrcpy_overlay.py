"""Overlay navigation and control toolbar for scrcpy screen mirroring sessions.

Facade that re-exports the split scrcpy_* modules so existing imports
keep working (e.g. ``from .scrcpy_overlay import ScrcpyOverlayToolbar``).
"""

import tkinter as tk

from .scrcpy_keys import (
    KEYCODE_HOME,
    KEYCODE_BACK,
    KEYCODE_VOLUME_UP,
    KEYCODE_VOLUME_DOWN,
    KEYCODE_POWER,
    KEYCODE_APP_SWITCH,
    KEYCODE_WAKEUP,
    KEYCODE_SLEEP,
    KEYCODE_PASTE,
    VK_LMENU,
    VK_ESCAPE,
    VK_HOME,
    VK_UP,
    VK_DOWN,
    VK_B,
    VK_H,
    VK_P,
    VK_R,
    VK_S,
    VK_V,
    KEYEVENTF_KEYUP,
    HWND_TOPMOST,
    HWND_NOTOPMOST,
    SWP_NOMOVE,
    SWP_NOSIZE,
    SWP_NOACTIVATE,
)
from .scrcpy_overlay_tooltip import _Tooltip
from .scrcpy_toolbar import ScrcpyToolbarMixin
from .scrcpy_tracking import ScrcpyTrackingMixin
from .scrcpy_injection import ScrcpyInjectionMixin
from .scrcpy_actions import ScrcpyActionsMixin


class ScrcpyOverlayToolbar(
    ScrcpyToolbarMixin,
    ScrcpyTrackingMixin,
    ScrcpyInjectionMixin,
    ScrcpyActionsMixin,
    tk.Toplevel,
):
    """Vertical floating overlay control bar sticking to the right edge of scrcpy."""


__all__ = ['ScrcpyOverlayToolbar']
