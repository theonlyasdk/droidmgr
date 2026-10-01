"""High DPI scaling utilities for droidmgr.

Provides DPI awareness initialization and dynamic scaling helpers for Tkinter
on high DPI displays (Windows, Linux, macOS).
"""

import sys
import tkinter as tk
from tkinter import ttk, font
from typing import Optional, Tuple, Union


_dpi_awareness_initialized = False


def enable_dpi_awareness() -> bool:
    """Enable high DPI awareness to prevent blurry scaling on Windows.

    Must be called before any Tk window or GUI component is initialized.
    Safe to call on any platform (no-op on Linux/macOS).
    """
    global _dpi_awareness_initialized
    if _dpi_awareness_initialized:
        return True

    if sys.platform.startswith('win'):
        try:
            import ctypes
            # Per Monitor V2 (Windows 10 1703+)
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            _dpi_awareness_initialized = True
            return True
        except Exception:
            pass

        try:
            # Per Monitor V1 (Windows 8.1+)
            # PROCESS_PER_MONITOR_DPI_AWARE = 2
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            _dpi_awareness_initialized = True
            return True
        except Exception:
            pass

        try:
            # System DPI Aware (Windows 8.1+)
            # PROCESS_SYSTEM_DPI_AWARE = 1
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            _dpi_awareness_initialized = True
            return True
        except Exception:
            pass

        try:
            # Windows Vista+ fallback
            ctypes.windll.user32.SetProcessDPIAware()
            _dpi_awareness_initialized = True
            return True
        except Exception:
            pass

    _dpi_awareness_initialized = True
    return False


def get_dpi(window: Optional[tk.Misc] = None) -> int:
    """Get the current DPI for a given window or the primary display."""
    if sys.platform.startswith('win'):
        try:
            import ctypes
            if window is not None:
                try:
                    hwnd = window.winfo_id()
                    if hwnd and hasattr(ctypes.windll.user32, 'GetDpiForWindow'):
                        dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
                        if dpi > 0:
                            return dpi
                except Exception:
                    pass

            if hasattr(ctypes.windll.user32, 'GetDpiForSystem'):
                dpi = ctypes.windll.user32.GetDpiForSystem()
                if dpi > 0:
                    return dpi

            hdc = ctypes.windll.user32.GetDC(0)
            if hdc:
                # LOGPIXELSX = 88
                dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
                ctypes.windll.user32.ReleaseDC(0, hdc)
                if dpi > 0:
                    return dpi
        except Exception:
            pass

    if window is not None:
        try:
            # winfo_fpixels('1i') returns pixels per inch
            dpi = int(round(window.winfo_fpixels('1i')))
            if dpi > 0:
                return dpi
        except Exception:
            pass

        try:
            scaling = float(window.tk.call('tk', 'scaling'))
            dpi = int(round(scaling * 72.0))
            if dpi > 0:
                return dpi
        except Exception:
            pass

    return 96


def get_scale_factor(window: Optional[tk.Misc] = None) -> float:
    """Get display scaling factor (1.0 = 100%, 1.25 = 125%, 1.5 = 150%, 2.0 = 200%)."""
    return get_dpi(window) / 96.0


def scale_size(size: Union[int, float, Tuple[int, ...]], window: Optional[tk.Misc] = None) -> Union[int, Tuple[int, ...]]:
    """Scale a dimension or tuple of dimensions by the DPI scale factor."""
    scale = get_scale_factor(window)
    if isinstance(size, (tuple, list)):
        return tuple(int(round(s * scale)) for s in size)
    return int(round(size * scale))


def configure_dpi_styles(window: Optional[tk.Misc] = None) -> None:
    """Configure Tk scaling and ttk widget styles for crisp high DPI rendering."""
    if window is None:
        return

    dpi = get_dpi(window)
    try:
        # Set tk scaling factor (pixels per point)
        window.tk.call('tk', 'scaling', dpi / 72.0)
    except Exception:
        pass

    try:
        # Treeview rowheight hardcodes 20px on Windows.
        # Dynamically scale it according to the default font line height.
        style = ttk.Style(window)
        default_font = font.nametofont('TkDefaultFont')
        linespace = default_font.metrics('linespace')
        row_height = max(24, int(linespace * 1.35))
        style.configure('Treeview', rowheight=row_height)
    except Exception:
        pass


def setup_window_dpi(
    window: tk.Wm,
    base_width: Optional[int] = None,
    base_height: Optional[int] = None,
    min_width: Optional[int] = None,
    min_height: Optional[int] = None,
    parent: Optional[tk.Misc] = None
) -> Tuple[int, int]:
    """Configure DPI scaling, widget styles, window geometry, minsize, and centering.

    Args:
        window: The tk.Tk or tk.Toplevel window to configure.
        base_width: Standard (100% scale) width in pixels.
        base_height: Standard (100% scale) height in pixels.
        min_width: Standard minimum width in pixels.
        min_height: Standard minimum height in pixels.
        parent: Optional parent window for relative centering.

    Returns:
        Tuple of (scaled_width, scaled_height).
    """
    enable_dpi_awareness()
    configure_dpi_styles(window)

    if base_width is None or base_height is None:
        return (0, 0)

    scale = get_scale_factor(window)
    scaled_w = int(round(base_width * scale))
    scaled_h = int(round(base_height * scale))

    window.update_idletasks()
    sw = window.winfo_screenwidth()
    sh = window.winfo_screenheight()

    # Ensure window fits comfortably on screen
    scaled_w = min(scaled_w, max(sw - 40, 300))
    scaled_h = min(scaled_h, max(sh - 80, 200))

    if min_width is not None and min_height is not None:
        scaled_min_w = min(scale_size(min_width, window), scaled_w)
        scaled_min_h = min(scale_size(min_height, window), scaled_h)
        window.minsize(scaled_min_w, scaled_min_h)

    # Calculate centered position
    if parent is not None and parent.winfo_exists() and parent.winfo_ismapped():
        try:
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            cx = px + (pw - scaled_w) // 2
            cy = py + (ph - scaled_h) // 2
            # Clamp to screen bounds
            cx = max(10, min(cx, sw - scaled_w - 10))
            cy = max(10, min(cy, sh - scaled_h - 40))
        except Exception:
            cx = max(0, (sw - scaled_w) // 2)
            cy = max(0, (sh - scaled_h) // 2)
    else:
        cx = max(0, (sw - scaled_w) // 2)
        cy = max(0, (sh - scaled_h) // 2)

    window.geometry(f"{scaled_w}x{scaled_h}+{cx}+{cy}")
    return (scaled_w, scaled_h)
