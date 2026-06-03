"""Universal game-info panel: info lines per mode + real result sources."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from unittest.mock import MagicMock

import pygame as pg
import pytest

from backend.match import BOT, ONLINE
from frontend.visual.colors import Colors


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
    "time_minutes, incr, tc",
    [
        pytest.param(5, 2, "5+2", id="with_clock"),
        pytest.param(None, 0, "∞", id="untimed_shows_infinity"),
    ],
)
def test_single_screen_info(time_minutes, incr, tc):
    """Local mode: a Local pill, the time control, round 1, no extra lines."""
    app = _make_app()
    _start_local(app, time_minutes=time_minutes, incr=incr)
    assert app._compute_game_info() == {
        "mode": "Local", "time_control": tc, "round": 1, "lines": [],
    }


def test_bot_mode_info():
    app = _make_app()
    app.mode = BOT
    app._time_control = (180, 0)
    assert app._compute_game_info() == {
        "mode": "Bot", "time_control": "3+0", "round": 1, "lines": [],
    }


def test_online_initial_series_zero_zero():
    """Online header carries the Online pill + TC + round; the scoreboard and
    live ping drop into the extra lines below."""
    app = _make_app()
    app.mode = ONLINE
    app.white_name = "Alice"
    app.black_name = "Bob"
    app._time_control = (180, 2)
    info = app._compute_game_info()
    assert info["mode"] == "Online"
    assert info["time_control"] == "3+2"
    assert info["lines"][0] == "Alice  0 – 0  Bob"
    assert info["lines"][1] == "ping: —"


@pytest.mark.parametrize(
    "white_score,black_score,expected",
    [
        pytest.param(0, 0, "Alice  0 – 0  Bob", id="zero_each"),
        pytest.param(1, 0, "Alice  1 – 0  Bob", id="one_nil"),
        pytest.param(1, 1, "Alice  1 – 1  Bob", id="one_all"),
        pytest.param(1.5, 0.5, "Alice  1½ – ½  Bob", id="one_half_vs_half"),
        pytest.param(2, 1.5, "Alice  2 – 1½  Bob", id="two_vs_one_half"),
        pytest.param(0.5, 0.5, "Alice  ½ – ½  Bob", id="half_each"),
    ],
)
def test_series_score_formatting(white_score, black_score, expected):
    app = _make_app()
    app.mode = ONLINE
    app.white_name = "Alice"
    app.black_name = "Bob"
    app._time_control = (60, 0)
    app._series_scores = {"Alice": white_score, "Bob": black_score}
    info = app._compute_game_info()
    assert info["lines"][0] == expected
    assert info["time_control"] == "1+0"


def test_series_seeded_from_server_scores():
    """The client adopts the server-authoritative series scores from the
    game_start payload, overwriting any stale local tally (so a reconnect can't
    desync the count)."""
    app = _make_app()
    app._series_pair = ("A", "C")
    app._series_scores = {"A": 2, "C": 1}
    app._start_online_game({
        "your_color": "white", "white_name": "A", "black_name": "B",
        "time_minutes": 3, "increment_seconds": 0,
        "white_score": 1.0, "black_score": 0.5,
    })
    assert app._series_scores == {"A": 1.0, "B": 0.5}
    assert app._series_pair == ("A", "B")


def test_series_seeded_keyed_by_player_through_color_swap():
    """Score is keyed by player identity: a rematch with swapped colors carries
    each player's server score onto the right name."""
    app = _make_app()
    app._start_online_game({
        "your_color": "black", "white_name": "B", "black_name": "A",
        "time_minutes": 3, "increment_seconds": 0,
        "white_score": 0.0, "black_score": 1.0,
    })
    assert app._series_scores == {"A": 1.0, "B": 0.0}
    assert app._compute_game_info()["lines"][0] == "B  0 – 1  A"


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
        "white_score": 0.0, "black_score": 1.0,
    })
    assert app._series_scores["Me"] == 1
    assert app._series_scores["Friend"] == 0.0
    assert app._compute_game_info()["lines"][0] == "Friend  0 – 1  Me"


@pytest.mark.parametrize("reason,winner,expected", [
    pytest.param("checkmate", "white", ("White wins", "by checkmate"), id="white_checkmate"),
    pytest.param("checkmate", "black", ("Black wins", "by checkmate"), id="black_checkmate"),
    pytest.param("timeout", "white", ("White wins", "on time"), id="white_timeout"),
    pytest.param("timeout", "black", ("Black wins", "on time"), id="black_timeout"),
    pytest.param("resignation", "white", ("White wins", "by resignation"), id="white_resign"),
    pytest.param("resignation", "black", ("Black wins", "by resignation"), id="black_resign"),
    pytest.param("abandonment", "white", ("White wins", "by abandonment"), id="white_abandon"),
    pytest.param("abandonment", "black", ("Black wins", "by abandonment"), id="black_abandon"),
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
    pytest.param("draw_agreement", ("Draw", "by agreement"), id="agreement"),
    pytest.param("draw_stalemate", ("Draw", "by agreement"), id="stalemate"),
    pytest.param("draw_repetition", ("Draw", "by agreement"), id="repetition"),
    pytest.param("draw_fifty_move", ("Draw", "by agreement"), id="fifty_move"),
    pytest.param("draw_insufficient_material", ("Draw", "by agreement"), id="insufficient"),
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


def test_single_screen_result_uses_winner_perspective_not_stale_local_color():
    """Bug: a stale local_color left over from a prior online game must not flip
    the single-screen result modal to the loser's clock / a DEFEAT word."""
    from backend.pieces import PieceColor
    app = _make_app()
    _start_local(app)
    app.match.local_color = PieceColor.BLACK
    assert app._result_subject_color("white_wins_by_resignation") == PieceColor.WHITE
    assert app._outcome_word_intent("white_wins_by_resignation", "White wins") \
        == ("White wins".upper(), "win")
    assert app._result_subject_color("black_wins") == PieceColor.BLACK


def test_single_screen_start_resets_local_color():
    from backend.pieces import PieceColor
    app = _make_app()
    app.match.local_color = PieceColor.WHITE
    _start_local(app)
    assert app.match.local_color is None


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
    "result_tag, shown",
    [
        pytest.param("1-0", "1-0", id="result_tag"),
        pytest.param(None, "*", id="star_fallback"),
    ],
)
def test_pgn_review_info(result_tag, shown):
    """PGN review shows a Review pill + TC and surfaces the result tag (or "*"
    fallback) as the single extra line."""
    app = _make_app()
    _start_local(app)
    app._pgn_result_tag = result_tag
    app.pgn_review = True
    assert app._compute_game_info() == {
        "mode": "Review", "time_control": "5+2", "round": 1, "lines": [shown],
    }


def test_pgn_review_inline_result_suppresses_modal():
    app = _make_app()
    _start_local(app)
    app.manual_result = "white_wins"
    app.pgn_review = True
    app._update_result_pending()
    assert app._result_first_seen_at_ms is None


def test_menu_mode_returns_no_info():
    app = _make_app()
    assert app.mode == "menu"
    assert app._compute_game_info() is None


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
    assert app._compute_game_info()["lines"][1] == expected_line


def _info_menu():
    from frontend.panels.right import RightMenu
    from backend.backend import Backend
    rm = RightMenu(pg.display.get_surface(), Backend(), {})
    rm.set_rect(pg.Rect(0, 0, 320, 640))
    return rm


def test_right_menu_header_reserves_space_for_info():
    rm = _info_menu()
    rm.set_game_info({"mode": "Local", "time_control": "5+2", "round": 1, "lines": []})
    assert rm.info_rect.height > 0


def test_right_menu_extra_lines_grow_info_height():
    rm = _info_menu()
    rm.set_game_info({"mode": "Local", "time_control": "5+2", "round": 1, "lines": []})
    bare = rm.info_rect.height
    rm.set_game_info({"mode": "Online", "time_control": "5+2", "round": 1,
                      "lines": ["A 0 - 0 B", "ping: —"]})
    assert rm.info_rect.height > bare


def test_right_menu_no_info_collapses_section():
    rm = _info_menu()
    rm.set_game_info(None)
    assert rm.info_rect.height == 0


def test_right_menu_mode_pill_draws_amber(monkeypatch):
    rm = _info_menu()
    rm.set_game_info({"mode": "Local", "time_control": "5+2", "round": 2, "lines": []})
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    rm.draw_menu()
    want = pg.Color(Colors.amber_hi)
    found = any(
        abs(win.get_at((x, y)).r - want.r) <= 30
        and win.get_at((x, y)).g > 120 and win.get_at((x, y)).b < 130
        for x in range(rm.info_rect.x, rm.info_rect.right, 2)
        for y in range(rm.info_rect.y, rm.info_rect.y + 24)
    )
    assert found, "mode pill text should render in amber"
