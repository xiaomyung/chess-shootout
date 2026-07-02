"""Bug 4 (v2.4.1): the taskbar-aware maximize geometry is a pure function so it can
be unit-tested on any host; the Win32 WndProc plumbing itself is exercised only on
Windows (the user's VM). Also pins that the module imports cleanly off-Windows."""
import os

import pytest

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
    import chessshootout.frontend.win_snap as ws
    if os.name != "nt":
        assert ws._WNDPROC is None, "the WndProc factory is Windows-only"
