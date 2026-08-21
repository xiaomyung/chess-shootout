import ctypes
import logging
import os
from collections.abc import Callable
from typing import Any, cast

log = logging.getLogger("chess.chrome")

GWL_STYLE = -16
GWLP_WNDPROC = -4
WS_MAXIMIZEBOX = 0x00010000
WS_MINIMIZEBOX = 0x00020000
WS_THICKFRAME = 0x00040000
WM_SIZE = 0x0005
WM_ERASEBKGND = 0x0014
WM_GETMINMAXINFO = 0x0024
SIZE_MAXIMIZED = 2
BLACK_BRUSH = 4
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
MONITOR_DEFAULTTONEAREST = 2

_SNAP_STYLES = WS_MAXIMIZEBOX | WS_MINIMIZEBOX | WS_THICKFRAME


def maximized_placement(monitor_rect: tuple[int, int, int, int],
                        work_area: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """
    Work out where a maximised game window should sit and how big it should
    be, so that it fills the screen but leaves the taskbar showing. Windows
    asks for this relative to the monitor the window is on, which is what makes
    it come out right on a second monitor as well as the first. Kept a plain
    calculation so it can be tested on any machine, Windows or not

    :param monitor_rect: the whole monitor as left, top, right, bottom in
        desktop pixels
    :param work_area: the part of that monitor the taskbar leaves free, in the
        same coordinates
    :returns: x, y, width and height, with the position relative to the
        monitor's own top-left corner
    """
    ml, mt, _mr, _mb = monitor_rect
    wl, wt, wr, wb = work_area
    return (wl - ml, wt - mt, wr - wl, wb - wt)


if os.name == "nt" and ctypes.sizeof(ctypes.c_void_p) == 8:
    _WNDPROC = ctypes.WINFUNCTYPE(  # type: ignore[attr-defined]
        ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
        ctypes.c_size_t, ctypes.c_ssize_t)
else:
    _WNDPROC = None


class _POINT(ctypes.Structure):
    """
    A pair of window coordinates as Windows lays them out in memory, mirroring
    the Win32 POINT structure field for field
    """

    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MINMAXINFO(ctypes.Structure):
    """
    The limits Windows offers a window when it is about to be maximised or
    resized, mirroring the Win32 MINMAXINFO structure. Writing into it is how
    a maximise is held back to the area the taskbar leaves free
    """

    _fields_ = [
        ("ptReserved", _POINT), ("ptMaxSize", _POINT), ("ptMaxPosition", _POINT),
        ("ptMinTrackSize", _POINT), ("ptMaxTrackSize", _POINT),
    ]


class _RECT(ctypes.Structure):
    """
    A rectangle as Windows lays it out in memory -- left, top, right and
    bottom edges rather than a position and a size, mirroring Win32 RECT
    """

    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    """
    What Windows reports about one monitor: its whole area and the part of it
    the taskbar leaves free, mirroring the Win32 MONITORINFO structure
    """

    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]


class WindowsSnap:
    """
    Gives the game's borderless window the behaviour Windows players expect of
    a window: Aero Snap to the screen edges, drag-to-top to maximise, and a
    maximise that stops at the taskbar instead of covering it. It works by
    stepping in front of the window's own message handling, and exists only on
    Windows -- the window chrome installs it nowhere else
    """

    def __init__(self, hwnd: int, is_fullscreen: Callable[[], bool]) -> None:
        """
        Prepare the helper for one window and declare the Windows calls it is
        going to make. Nothing about the window changes until it is installed

        :param hwnd: Windows handle of the game window
        :param is_fullscreen: asked whether the game is fullscreen right now,
            since a fullscreen window must be left free to cover the taskbar
        """
        self._hwnd = hwnd
        self._is_fullscreen = is_fullscreen
        self._user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        self._orig_wndproc: int | None = None
        self._wndproc_cb: Any = None
        self.maximized = False
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        """
        Declare the argument and result types of every Windows call this helper
        makes, which ctypes needs before any of them can be trusted with
        handles and pointers on a 64-bit build
        """
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
        u.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        u.FillRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        u.FillRect.restype = ctypes.c_int

    def install(self) -> bool:
        """
        Turn the borderless window into one Windows is willing to snap: put the
        window styles back that make it eligible, then step in front of its
        message handling. A 32-bit host is not supported and says so rather
        than leaving the window half changed, and any failure is reported so
        the chrome can carry on without snapping

        :returns: True once the helper is in place and handling messages
        """
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

    def apply_styles(self) -> None:
        """
        Put back the resize, maximise and minimise styles a borderless window
        would otherwise lack -- without them Windows refuses to snap it at all.
        Applied again on the way out of fullscreen, which strips them
        """
        try:
            u = self._user32
            style = u.GetWindowLongPtrW(self._hwnd, GWL_STYLE)
            u.SetWindowLongPtrW(self._hwnd, GWL_STYLE, style | _SNAP_STYLES)
            u.SetWindowPos(self._hwnd, None, 0, 0, 0, 0,
                           SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
                           | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        except Exception:
            log.warning("window snap style apply failed", exc_info=True)

    def client_size(self) -> tuple[int, int] | None:
        """
        The size of the window's drawable area according to Windows itself,
        which the shell uses to keep its own drawing surface the right size
        while an edge is being dragged and no resize events are arriving

        :returns: width and height in pixels, or None when Windows would not
            answer
        """
        try:
            rect = _RECT()
            if not self._user32.GetClientRect(self._hwnd, ctypes.byref(rect)):
                return None
            return (rect.right - rect.left, rect.bottom - rect.top)
        except Exception:
            return None

    def shutdown(self) -> None:
        """
        Step back out of the window's message handling and give it its own
        handler back, done as the game closes. Safe to call when nothing was
        ever installed
        """
        if self._orig_wndproc:
            try:
                self._user32.SetWindowLongPtrW(
                    self._hwnd, GWLP_WNDPROC, self._orig_wndproc)
            except Exception:
                log.debug("window snap restore failed", exc_info=True)
            self._orig_wndproc = None
            self._wndproc_cb = None

    def _call_orig(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        """
        Hand a window message on to the handler that was there before this one,
        which every message reaches unless it was answered here first

        :param hwnd: Windows handle of the window the message is about
        :param msg: the Win32 message code
        :param wparam: the message's first parameter, whose meaning depends on
            which message it is
        :param lparam: the message's second parameter, often a pointer
        :returns: whatever the original handler answered
        """
        return cast(int, self._user32.CallWindowProcW(
            self._orig_wndproc, hwnd, msg, wparam, lparam))

    def _wndproc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        """
        See every message Windows sends the game window and step in for the
        three that matter: painting the background black so a resize does not
        flash white, noticing when the window has been maximised, and holding a
        maximise back to the area the taskbar leaves free. Everything else is
        passed straight on, and anything that goes wrong is logged and then
        passed on too, since a window handler that raises would take the window
        down with it

        :param hwnd: Windows handle of the window the message is about
        :param msg: the Win32 message code
        :param wparam: the message's first parameter, whose meaning depends on
            which message it is
        :param lparam: the message's second parameter, often a pointer
        :returns: the answer Windows gets back for this message
        """
        try:
            if msg == WM_ERASEBKGND:
                self._fill_black(hwnd, wparam)
                return 1
            if msg == WM_SIZE:
                self.maximized = (wparam == SIZE_MAXIMIZED)
            if msg == WM_GETMINMAXINFO and not self._is_fullscreen():
                result = self._call_orig(hwnd, msg, wparam, lparam)
                self._clamp_maximize_to_work_area(hwnd, lparam)
                return result
        except Exception:
            log.debug("window snap wndproc error", exc_info=True)
        return self._call_orig(hwnd, msg, wparam, lparam)

    def _fill_black(self, hwnd: int, hdc: int) -> None:
        """
        Paint the window's background black rather than letting Windows erase
        it in white, which is what stops the bright flash along the edge while
        the window is being dragged larger

        :param hwnd: handle of the window being erased
        :param hdc: Windows drawing context to paint into
        """
        try:
            rect = _RECT()
            self._user32.GetClientRect(hwnd, ctypes.byref(rect))
            brush = ctypes.windll.gdi32.GetStockObject(  # type: ignore[attr-defined]
                BLACK_BRUSH)
            self._user32.FillRect(hdc, ctypes.byref(rect), brush)
        except Exception:
            log.debug("window snap erase-bg fill failed", exc_info=True)

    def _clamp_maximize_to_work_area(self, hwnd: int, lparam: int) -> None:
        """
        Tell Windows how far the window may grow when it is maximised, so a
        borderless maximise stops at the taskbar instead of swallowing it. The
        limits are worked out for whichever monitor the window is actually on
        and written straight into the structure Windows handed over

        :param hwnd: handle of the window being maximised
        :param lparam: pointer to the limits structure to write into
        """
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
