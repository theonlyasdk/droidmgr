"""Small, optional Windows taskbar progress indicator."""

import ctypes
import sys
import uuid


class TaskbarProgress:
    """Drive the Windows taskbar progress bar without a pywin32 dependency."""

    _CLSID_TASKBAR_LIST = "56FDF344-FD6D-11d0-958A-006097C9A090"
    _IID_TASKBAR_LIST3 = "EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF"
    _TBPF_NOPROGRESS = 0
    _TBPF_INDETERMINATE = 1
    _TBPF_NORMAL = 2

    def __init__(self, window):
        self._pointer = None
        self._ole32 = None
        self._com_initialized = False
        self._hwnd = None
        self._closed = False
        if sys.platform != "win32":
            return
        try:
            self._hwnd = ctypes.c_void_p(window.winfo_id())
            self._ole32 = ctypes.OleDLL("ole32")
            self._ole32.CoInitialize.argtypes = [ctypes.c_void_p]
            self._ole32.CoInitialize.restype = ctypes.c_long
            result = self._ole32.CoInitialize(None)
            if result < 0:
                return
            self._com_initialized = True

            class GUID(ctypes.Structure):
                _fields_ = [("data", ctypes.c_ubyte * 16)]

                @classmethod
                def from_string(cls, value):
                    return cls((ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le))

            self._ole32.CoCreateInstance.argtypes = [
                ctypes.POINTER(GUID), ctypes.c_void_p, ctypes.c_ulong,
                ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p),
            ]
            self._ole32.CoCreateInstance.restype = ctypes.c_long
            pointer = ctypes.c_void_p()
            result = self._ole32.CoCreateInstance(
                ctypes.byref(GUID.from_string(self._CLSID_TASKBAR_LIST)), None, 1,
                ctypes.byref(GUID.from_string(self._IID_TASKBAR_LIST3)), ctypes.byref(pointer),
            )
            if result < 0 or not pointer:
                self.close()
                return
            self._pointer = pointer
            if self._call(3, ctypes.c_long) < 0:  # HrInit
                self.close()
        except Exception:
            self.close()

    def _call(self, index, result_type, *arg_types_and_values):
        if not self._pointer:
            return 0
        vtable = ctypes.cast(self._pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        prototype = ctypes.WINFUNCTYPE(result_type, ctypes.c_void_p, *arg_types_and_values[::2])
        function = prototype(vtable[index])
        return function(self._pointer, *arg_types_and_values[1::2])

    def _set_state(self, state):
        if self._pointer and self._hwnd:
            self._call(10, ctypes.c_long, ctypes.c_void_p, self._hwnd, ctypes.c_int, state)

    def set_indeterminate(self):
        self._set_state(self._TBPF_INDETERMINATE)

    def set_value(self, done, total):
        if not self._pointer or not self._hwnd:
            return
        if total <= 0:
            self.set_indeterminate()
            return
        self._set_state(self._TBPF_NORMAL)
        self._call(9, ctypes.c_long, ctypes.c_void_p, self._hwnd,
                   ctypes.c_ulonglong, max(0, int(done)),
                   ctypes.c_ulonglong, max(1, int(total)))

    def clear(self):
        self._set_state(self._TBPF_NOPROGRESS)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._pointer:
                self.clear()
                self._call(2, ctypes.c_ulong)  # IUnknown::Release
                self._pointer = None
        except Exception:
            pass
        if self._com_initialized and self._ole32:
            try:
                self._ole32.CoUninitialize()
            except Exception:
                pass
            self._com_initialized = False
