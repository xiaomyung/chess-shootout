"""Temporary Windows resize diagnostic (v2.4.3). Delete before merge.

Run on the Windows VM from the repo root:
    python tools/win_resize_diag.py          # baseline: NOFRAME|RESIZABLE only
    python tools/win_resize_diag.py snap      # with the win_snap WndProc subclass

Then resize the window by dragging an edge, and maximize it (drag to top). Copy
the console output back. It answers:
  * is WS_THICKFRAME on the window (can Windows resize it)?
  * does win_snap.install() succeed?
  * does pg.VIDEORESIZE fire on resize?
  * does pg.display.get_window_size() track the new size, or stay stale?
  * does the render surface follow?
An orange border is drawn at the surface edge so you can see the surface bounds
versus the actual window.
"""
import ctypes
import os
import sys

import pygame as pg

GWL_STYLE = -16
WS_THICKFRAME = 0x00040000
WS_MAXIMIZEBOX = 0x00010000


def probe_style(tag):
    if os.name != "nt":
        print(f"[{tag}] not Windows; skipping style probe")
        return
    try:
        hwnd = pg.display.get_wm_info().get("window")
        u = ctypes.windll.user32
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        style = u.GetWindowLongPtrW(hwnd, GWL_STYLE) & 0xFFFFFFFF
        print(f"[{tag}] hwnd={hwnd} style=0x{style:08x} "
              f"THICKFRAME={'YES' if style & WS_THICKFRAME else 'no'} "
              f"MAXBOX={'YES' if style & WS_MAXIMIZEBOX else 'no'}")
    except Exception as exc:
        print(f"[{tag}] style probe failed: {exc}")


def main():
    use_snap = "snap" in sys.argv[1:]
    pg.init()
    win = pg.display.set_mode((900, 600), pg.NOFRAME | pg.RESIZABLE)
    pg.display.set_caption("resize diag")
    probe_style("before")

    snap = None
    if use_snap:
        try:
            from chessshootout.frontend.win_snap import WindowsSnap
            hwnd = pg.display.get_wm_info().get("window")
            snap = WindowsSnap(hwnd, lambda: False)
            print("[snap] install ->", snap.install())
            probe_style("after-snap")
        except Exception as exc:
            print("[snap] import/install failed:", exc)

    print(f"[init] mode={'snap' if use_snap else 'baseline'} "
          f"get_window_size={pg.display.get_window_size()} surface={win.get_size()}")
    print(">>> Drag an edge to resize, and maximize (drag to top). Close the window to quit.")

    win_events = {}
    for name in ("WINDOWRESIZED", "WINDOWSIZECHANGED", "WINDOWMAXIMIZED",
                 "WINDOWRESTORED", "WINDOWMINIMIZED"):
        if hasattr(pg, name):
            win_events[getattr(pg, name)] = name

    clock = pg.time.Clock()
    last_poll = None
    running = True
    while running:
        for ev in pg.event.get():
            if ev.type == pg.QUIT:
                running = False
            elif ev.type == pg.VIDEORESIZE:
                print(f"[VIDEORESIZE] event=({ev.w},{ev.h}) "
                      f"get_window_size={pg.display.get_window_size()} "
                      f"surface={pg.display.get_surface().get_size()}")
            elif ev.type in win_events:
                print(f"[{win_events[ev.type]}] "
                      f"get_window_size={pg.display.get_window_size()} "
                      f"surface={pg.display.get_surface().get_size()}")
        cur = pg.display.get_window_size()
        if cur != last_poll:
            print(f"[poll] get_window_size={cur} surface={pg.display.get_surface().get_size()} "
                  f"snap.maximized={getattr(snap, 'maximized', None)}")
            last_poll = cur
        surf = pg.display.get_surface()
        surf.fill((20, 20, 30))
        pg.draw.rect(surf, (230, 120, 40), surf.get_rect(), 6)
        pg.display.flip()
        clock.tick(30)
    if snap is not None:
        snap.shutdown()
    pg.quit()


if __name__ == "__main__":
    main()
