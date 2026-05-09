"""Universal game-info panel (M14): info lines per mode + real result sources."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from unittest.mock import MagicMock

import pygame as pg
import pytest

from backend.match import BOT, ONLINE


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def _make_app():
    from frontend.frontend import Frontend
    app = Frontend(1000, 800)
    app.sound_manager = MagicMock()
    return app


def _start_local(app, time_minutes=5, incr=2):
    app._on_start_game({
        "mode": "single_screen", "nickname": "a",
        "time_minutes": time_minutes, "increment_seconds": incr,
        "side": "white",
    })


# ---------- single-screen ----------

def test_single_screen_lines():
    # Row 2 carries both move count and game time in the new shared layout —
    # same convention across local / bot / online / pgn-review.
    app = _make_app()
    _start_local(app)
    lines = app._compute_game_info_lines()
    assert lines == ["Local game", "Move 1  ·  5+2"]


def test_single_screen_no_clock_lines():
    # No time control still occupies the row — collapsed to "no clock" so
    # the layout stays a stable two-column "<count> · <time>" shape.
    app = _make_app()
    _start_local(app, time_minutes=None, incr=0)
    lines = app._compute_game_info_lines()
    assert lines == ["Local game", "Move 1  ·  no clock"]


# ---------- bot mode ----------

def test_bot_mode_lines():
    app = _make_app()
    app.mode = BOT
    app._time_control = (180, 0)
    lines = app._compute_game_info_lines()
    assert lines[0] == "vs Bot (preview)"
    assert lines[1] == "Move 1  ·  3+0"


# ---------- online mode (series score) ----------

def test_online_initial_series_zero_zero():
    app = _make_app()
    app.mode = ONLINE
    app.white_name = "Alice"
    app.black_name = "Bob"
    app._time_control = (180, 2)
    lines = app._compute_game_info_lines()
    assert lines[0] == "Alice  vs  Bob"
    assert lines[1] == "Move 1  ·  3+2"
    assert lines[2] == "0 - 0"
    # Online gets a fourth line for the live ping; with no client attached
    # yet we render the "—" placeholder.
    assert lines[3] == "ping: —"


@pytest.mark.parametrize(
    "white_score,black_score,expected",
    [
        (0, 0, "0 - 0"),
        (1, 0, "1 - 0"),
        (1, 1, "1 - 1"),
        (1.5, 0.5, "1½ - ½"),
        (2, 1.5, "2 - 1½"),
        (0.5, 0.5, "½ - ½"),
    ],
)
def test_series_score_formatting(white_score, black_score, expected):
    app = _make_app()
    app.mode = ONLINE
    app.white_name = "A"
    app.black_name = "B"
    app._time_control = (60, 0)
    app._series_white_score = white_score
    app._series_black_score = black_score
    lines = app._compute_game_info_lines()
    assert lines[2] == expected


def test_series_resets_when_opponent_pair_changes():
    app = _make_app()
    app._series_pair = ("A", "C")
    app._series_white_score = 2
    app._series_black_score = 1
    app._start_online_game({
        "your_color": "white", "white_name": "A", "black_name": "B",
        "time_minutes": 3, "increment_seconds": 0,
    })
    assert app._series_white_score == 0
    assert app._series_black_score == 0
    assert app._series_pair == ("A", "B")


def test_series_persists_across_rematch_with_same_pair():
    app = _make_app()
    app._series_pair = tuple(sorted(["A", "B"]))
    app._series_white_score = 1
    app._series_black_score = 0
    # Rematch with the same pair (colors swapped, but pair is sorted-tuple).
    app._start_online_game({
        "your_color": "black", "white_name": "B", "black_name": "A",
        "time_minutes": 3, "increment_seconds": 0,
    })
    assert app._series_white_score == 1
    assert app._series_black_score == 0


def test_series_increments_on_white_win():
    app = _make_app()
    app.mode = ONLINE
    app._series_pair = ("A", "B")
    app._series_white_score = 0
    app._series_black_score = 0
    app._handle_online_result({"reason": "checkmate", "winner_color": "white"})
    assert app._series_white_score == 1
    assert app._series_black_score == 0


def test_series_increments_on_draw():
    app = _make_app()
    app.mode = ONLINE
    app._series_pair = ("A", "B")
    app._series_white_score = 0
    app._series_black_score = 0
    app._handle_online_result({"reason": "draw_repetition"})
    assert app._series_white_score == 0.5
    assert app._series_black_score == 0.5


def test_aborted_does_not_change_series():
    app = _make_app()
    app.mode = ONLINE
    app._series_pair = ("A", "B")
    app._series_white_score = 1
    app._series_black_score = 0
    app._handle_online_result({"reason": "aborted"})
    assert app._series_white_score == 1
    assert app._series_black_score == 0


# ---------- pgn review ----------

def test_pgn_review_uses_pgn_result_tag():
    app = _make_app()
    _start_local(app)
    app._pgn_result_tag = "1-0"
    app.pgn_review = True
    lines = app._compute_game_info_lines()
    assert "1-0" in lines


def test_pgn_review_falls_back_to_star_when_no_tag():
    app = _make_app()
    _start_local(app)
    app._pgn_result_tag = None
    app.pgn_review = True
    lines = app._compute_game_info_lines()
    assert "*" in lines


def test_pgn_review_inline_result_suppresses_modal():
    app = _make_app()
    _start_local(app)
    app.manual_result = "white_wins"
    app.pgn_review = True
    app._update_result_pending()
    assert app._result_first_seen_at_ms is None


def test_menu_mode_returns_no_lines():
    app = _make_app()
    assert app.mode == "menu"
    assert app._compute_game_info_lines() is None


# ---------- move count advances after each ply ----------

def test_move_count_advances_after_each_ply():
    # ply 0 → Move 1 (white about to play move 1)
    # ply 1 → Move 1 (black about to reply on move 1)
    # ply 2 → Move 2 (white about to play move 2), etc.
    from backend.utils import Square
    app = _make_app()
    _start_local(app)
    assert "Move 1  ·" in app._compute_game_info_lines()[1]
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    app.board.cancel_animations()
    assert "Move 1  ·" in app._compute_game_info_lines()[1]
    app.board.handle_click(Square(1, 4))
    app.board.handle_click(Square(3, 4))
    app.board.cancel_animations()
    assert "Move 2  ·" in app._compute_game_info_lines()[1]


def test_pgn_review_uses_review_ply_for_count():
    # In PGN review, the count reflects the position currently shown, not the
    # full game length.
    from backend.utils import Square
    app = _make_app()
    _start_local(app)
    for fr, to in [(Square(6, 4), Square(4, 4)),
                   (Square(1, 4), Square(3, 4)),
                   (Square(7, 6), Square(5, 5))]:
        app.board.handle_click(fr)
        app.board.handle_click(to)
        app.board.cancel_animations()
    app.pgn_review = True
    app.board.review_ply = 1
    assert "Move 1  ·" in app._compute_game_info_lines()[1]
    app.board.review_ply = 2
    assert "Move 2  ·" in app._compute_game_info_lines()[1]


# ---------- online ping line ----------

def test_online_ping_line_shows_value_when_client_has_samples():
    app = _make_app()
    app.mode = ONLINE
    app.white_name = "A"
    app.black_name = "B"
    app._time_control = (60, 0)
    fake = MagicMock()
    fake.get_ping_ms.return_value = 42
    app.online_client = fake
    lines = app._compute_game_info_lines()
    assert lines[3] == "ping: 42 ms"


def test_online_ping_line_dash_when_no_samples():
    app = _make_app()
    app.mode = ONLINE
    app.white_name = "A"
    app.black_name = "B"
    app._time_control = (60, 0)
    fake = MagicMock()
    fake.get_ping_ms.return_value = None
    app.online_client = fake
    lines = app._compute_game_info_lines()
    assert lines[3] == "ping: —"


# ---------- right_menu set_game_info accepts list ----------

def test_right_menu_accepts_list_of_lines():
    from frontend.panels.right import RightMenu
    from backend.backend import Backend
    rm = RightMenu(pg.display.get_surface(), Backend(), {})
    rm.set_rect(pg.Rect(0, 0, 300, 600))
    rm.set_game_info(["First", "Second", "Third"])
    assert rm._info_lines() == ["First", "Second", "Third"]


def test_right_menu_accepts_legacy_dict():
    from frontend.panels.right import RightMenu
    from backend.backend import Backend
    rm = RightMenu(pg.display.get_surface(), Backend(), {})
    rm.set_rect(pg.Rect(0, 0, 300, 600))
    rm.set_game_info({
        "white_name": "A", "black_name": "B",
        "time_minutes": 3, "increment_seconds": 2, "ping_ms": 50,
    })
    lines = rm._info_lines()
    assert "A" in lines[0] and "B" in lines[0]
    assert "3" in lines[1] and "2" in lines[1]
    assert "50" in lines[2]


def test_right_menu_no_info_when_none():
    from frontend.panels.right import RightMenu
    from backend.backend import Backend
    rm = RightMenu(pg.display.get_surface(), Backend(), {})
    rm.set_rect(pg.Rect(0, 0, 300, 600))
    rm.set_game_info(None)
    assert rm._info_lines() == []
