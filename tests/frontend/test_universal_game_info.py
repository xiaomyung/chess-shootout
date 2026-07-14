"""Universal game-info panel: info lines per mode + real result sources."""

from unittest.mock import MagicMock

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.domain.match import ONLINE
from chessshootout.frontend.visual.colors import Colors
from tests.helpers import make_app as _make_app_at


_pygame_init = pygame_display(1000, 800)


def _make_app():
    return _make_app_at(1000, 800)


def _start_local(app, time_minutes=5, incr=2):
    app._on_start_game({
        "mode": "single_screen", "nickname": "a",
        "time_minutes": time_minutes, "increment_seconds": incr,
        "side": "white",
    })


def test_current_result_reacts_to_clock_flag():
    """A flagged clock must end the game even though a timeout changes neither
    move_history length nor manual_result. current_result() is memoized, so its
    cache key has to include the clock flag or the game never ends (v2.5.0 bug)."""
    from chessshootout.backend.pieces import PieceColor
    app = _make_app()
    _start_local(app, time_minutes=5, incr=2)
    assert app.game.current_result() is None
    app.game.match.clock.flagged = PieceColor.BLACK
    assert app.game.current_result() == "white_wins_on_time"
    app.game.match.clock.flagged = PieceColor.WHITE
    assert app.game.current_result() == "black_wins_on_time"


def test_chrome_stats_readouts_follow_toggles():
    from chessshootout.infra import env
    app = _make_app()
    _start_local(app)
    for v in [3.0, 3.2, 5.0, 3.0, 3.1] * 24:
        app._frame_times.append(v)
    app._last_work_ms = 2.4
    env.set_show_fps(True)
    env.set_show_ping(False)
    env.set_show_frame_stats(True)
    env.set_show_1pct_low(True)
    env.set_show_frametime(True)
    parts = app._chrome_stats()
    assert any(p.startswith("FPS ") for p in parts)
    assert any(p.startswith("AVG ") for p in parts)
    assert any(p.startswith("MIN ") for p in parts)
    assert any(p.startswith("1%LOW ") for p in parts)
    assert any(p.startswith("FRAME ") and p.rstrip().endswith("ms") for p in parts)

    env.set_show_frame_stats(False)
    env.set_show_1pct_low(False)
    env.set_show_frametime(False)
    recent = list(app._frame_times)[-10:]
    expected_fps = 1000.0 / (sum(recent) / len(recent))
    from chessshootout.frontend.frontend import STAT_SLOT_FPS, _stat_slot
    assert app._chrome_stats() == [_stat_slot("FPS", int(expected_fps), STAT_SLOT_FPS)]


def test_chrome_stats_value_fields_are_fixed_width():
    from chessshootout.infra import env
    app = _make_app()
    _start_local(app)
    env.set_show_fps(True)
    env.set_show_frame_stats(True)
    env.set_show_1pct_low(True)
    env.set_show_frametime(True)
    env.set_show_ping(True)

    def stats_for(fps_frames, frame_ms, ping):
        app._frame_times.clear()
        app._frame_times.extend(fps_frames)
        app._last_work_ms = frame_ms
        app.coordinator.ping_ms = lambda: ping
        return app._chrome_stats()

    narrow = stats_for([1000.0 / 9] * 120, 9.4, None)
    wide = stats_for([1000.0 / 999] * 120, 10.5, 12)
    widest = stats_for([1000.0 / 999] * 120, 100.5, 999)
    by_label = {p.split(" ", 1)[0]: len(p) for p in narrow}
    for stats in (wide, widest):
        for p in stats:
            label = p.split(" ", 1)[0]
            assert len(p) == by_label[label]


def test_current_result_recomputes_when_position_changes_at_same_length(monkeypatch):
    """The memo key must track the actual position, not just move count. An undo
    followed by a different move returns to the same length but a different
    position (e.g. an online takeback + replacement) and must re-evaluate."""
    from chessshootout.backend.utils import Square
    app = _make_app()
    _start_local(app, time_minutes=None, incr=0)
    backend = app.game.match.backend
    calls = []
    real = backend.game_result
    monkeypatch.setattr(backend, "game_result",
                        lambda: (calls.append(1), real())[1])
    backend.try_move(Square(6, 4), Square(4, 4))
    app.game.current_result()
    backend.undo()
    backend.try_move(Square(6, 3), Square(4, 3))
    before = len(calls)
    app.game.current_result()
    assert len(calls) > before


def test_current_result_memo_resets_on_new_game():
    """A flagged/finished game must not leak its cached result into the next."""
    from chessshootout.backend.pieces import PieceColor
    app = _make_app()
    _start_local(app, time_minutes=5, incr=2)
    app.game.match.clock.flagged = PieceColor.WHITE
    assert app.game.current_result() == "black_wins_on_time"
    _start_local(app, time_minutes=5, incr=2)
    assert app.game.current_result() is None


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
    assert app.game._compute_game_info() == {
        "mode": "Local", "time_control": tc, "round": 1, "lines": [],
    }


def test_bot_mode_info():
    app = _make_app()
    app.switch_to("game", variant="bot")
    app.game._time_control = (180, 0)
    assert app.game._compute_game_info() == {
        "mode": "Bot", "time_control": "3+0", "round": 1, "lines": [],
    }


def test_online_initial_series_zero_zero():
    """Online header carries the Online pill + TC + round; the scoreboard drops
    into the single extra line below (ping moved to the window chrome)."""
    app = _make_app()
    app.switch_to("game", variant=ONLINE)
    app.game.white_name = "Alice"
    app.game.black_name = "Bob"
    app.game._time_control = (180, 2)
    info = app.game._compute_game_info()
    assert info["mode"] == "Online"
    assert info["time_control"] == "3+2"
    assert info["lines"] == ["Alice  0 – 0  Bob"]


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
    app.switch_to("game", variant=ONLINE)
    app.game.white_name = "Alice"
    app.game.black_name = "Bob"
    app.game._time_control = (60, 0)
    app.game.result_flow.series_scores = {"Alice": white_score, "Bob": black_score}
    info = app.game._compute_game_info()
    assert info["lines"][0] == expected
    assert info["time_control"] == "1+0"


def test_series_seeded_from_server_scores():
    """The client adopts the server-authoritative series scores from the
    game_start payload, overwriting any stale local tally (so a reconnect can't
    desync the count)."""
    app = _make_app()
    app.game.result_flow.series_scores = {"A": 2, "C": 1}
    app.coordinator._start_online_game({
        "your_color": "white", "white_name": "A", "black_name": "B",
        "time_minutes": 3, "increment_seconds": 0,
        "white_score": 1.0, "black_score": 0.5,
    })
    assert app.game.result_flow.series_scores == {"A": 1.0, "B": 0.5}


def test_series_seeded_keyed_by_player_through_color_swap():
    """Score is keyed by player identity: a rematch with swapped colors carries
    each player's server score onto the right name."""
    app = _make_app()
    app.coordinator._start_online_game({
        "your_color": "black", "white_name": "B", "black_name": "A",
        "time_minutes": 3, "increment_seconds": 0,
        "white_score": 0.0, "black_score": 1.0,
    })
    assert app.game.result_flow.series_scores == {"A": 1.0, "B": 0.0}
    assert app.game._compute_game_info()["lines"][0] == "B  0 – 1  A"


@pytest.mark.parametrize(
    "winner_color, expected_scores",
    [
        pytest.param("white", {"Alice": 1, "Bob": 0.0}, id="white_win"),
        pytest.param("black", {"Alice": 0.0, "Bob": 1}, id="black_win"),
    ],
)
def test_series_increments_on_win(winner_color, expected_scores):
    app = _make_app()
    app.switch_to("game", variant=ONLINE)
    app.game.white_name = "Alice"
    app.game.black_name = "Bob"
    app.game.result_flow.series_scores = {"Alice": 0.0, "Bob": 0.0}
    app.coordinator._handle_online_result({"reason": "checkmate", "winner_color": winner_color})
    assert app.game.result_flow.series_scores == expected_scores


def test_series_increments_on_draw():
    app = _make_app()
    app.switch_to("game", variant=ONLINE)
    app.game.white_name = "Alice"
    app.game.black_name = "Bob"
    app.game.result_flow.series_scores = {"Alice": 0.0, "Bob": 0.0}
    app.coordinator._handle_online_result({"reason": "draw_repetition"})
    assert app.game.result_flow.series_scores == {"Alice": 0.5, "Bob": 0.5}


def test_aborted_does_not_change_series():
    app = _make_app()
    app.switch_to("game", variant=ONLINE)
    app.game.white_name = "Alice"
    app.game.black_name = "Bob"
    app.game.result_flow.series_scores = {"Alice": 1, "Bob": 0}
    app.coordinator._handle_online_result({"reason": "aborted"})
    assert app.game.result_flow.series_scores == {"Alice": 1, "Bob": 0}


def test_disconnect_abort_is_neutral_result_with_its_own_text():
    """A disconnect abort is a no-winner static result with a distinct modal subtitle and
    leaves the series score untouched."""
    app = _make_app()
    app.switch_to("game", variant=ONLINE)
    app.game.white_name = "Alice"
    app.game.black_name = "Bob"
    app.game.result_flow.series_scores = {"Alice": 1, "Bob": 0}
    app.coordinator._handle_online_result({"reason": "aborted_disconnect"})
    assert app.game.manual_result == "aborted_disconnect"
    assert app.game.result_flow.result_text() == ("Game aborted", "opponent disconnected")
    assert app.game.result_flow.series_scores == {"Alice": 1, "Bob": 0}


def test_score_follows_player_through_color_swap_end_to_end():
    """Two games, same opponent. Game 1: I play white and win. Game 2: I play
    black. My nickname's score stays 1 regardless of the color I hold."""
    app = _make_app()
    app.coordinator._start_online_game({
        "your_color": "white", "white_name": "Me", "black_name": "Friend",
        "time_minutes": 3, "increment_seconds": 0,
    })
    app.coordinator._handle_online_result({"reason": "checkmate", "winner_color": "white"})
    assert app.game.result_flow.series_scores["Me"] == 1
    assert app.game.result_flow.series_scores["Friend"] == 0.0
    app.coordinator._start_online_game({
        "your_color": "black", "white_name": "Friend", "black_name": "Me",
        "time_minutes": 3, "increment_seconds": 0,
        "white_score": 0.0, "black_score": 1.0,
    })
    assert app.game.result_flow.series_scores["Me"] == 1
    assert app.game.result_flow.series_scores["Friend"] == 0.0
    assert app.game._compute_game_info()["lines"][0] == "Friend  0 – 1  Me"


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
    app.switch_to("game", variant=ONLINE)
    app.game.white_name = "Alice"
    app.game.black_name = "Bob"
    app.game.result_flow.series_scores = {"Alice": 0.0, "Bob": 0.0}
    app.coordinator._handle_online_result({"reason": reason, "winner_color": winner})
    assert app.game.result_flow.result_text() == expected


@pytest.mark.parametrize("draw_reason,expected", [
    pytest.param("draw_agreement", ("Draw", "by agreement"), id="agreement"),
    pytest.param("draw_stalemate", ("Draw", "by stalemate"), id="stalemate"),
    pytest.param("draw_repetition", ("Draw", "by threefold repetition"), id="repetition"),
    pytest.param("draw_fifty_move", ("Draw", "by fifty-move rule"), id="fifty_move"),
    pytest.param("draw_insufficient_material", ("Draw", "by insufficient material"),
                 id="insufficient"),
])
def test_online_draw_result_subtitle(draw_reason, expected):
    """Each online draw reason keeps its own subtitle (manual_result=reason) instead
    of collapsing every draw to "by agreement"."""
    app = _make_app()
    app.switch_to("game", variant=ONLINE)
    app.game.white_name = "Alice"
    app.game.black_name = "Bob"
    app.game.result_flow.series_scores = {"Alice": 0.0, "Bob": 0.0}
    app.coordinator._handle_online_result({"reason": draw_reason})
    assert app.game.result_flow.result_text() == expected


def test_local_resignation_subtitle_reports_resignation():
    """Local resignation path uses the compound code so it never mislabels as
    "by checkmate"."""
    app = _make_app()
    _start_local(app)
    app.game._perform_resign()
    assert app.game.result_flow.result_text() == ("Black wins", "by resignation")


def test_single_screen_result_uses_winner_perspective_not_stale_local_color():
    """Bug: a stale local_color left over from a prior online game must not flip
    the single-screen result modal to the loser's clock / a DEFEAT word."""
    from chessshootout.backend.pieces import PieceColor
    app = _make_app()
    _start_local(app)
    app.game.match.local_color = PieceColor.BLACK
    assert (app.game.result_flow._result_subject_color("white_wins_by_resignation")
            == PieceColor.WHITE)
    assert app.game.result_flow._outcome_word_intent("white_wins_by_resignation", "White wins") \
        == ("White wins".upper(), "win")
    assert app.game.result_flow._result_subject_color("black_wins") == PieceColor.BLACK


def test_single_screen_start_resets_local_color():
    from chessshootout.backend.pieces import PieceColor
    app = _make_app()
    app.game.match.local_color = PieceColor.WHITE
    _start_local(app)
    assert app.game.match.local_color is None


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
    app.game.match.backend.game_result = lambda: engine_result
    assert app.game.result_flow.result_text() == expected


def test_menu_mode_returns_no_info():
    app = _make_app()
    assert app.screen is app.menu
    assert app.game._compute_game_info() is None


def test_settings_has_performance_section_wired_to_env():
    from chessshootout.infra import env
    app = _make_app()
    sections = dict(app.settings._build_settings_sections())
    assert "Performance" in sections
    rows = sections["Performance"]
    assert [r.title for r in rows] == [
        "Show FPS", "Show avg / min FPS", "Show 1% low FPS",
        "Show frame time", "Show ping",
    ]
    wiring = {
        "Show FPS": (env.get_show_fps, env.set_show_fps),
        "Show avg / min FPS": (env.get_show_frame_stats, env.set_show_frame_stats),
        "Show 1% low FPS": (env.get_show_1pct_low, env.set_show_1pct_low),
        "Show frame time": (env.get_show_frametime, env.set_show_frametime),
        "Show ping": (env.get_show_ping, env.set_show_ping),
    }
    for row in rows:
        getter, setter = wiring[row.title]
        assert row.getter is getter and row.setter is setter


def test_online_game_info_has_no_ping_line():
    app = _make_app()
    app.switch_to("game", variant=ONLINE)
    app.game.white_name = "A"
    app.game.black_name = "B"
    app.game._time_control = (60, 0)
    app.coordinator.client = MagicMock()
    lines = app.game._compute_game_info()["lines"]
    assert len(lines) == 1
    assert not any("ping" in line.lower() for line in lines)


def _info_menu():
    from chessshootout.frontend.panels.right import RightMenu
    from chessshootout.backend.backend import Backend
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
                      "lines": ["A 0 - 0 B", "Game 2"]})
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
