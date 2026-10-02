"""File drops from Explorer onto Tk widgets.

tkdnd is not a dependency of this project, so on Windows the shell32 API is used
directly: DragAcceptFiles registers a window with the shell, and the shell answers
a drop with WM_DROPFILES, which a subclassed window procedure intercepts.

On any other platform `enable_file_drop` reports failure and callers keep using
their normal file picker.
"""

import ctypes
import sys
import traceback
from ctypes import wintypes


WM_DROPFILES = 0x0233
GWL_WNDPROC = -4

# iFile value that asks DragQueryFile for the number of dropped files.
_DRAG_QUERY_COUNT = 0xFFFFFFFF

_LRESULT = ctypes.c_ssize_t
_WNDPROC = ctypes.WINFUNCTYPE(
    _LRESULT, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM
)


def _point_from_lparam(lparam):
    """Screen coordinates carried by the WM_DROPFILES lparam, as signed shorts."""
    x = ctypes.c_short(lparam & 0xFFFF).value
    y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
    return x, y


def _window_handle(widget):
    """The HWND of a widget's window, as Tk reports it on Windows."""
    raw = widget.winfo_toplevel().winfo_id()
    # Tk hands back an integer on Windows and a hex string on some other builds.
    handle = int(raw, 16) if isinstance(raw, str) else int(raw)
    if not handle:
        raise OSError('widget has no native window handle')
    return wintypes.HWND(handle)


def _as_handle(value):
    """Coerce a window message wparam into an HGLOBAL, however it arrived."""
    if isinstance(value, int):
        return wintypes.HANDLE(value)
    return wintypes.HANDLE(ctypes.cast(value, ctypes.c_void_p).value)


# DROPFILES is {DWORD pFiles; POINT pt; BOOL fNC; BOOL fWide}, so fWide is the
# fifth 32-bit field. Explorer always sends wide lists, but a 16-bit legacy
# sender can still hand over an ANSI one, which DragQueryFileW would read as
# UTF-16 and mangle.
_FWIDE_FIELD_INDEX = 4


class _FileDropTarget:
    """Accepts file drops on one widget, inside one window.

    The window itself is registered with the shell rather than the widget, so the
    drop position is hit-tested against the widget rectangle. That keeps a single
    subclass per window however many widgets want drops.

    The instance must outlive the window: it holds the window procedure that
    native code calls back into. `enable_file_drop` stores it on the widget.
    """

    def __init__(self, widget, on_paths):
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        shell32 = ctypes.WinDLL('shell32', use_last_error=True)

        # SetWindowLongPtrW on 64-bit, SetWindowLongW on 32-bit.
        set_long = getattr(user32, 'SetWindowLongPtrW', None) or user32.SetWindowLongW
        get_long = getattr(user32, 'GetWindowLongPtrW', None) or user32.GetWindowLongW
        set_long.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
        set_long.restype = ctypes.c_ssize_t
        get_long.argtypes = (wintypes.HWND, ctypes.c_int)
        get_long.restype = ctypes.c_ssize_t

        shell32.DragAcceptFiles.argtypes = (wintypes.HWND, wintypes.BOOL)
        shell32.DragAcceptFiles.restype = None
        shell32.DragFinish.argtypes = (wintypes.HANDLE,)
        shell32.DragFinish.restype = None
        shell32.DragQueryFileW.argtypes = (
            wintypes.HANDLE, ctypes.c_uint, wintypes.LPWSTR, ctypes.c_uint)
        shell32.DragQueryFileW.restype = ctypes.c_uint
        shell32.DragQueryFileA.argtypes = (
            wintypes.HANDLE, ctypes.c_uint, ctypes.c_char_p, ctypes.c_uint)
        shell32.DragQueryFileA.restype = ctypes.c_uint
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.GlobalLock.argtypes = (wintypes.HANDLE,)
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = (wintypes.HANDLE,)
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        user32.CallWindowProcW.argtypes = (
            ctypes.c_void_p, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallWindowProcW.restype = _LRESULT

        self._shell32 = shell32
        self._user32 = user32
        self._kernel32 = kernel32
        self._widget = widget
        self._on_paths = on_paths

        self._hwnd = _window_handle(widget)
        self._old_proc = get_long(self._hwnd, GWL_WNDPROC)
        # Kept on the instance: if this reference dies, native code would call freed
        # memory the next time a message arrives.
        self._proc = _WNDPROC(self._window_proc)
        shell32.DragAcceptFiles(self._hwnd, True)
        set_long(self._hwnd, GWL_WNDPROC, ctypes.cast(self._proc, ctypes.c_void_p).value)

    def _hits_widget(self, x, y):
        """Whether a screen point falls inside the target widget."""
        try:
            left = self._widget.winfo_rootx()
            top = self._widget.winfo_rooty()
            width = self._widget.winfo_width()
            height = self._widget.winfo_height()
        except Exception:
            return False
        return left <= x < left + width and top <= y < top + height

    def _is_wide_drop(self, hdrop):
        """Whether the dropped file list is stored as UTF-16 rather than ANSI."""
        address = self._kernel32.GlobalLock(hdrop)
        if not address:
            return True
        try:
            # DragFinish frees the handle, so it has to be unlocked first.
            fields = ctypes.cast(address, ctypes.POINTER(ctypes.c_int32))
            return bool(fields[_FWIDE_FIELD_INDEX])
        finally:
            self._kernel32.GlobalUnlock(hdrop)

    def _dropped_paths(self, hdrop):
        """Read the dropped file list, honouring the DROPFILES character width."""
        shell32 = self._shell32
        if self._is_wide_drop(hdrop):
            query = shell32.DragQueryFileW
            empty, decode = ctypes.create_unicode_buffer, (lambda raw: raw)
        else:
            query = shell32.DragQueryFileA
            empty, decode = ctypes.create_string_buffer, (
                lambda raw: raw.decode('mbcs', errors='replace'))

        count = query(hdrop, _DRAG_QUERY_COUNT, None, 0)
        paths = []
        for index in range(count):
            needed = query(hdrop, index, None, 0)
            buffer = empty(needed + 1)
            if query(hdrop, index, buffer, needed + 1):
                paths.append(decode(buffer.value))
        return paths

    def _handle_drop(self, wparam, lparam):
        hdrop = _as_handle(wparam)
        paths = []
        if self._hits_widget(*_point_from_lparam(lparam)):
            paths = self._dropped_paths(hdrop)
        # The handle must be released whether or not the drop was ours.
        self._shell32.DragFinish(hdrop)
        if not paths:
            return
        # Hand off to the event loop: installing an APK inside a window procedure
        # would block the UI thread inside native dispatch.
        self._widget.after(0, lambda: self._on_paths(paths))

    def _window_proc(self, hwnd, msg, wparam, lparam):
        """Window procedure: swallow WM_DROPFILES, pass everything else to Tk."""
        if msg == WM_DROPFILES:
            self._handle_drop(wparam, lparam)
            return 0
        return self._user32.CallWindowProcW(self._old_proc, hwnd, msg, wparam, lparam)


def enable_file_drop(widget, on_paths):
    """Let Explorer file drops on `widget` call `on_paths` with the dropped paths.

    Failures are reported rather than swallowed: a window procedure that raises
    inside native dispatch would otherwise cost the whole UI thread.

    Args:
        widget: The widget that should react to drops
        on_paths: Callable taking a list of path strings

    Returns:
        True when drops are now accepted, False when the platform cannot support it.
    """
    if not sys.platform.startswith('win'):
        return False
    try:
        target = _FileDropTarget(widget, on_paths)
    except Exception:
        traceback.print_exc()
        return False
    # Bound to the widget so the window procedure stays valid for as long as it does.
    widget._file_drop_target = target
    return True