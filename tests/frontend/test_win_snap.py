"""Windows taskbar-aware maximize geometry is a pure function, so it can be
unit-tested on any host; the Win32 message pump itself is exercised only on
Windows (the user's VM). Also pins that the module imports cleanly off-Windows
(the WndProc factory is Windows-only).

install() is covered off-Windows through a stand-in user32: every entry point
the helper declares is a recording callable, patched in as ctypes.windll so the
helper can be built on any host and never touches a real window. What matters
there is ordering under failure -- see the install tests."""
import ctypes
import os
import types

import pytest

import chessshootout.frontend.win_snap as ws
from chessshootout.frontend.win_snap import maximized_placement


@pytest.mark.parametrize("monitor, work, expected", [
    ((0, 0, 1920, 1080), (0, 0, 1920, 1040), (0, 0, 1920, 1040)),        # taskbar bottom
    ((0, 0, 1920, 1080), (0, 40, 1920, 1080), (0, 40, 1920, 1040)),      # taskbar top
    ((0, 0, 1920, 1080), (60, 0, 1920, 1080), (60, 0, 1860, 1080)),      # taskbar left
    ((0, 0, 1920, 1080), (0, 0, 1860, 1080), (0, 0, 1860, 1080)),        # taskbar right
    ((1920, 0, 3840, 1080), (1920, 0, 3840, 1040), (0, 0, 1920, 1040)),  # secondary (right)
    ((-1920, 0, 0, 1080), (-1920, 40, 0, 1080), (0, 40, 1920, 1040)),    # secondary (left)+top bar
])
def test_maximized_placement_is_monitor_relative_and_taskbar_aware(monitor, work, expected):
    """Position is relative to the monitor origin; size is the work area (taskbar stays)."""
    assert maximized_placement(monitor, work) == expected


def test_win_snap_module_imports_on_any_platform():
    if os.name != "nt":
        assert ws._WNDPROC is None, "the WndProc factory is Windows-only"


HWND = 0xFEED
ORIGINAL_WNDPROC = 0x1234


class _FakeFn:
    """One user32 entry point: records every call, hands back a fixed value, and
    can be told to raise the way ctypes does when a call fails."""

    def __init__(self):
        self.ret = 0
        self.fails_when = None
        self.restype = None
        self.argtypes = None
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        if self.fails_when is not None and self.fails_when(*args):
            raise OSError("user32 call failed")
        return self.ret


class _FakeUser32:
    """Every user32 name WindowsSnap declares a signature for. Anything the
    helper reaches for that is missing here would raise, which is the point:
    the fake fails loudly rather than silently absorbing a new call."""

    NAMES = ("GetWindowLongPtrW", "SetWindowLongPtrW", "CallWindowProcW",
             "SetWindowPos", "MonitorFromWindow", "GetMonitorInfoW",
             "GetClientRect", "FillRect")

    def __init__(self):
        for name in self.NAMES:
            setattr(self, name, _FakeFn())


def _snap(monkeypatch, wndproc_swap_fails=False):
    """Build a WindowsSnap on any host: a stand-in windll plus a real ctypes
    callback factory (CFUNCTYPE stands in for the Windows-only WINFUNCTYPE, so
    ctypes.cast on the callback still works)."""
    user32 = _FakeUser32()
    user32.GetWindowLongPtrW.ret = ORIGINAL_WNDPROC
    if wndproc_swap_fails:
        user32.SetWindowLongPtrW.fails_when = (
            lambda hwnd, index, value: index == ws.GWLP_WNDPROC)
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(user32=user32),
                        raising=False)
    monkeypatch.setattr(ws, "_WNDPROC", ctypes.CFUNCTYPE(
        ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
        ctypes.c_size_t, ctypes.c_ssize_t))
    return ws.WindowsSnap(HWND, lambda: False), user32


def _writes_to(user32, index):
    return [call for call in user32.SetWindowLongPtrW.calls if call[1] == index]


def test_install_swaps_the_wndproc_and_then_restyles_the_window(monkeypatch):
    snap, user32 = _snap(monkeypatch)

    assert snap.install() is True
    assert snap._orig_wndproc == ORIGINAL_WNDPROC
    assert snap._wndproc_cb is not None, "the callback must be held, or Windows calls freed memory"
    assert _writes_to(user32, ws.GWLP_WNDPROC), "the window's handler is replaced"
    style_write = _writes_to(user32, ws.GWL_STYLE)[-1]
    assert style_write[2] & ws._SNAP_STYLES == ws._SNAP_STYLES, \
        "the snap styles are ORed onto the style the window already had"
    assert user32.SetWindowPos.calls, "the frame change has to be pushed to Windows"


def test_a_failed_wndproc_swap_leaves_the_window_exactly_as_it_was(monkeypatch):
    """install() used to restyle the window and record the original handler
    before the swap those depend on. When SetWindowLongPtrW failed the chrome
    threw the helper away, leaving a borderless window wearing snap styles and
    a dead helper claiming a handler it had never replaced."""
    snap, user32 = _snap(monkeypatch, wndproc_swap_fails=True)

    assert snap.install() is False
    assert snap._orig_wndproc is None
    assert snap._wndproc_cb is None
    assert _writes_to(user32, ws.GWL_STYLE) == [], "no style may be written before the swap lands"
    assert user32.SetWindowPos.calls == []


def test_shutdown_after_a_failed_install_restores_nothing(monkeypatch):
    """Nothing was hooked, so nothing may be unhooked: writing the recorded
    handler back would hand the window a stale procedure pointer."""
    snap, user32 = _snap(monkeypatch, wndproc_swap_fails=True)
    snap.install()
    user32.SetWindowLongPtrW.calls.clear()

    snap.shutdown()

    assert user32.SetWindowLongPtrW.calls == []


def test_shutdown_after_a_good_install_puts_the_original_handler_back(monkeypatch):
    snap, user32 = _snap(monkeypatch)
    snap.install()
    user32.SetWindowLongPtrW.calls.clear()

    snap.shutdown()

    assert user32.SetWindowLongPtrW.calls == [(HWND, ws.GWLP_WNDPROC, ORIGINAL_WNDPROC)]
    assert snap._orig_wndproc is None
    assert snap._wndproc_cb is None


def test_install_on_a_32_bit_host_touches_nothing(monkeypatch):
    """Without the 64-bit callback factory the helper cannot subclass anything,
    so it must refuse before it changes a single window style."""
    snap, user32 = _snap(monkeypatch)
    monkeypatch.setattr(ws, "_WNDPROC", None)

    assert snap.install() is False
    assert user32.SetWindowLongPtrW.calls == []
    assert user32.SetWindowPos.calls == []
