"""Universal game-info panel: info lines per mode + real result sources."""

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


@pytest.mark.parametrize(
    "time_minutes, incr, expected",
    [
        pytest.param(5, 2, ["Local game", "5+2"], id="with_clock"),
        pytest.param(None, 0, ["Local game", "no clock"], id="no_clock"),
    ],
)
def test_single_screen_lines(time_minutes, incr, expected):
    """Local mode has no series concept, so row 2 is just the time control."""
    app = _make_app()
    _start_local(app, time_minutes=time_minutes, incr=incr)
    assert app._compute_game_info_lines() == expected


def test_bot_mode_lines():
    app = _make_app()
    app.mode = BOT
    app._time_control = (180, 0)
    assert app._compute_game_info_lines() == ["vs Bot (preview)", "3+0"]


def test_online_initial_series_zero_zero():
    """Online line 1 packs names + score in board-color order, line 2 is
    bare time control, line 3 is live ping."""
    app = _make_app()
    app.mode = ONLINE
    app.white_name = "Alice"
    app.black_name = "Bob"
    app._time_control = (180, 2)
    lines = app._compute_game_info_lines()
    assert lines[0] == "Alice  0 - 0  Bob"
    assert lines[1] == "3+2"
    assert lines[2] == "ping: —"


@pytest.mark.parametrize(
    "white_score,black_score,expected",
    [
        (0, 0, "Alice  0 - 0  Bob"),
        (1, 0, "Alice  1 - 0  Bob"),
        (1, 1, "Alice  1 - 1  Bob"),
        (1.5, 0.5, "Alice  1½ - ½  Bob"),
        (2, 1.5, "Alice  2 - 1½  Bob"),
        (0.5, 0.5, "Alice  ½ - ½  Bob"),
    ],
)
def test_series_score_formatting(white_score, black_score, expected):
    app = _make_app()
    app.mode = ONLINE
    app.white_name = "Alice"
    app.black_name = "Bob"
    app._time_control = (60, 0)
    app._series_scores = {"Alice": white_score, "Bob": black_score}
    lines = app._compute_game_info_lines()
    assert lines[0] == expected
    assert lines[1] == "1+0"


def test_series_resets_when_opponent_pair_changes():
    app = _make_app()
    app._series_pair = ("A", "C")
    app._series_scores = {"A": 2, "C": 1}
    app._start_online_game({
        "your_color": "white", "white_name": "A", "black_name": "B",
        "time_minutes": 3, "increment_seconds": 0,
    })
    assert app._series_scores == {"A": 0.0, "B": 0.0}
    assert app._series_pair == ("A", "B")


def test_series_persists_across_rematch_with_color_swap():
    """Bug 3 regression: score is keyed by player identity, so a rematch with
    swapped colors keeps the same number attached to each player."""
    app = _make_app()
    app._series_pair = tuple(sorted(["A", "B"]))
    app._series_scores = {"A": 1, "B": 0}
    app._start_online_game({
        "your_color": "black", "white_name": "B", "black_name": "A",
        "time_minutes": 3, "increment_seconds": 0,
    })
    assert app._series_scores == {"A": 1, "B": 0}
    lines = app._compute_game_info_lines()
    assert lines[0] == "B  0 - 1  A"


@pytest.mark.parametrize(
    "winner_color, expected_scores",
    [
        pytest.param("white", {"Alice": 1, "Bob": 0.0}, id="white_win"),
        pytest.param("black", {"Alice": 0.0, "Bob": 1}, id="black_win"),
    ],
)
def test_series_increments_on_win(winner_color, expected_scores):
    app = _make_app()
    app.mode = ONLINE
    app.white_name = "Alice"
    app.black_name = "Bob"
    app._series_pair = ("Alice", "Bob")
    app._series_scores = {"Alice": 0.0, "Bob": 0.0}
    app._handle_online_result({"reason": "checkmate", "winner_color": winner_color})
    assert app._series_scores == expected_scores


def test_series_increments_on_draw():
    app = _make_app()
    app.mode = ONLINE
    app.white_name = "Alice"
    app.black_name = "Bob"
    app._series_pair = ("Alice", "Bob")
    app._series_scores = {"Alice": 0.0, "Bob": 0.0}
    app._handle_online_result({"reason": "draw_repetition"})
    assert app._series_scores == {"Alice": 0.5, "Bob": 0.5}


def test_aborted_does_not_change_series():
    app = _make_app()
    app.mode = ONLINE
    app.white_name = "Alice"
    app.black_name = "Bob"
    app._series_pair = ("Alice", "Bob")
    app._series_scores = {"Alice": 1, "Bob": 0}
    app._handle_online_result({"reason": "aborted"})
    assert app._series_scores == {"Alice": 1, "Bob": 0}


def test_score_follows_player_through_color_swap_end_to_end():
    """Two games, same opponent. Game 1: I play white and win. Game 2: I play
    black. My nickname's score stays 1 regardless of the color I hold."""
    app = _make_app()
    app._start_online_game({
        "your_color": "white", "white_name": "Me", "black_name": "Friend",
        "time_minutes": 3, "increment_seconds": 0,
    })
    app._handle_online_result({"reason": "checkmate", "winner_color": "white"})
    assert app._series_scores["Me"] == 1
    assert app._series_scores["Friend"] == 0.0
    app._start_online_game({
        "your_color": "black", "white_name": "Friend", "black_name": "Me",
        "time_minutes": 3, "increment_seconds": 0,
    })
    assert app._series_scores["Me"] == 1
    assert app._series_scores["Friend"] == 0.0
    lines = app._compute_game_info_lines()
    assert lines[0] == "Friend  0 - 1  Me"


@pytest.mark.parametrize("reason,winner,expected", [
    ("checkmate",    "white", ("White wins", "by checkmate")),
    ("checkmate",    "black", ("Black wins", "by checkmate")),
    ("timeout",      "white", ("White wins", "on time")),
    ("timeout",      "black", ("Black wins", "on time")),
    ("resignation",  "white", ("White wins", "by resignation")),
    ("resignation",  "black", ("Black wins", "by resignation")),
    ("abandonment",  "white", ("White wins", "by abandonment")),
    ("abandonment",  "black", ("Black wins", "by abandonment")),
])
def test_online_win_result_subtitle_reports_actual_reason(reason, winner, expected):
    """Bug 4: every online win used to render "by resignation" because
    _handle_online_result flattened all win reasons to bare white_wins."""
    app = _make_app()
    app.mode = ONLINE
    app.white_name = "Alice"
    app.black_name = "Bob"
    app._series_pair = ("Alice", "Bob")
    app._series_scores = {"Alice": 0.0, "Bob": 0.0}
    app._handle_online_result({"reason": reason, "winner_color": winner})
    assert app.result_text() == expected


@pytest.mark.parametrize("draw_reason,expected", [
    ("draw_agreement",             ("Draw", "by agreement")),
    ("draw_stalemate",             ("Draw", "by agreement")),
    ("draw_repetition",            ("Draw", "by agreement")),
    ("draw_fifty_move",            ("Draw", "by agreement")),
    ("draw_insufficient_material", ("Draw", "by agreement")),
])
def test_online_draw_result_subtitle(draw_reason, expected):
    """All online draws are flattened to manual_result="draw_agreement" by the
    existing handler; subtitle reflects that."""
    app = _make_app()
    app.mode = ONLINE
    app.white_name = "Alice"
    app.black_name = "Bob"
    app._series_pair = ("Alice", "Bob")
    app._series_scores = {"Alice": 0.0, "Bob": 0.0}
    app._handle_online_result({"reason": draw_reason})
    assert app.result_text() == expected


def test_local_resignation_subtitle_reports_resignation():
    """Local resignation path uses the compound code so it never mislabels as
    "by checkmate"."""
    app = _make_app()
    _start_local(app)
    app._perform_resign()
    assert app.result_text() == ("Black wins", "by resignation")


@pytest.mark.parametrize(
    "engine_result, expected",
    [
        pytest.param("white_wins", ("White wins", "by checkmate"), id="checkmate"),
        pytest.param("white_wins_on_time", ("White wins", "on time"), id="flag_fall"),
    ],
)
def test_engine_result_subtitle_reports_actual_reason(engine_result, expected):
    """Bare white_wins / black_wins in RESULT_TEXT means checkmate (the only way
    the engine produces them); compound codes carry the explicit reason."""
    app = _make_app()
    _start_local(app)
    app.match.backend.game_result = lambda: engine_result
    assert app.result_text() == expected


@pytest.mark.parametrize(
    "result_tag, expected",
    [
        pytest.param("1-0", ["Review", "1-0  ·  5+2"], id="result_tag"),
        pytest.param(None, ["Review", "*  ·  5+2"], id="star_fallback"),
    ],
)
def test_pgn_review_lines(result_tag, expected):
    """PGN review treats the result tag (or "*" fallback) as the "count",
    combined with TC on the same row, mirroring the online "score · TC" layout."""
    app = _make_app()
    _start_local(app)
    app._pgn_result_tag = result_tag
    app.pgn_review = True
    assert app._compute_game_info_lines() == expected


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


@pytest.mark.parametrize(
    "ping_value, expected_line",
    [
        pytest.param(42, "ping: 42 ms", id="has_samples"),
        pytest.param(None, "ping: —", id="no_samples"),
    ],
)
def test_online_ping_line(ping_value, expected_line):
    app = _make_app()
    app.mode = ONLINE
    app.white_name = "A"
    app.black_name = "B"
    app._time_control = (60, 0)
    fake = MagicMock()
    fake.get_ping_ms.return_value = ping_value
    app.online_client = fake
    lines = app._compute_game_info_lines()
    assert lines[2] == expected_line


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
    assert rm._info_lines() == ["A  vs  B", "3 min + 2 sec", "ping: 50 ms"]


def test_right_menu_no_info_when_none():
    from frontend.panels.right import RightMenu
    from backend.backend import Backend
    rm = RightMenu(pg.display.get_surface(), Backend(), {})
    rm.set_rect(pg.Rect(0, 0, 300, 600))
    rm.set_game_info(None)
    assert rm._info_lines() == []
