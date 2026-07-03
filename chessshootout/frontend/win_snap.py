import ctypes
import logging
import os

log = logging.getLogger("chess.chrome")

GWL_STYLE = -16
GWLP_WNDPROC = -4
WS_MAXIMIZEBOX = 0x00010000
WS_MINIMIZEBOX = 0x00020000
WS_THICKFRAME = 0x00040000
WM_GETMINMAXINFO = 0x0024
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
MONITOR_DEFAULTTONEAREST = 2

_SNAP_STYLES = WS_MAXIMIZEBOX | WS_MINIMIZEBOX | WS_THICKFRAME


def maximized_placement(monitor_rect, work_area):
    ml, mt, _mr, _mb = monitor_rect
    wl, wt, wr, wb = work_area
    return (wl - ml, wt - mt, wr - wl, wb - wt)


if os.name == "nt" and ctypes.sizeof(ctypes.c_void_p) == 8:
    _WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
        ctypes.c_size_t, ctypes.c_ssize_t)
else:
    _WNDPROC = None


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MINMAXINFO(ctypes.Structure):
    _fields_ = [
        ("ptReserved", _POINT), ("ptMaxSize", _POINT), ("ptMaxPosition", _POINT),
        ("ptMinTrackSize", _POINT), ("ptMaxTrackSize", _POINT),
    ]


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]


class WindowsSnap:
    def __init__(self, hwnd, is_fullscreen):
        self._hwnd = hwnd
        self._is_fullscreen = is_fullscreen
        self._user32 = ctypes.windll.user32
        self._orig_wndproc = None
        self._wndproc_cb = None
        self._configure_signatures()

    def _configure_signatures(self):
        u = self._user32
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        u.CallWindowProcW.restype = ctypes.c_ssize_t
        u.CallWindowProcW.argtypes = [
            ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
            ctypes.c_size_t, ctypes.c_ssize_t]
        u.SetWindowPos.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        u.MonitorFromWindow.restype = ctypes.c_void_p
        u.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    def install(self):
        if _WNDPROC is None:
            log.warning("window snap: 32-bit host unsupported; skipping")
            return False
        try:
            self.apply_styles()
            self._orig_wndproc = self._user32.GetWindowLongPtrW(self._hwnd, GWLP_WNDPROC)
            self._wndproc_cb = _WNDPROC(self._wndproc)
            addr = ctypes.cast(self._wndproc_cb, ctypes.c_void_p).value
            self._user32.SetWindowLongPtrW(self._hwnd, GWLP_WNDPROC, addr)
            return True
        except Exception:
            log.warning("window snap install failed", exc_info=True)
            return False

    def apply_styles(self):
        try:
            u = self._user32
            style = u.GetWindowLongPtrW(self._hwnd, GWL_STYLE)
            u.SetWindowLongPtrW(self._hwnd, GWL_STYLE, style | _SNAP_STYLES)
            u.SetWindowPos(self._hwnd, None, 0, 0, 0, 0,
                           SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
                           | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        except Exception:
            log.warning("window snap style apply failed", exc_info=True)

    def shutdown(self):
        if self._orig_wndproc:
            try:
                self._user32.SetWindowLongPtrW(
                    self._hwnd, GWLP_WNDPROC, self._orig_wndproc)
            except Exception:
                log.debug("window snap restore failed", exc_info=True)
            self._orig_wndproc = None
            self._wndproc_cb = None

    def _call_orig(self, hwnd, msg, wparam, lparam):
        return self._user32.CallWindowProcW(
            self._orig_wndproc, hwnd, msg, wparam, lparam)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_GETMINMAXINFO and not self._is_fullscreen():
                result = self._call_orig(hwnd, msg, wparam, lparam)
                self._clamp_maximize_to_work_area(hwnd, lparam)
                return result
        except Exception:
            log.debug("window snap wndproc error", exc_info=True)
        return self._call_orig(hwnd, msg, wparam, lparam)

    def _clamp_maximize_to_work_area(self, hwnd, lparam):
        try:
            monitor = self._user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
            info = _MONITORINFO()
            info.cbSize = ctypes.sizeof(_MONITORINFO)
            if not self._user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return
            mon = (info.rcMonitor.left, info.rcMonitor.top,
                   info.rcMonitor.right, info.rcMonitor.bottom)
            work = (info.rcWork.left, info.rcWork.top,
                    info.rcWork.right, info.rcWork.bottom)
            pos_x, pos_y, width, height = maximized_placement(mon, work)
            mmi = ctypes.cast(lparam, ctypes.POINTER(_MINMAXINFO)).contents
            mmi.ptMaxPosition.x = pos_x
            mmi.ptMaxPosition.y = pos_y
            mmi.ptMaxSize.x = width
            mmi.ptMaxSize.y = height
            mmi.ptMaxTrackSize.x = width
            mmi.ptMaxTrackSize.y = height
        except Exception:
            log.debug("window snap minmax clamp failed", exc_info=True)
