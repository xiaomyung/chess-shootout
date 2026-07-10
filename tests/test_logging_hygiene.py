"""Logging hygiene guards for the v2.7.0 logging pass.

Two runtime checks (a live idle game must not emit any log record per frame,
and a finished game's result must log exactly once no matter how many more
frames render while the result screen is up) plus two static checks (no log
call literally sits inside a known per-frame draw/update function, and no log
call anywhere references a skill-check secret or geometry seed).
"""
import logging
import os
import re

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from tests.focus_helpers import FakeClock, install_clock, make_app, start_game


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_ROOT = os.path.join(REPO_ROOT, "chessshootout")

LOG_CALL_RE = re.compile(r"\blog\.(debug|info|warning|error|exception|critical)\(")

STEADY_STATE_LOG_CALL_RE = re.compile(r"\blog\.(debug|info|warning|error|critical)\(")
"""Excludes log.exception: it can only run inside an active `except` clause,
so unlike the other levels it structurally cannot fire every steady-state
frame — a per-frame function is allowed a guarded error-path log.exception."""

FRAME_FUNCTIONS = {
    "chessshootout/frontend/frontend.py": ["draw_frame"],
    "chessshootout/frontend/board/board.py": ["draw_board", "update_drag_physics"],
    "chessshootout/frontend/result_flow.py": ["_update_result_pending"],
    "chessshootout/frontend/give_time.py": ["_update_give_time_hold"],
}


@pytest.fixture(scope="module", autouse=True)
def _pg():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


class _CaptureHandler(logging.Handler):

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def capture_chess_logs():
    handler = _CaptureHandler()
    root = logging.getLogger()
    saved_level = root.level
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    yield handler
    root.removeHandler(handler)
    root.setLevel(saved_level)


def _chess_records(handler):
    return [r for r in handler.records if r.name.startswith("chess.")]


def test_idle_draw_frame_emits_no_log_records(monkeypatch, capture_chess_logs):
    """A live game with no player input must not log per frame — game start
    already logged before the capture window opens, so anything captured here
    would be a genuine per-frame leak."""
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    app = start_game(make_app())
    capture_chess_logs.records.clear()
    for _ in range(120):
        clock.advance(16)
        app.draw_frame()
    offenders = _chess_records(capture_chess_logs)
    assert offenders == [], "draw_frame must not log per frame: " + "; ".join(
        f"{r.name}:{r.getMessage()}" for r in offenders)


def test_finished_game_result_final_logs_exactly_once_across_many_frames(
        monkeypatch, capture_chess_logs):
    """The result screen stays on screen for many frames after a resign;
    _on_result_final is re-entered every one of those frames via
    _update_result_pending, so its own log line must be guarded to fire once."""
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    app = start_game(make_app())
    capture_chess_logs.records.clear()
    app._perform_resign()
    for _ in range(120):
        clock.advance(16)
        app.draw_frame()
    game_end_lines = [r for r in _chess_records(capture_chess_logs)
                      if r.getMessage().startswith("game end result=")]
    assert len(game_end_lines) == 1, (
        f"expected exactly one game-end breadcrumb, got {len(game_end_lines)}")


def _slice_function(path, name):
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    start = None
    def_indent = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"def {name}(") or stripped.startswith(f"async def {name}("):
            start = i
            def_indent = len(line) - len(line.lstrip())
            break
    assert start is not None, f"{name} not found in {path}"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        line = lines[j]
        stripped = line.strip()
        if not stripped:
            continue
        cur_indent = len(line) - len(line.lstrip())
        if cur_indent <= def_indent:
            end = j
            break
    return "".join(lines[start:end])


def test_no_log_calls_in_known_per_frame_functions():
    """Static tripwire: a future PR pasting a debug log directly into
    draw_frame/draw_board/etc. fails here even before it ships a runtime leak."""
    offenders = []
    for rel_path, names in FRAME_FUNCTIONS.items():
        full = os.path.join(REPO_ROOT, rel_path)
        for name in names:
            body = _slice_function(full, name)
            if STEADY_STATE_LOG_CALL_RE.search(body):
                offenders.append(f"{rel_path}:{name}")
    assert offenders == [], f"per-frame functions must not log directly: {offenders}"


def _log_call_spans(text):
    spans = []
    for m in LOG_CALL_RE.finditer(text):
        i = m.end() - 1
        depth = 0
        while i < len(text):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        spans.append(text[m.start():i + 1])
    return spans


def test_no_secret_or_seed_in_any_log_call():
    """The skill-check `room.skillcheck_secret` (which-fires selector) and the
    per-check geometry `seed` must never be logged, on either side."""
    offenders = []
    for dirpath, _, filenames in os.walk(PACKAGE_ROOT):
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            for span in _log_call_spans(text):
                if re.search(r"secret|seed", span, re.IGNORECASE):
                    offenders.append(f"{os.path.relpath(path, REPO_ROOT)}: {span.splitlines()[0]}")
    assert offenders == [], f"log calls must never reference secret/seed: {offenders}"
