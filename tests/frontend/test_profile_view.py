"""ProfileView: editable nickname (ASCII sanitize, 20 max, persist on commit,
non-ASCII cleanup toast), the country row opening the shared global picker
(flag updates from it), lifetime W/L/D + KO stats scanned from the PGN
history (reused loaders), the read-only client UUID line, the Esc-to-Play
chain, and that it stays a card-only destination (no rail row, not in
VIEW_ORDER)."""

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.menu.profile_view import NICKNAME_REJECT_TOAST
from chessshootout.frontend.screens.menu import VIEW_RISE_MS
from chessshootout.frontend.visual.widgets import avatar_palette
from chessshootout.infra import env
from tests.helpers import make_app


_pygame_init = pygame_display(1200, 900)


def _write_pgn(tmp_path, name, white, black, result, moves):
    games = tmp_path / "games"
    games.mkdir(exist_ok=True)
    path = games / name
    path.write_text(
        f'[White "{white}"]\n[Black "{black}"]\n[Result "{result}"]\n\n{moves} {result}\n',
        encoding="utf-8")
    return path


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    application = make_app(1200, 900)
    application.draw_frame()
    return application


@pytest.fixture
def view(app):
    return app.menu.views["profile"]


def test_enter_syncs_the_nickname_field_from_env(app, view):
    env.set_nickname("Hikaru")
    app.menu.goto_view("profile")
    assert view._nickname_input.text == "Hikaru"


def test_nickname_commits_on_blur(view):
    view._nickname_input.focused = True
    view._nickname_input.text = "Magnus"
    view._nickname_input.focused = False
    assert env.get_nickname() == "Magnus"


def test_nickname_capped_at_20_chars(app, view):
    view._nickname_input.focused = True
    for ch in "a" * 25:
        view._nickname_input._insert(ch)
    assert len(view._nickname_input.text) == 20


def test_nickname_rejects_non_ascii_with_toast(app, view):
    view._nickname_input.focused = True
    view._nickname_input._insert("Ω")
    assert app.toast.message == NICKNAME_REJECT_TOAST


def test_country_row_opens_the_shared_picker(app, view):
    env.set_country("us")
    app.menu.goto_view("profile")

    view.handle_click(view._country_rect.center)

    assert app.country_picker.is_visible() is True
    assert app.country_picker.current == "US"


def test_country_picker_selection_updates_env_and_flag_source(app, view):
    app.menu.goto_view("profile")
    view.handle_click(view._country_rect.center)

    app.country_picker._pick("RO")

    assert env.get_country() == "RO"
    assert view._flag_surface("RO") is not None


def test_lifetime_stats_correctness_against_fixture_pgns(app, tmp_path):
    env.set_nickname("alice")
    _write_pgn(tmp_path, "local-20260101-120000.pgn", "alice", "bob", "1-0",
               "1. e4 d5 2. exd5")
    _write_pgn(tmp_path, "local-20260102-120000.pgn", "bob", "alice", "1-0",
               "1. e4 d5 2. Nc3 dxe4")
    _write_pgn(tmp_path, "local-20260103-120000.pgn", "alice", "bob", "1/2-1/2",
               "1. e4 e5")

    app.menu.goto_view("profile")
    view = app.menu.views["profile"]

    assert view._wins == 1
    assert view._losses == 1
    assert view._draws == 1
    assert view._kos == 2


def test_spectated_games_count_as_neither_win_loss_nor_draw(app, tmp_path):
    env.set_nickname("alice")
    _write_pgn(tmp_path, "local-20260101-120000.pgn", "alice", "bob", "1-0",
               "1. e4 d5 2. exd5")
    _write_pgn(tmp_path, "local-20260104-120000.pgn", "carl", "dave", "1-0",
               "1. e4 e5")
    _write_pgn(tmp_path, "local-20260105-120000.pgn", "carl", "dave", "0-1",
               "1. e4 e5")

    app.menu.goto_view("profile")
    view = app.menu.views["profile"]

    assert view._wins == 1
    assert view._losses == 0
    assert view._draws == 0


def test_client_uuid_shown_read_only(app, monkeypatch):
    app.menu.goto_view("profile")
    uid = env.get_or_create_client_uuid()
    from chessshootout.frontend.menu import profile_view as pv
    captured = []
    real_render_text = pv.render_text

    def spy(font, text, color):
        captured.append(text)
        return real_render_text(font, text, color)
    monkeypatch.setattr(pv, "render_text", spy)

    before_nickname = env.get_nickname()
    before_country = env.get_country()
    app.draw_frame()

    assert any(uid in text for text in captured), "the client uuid must be visible somewhere"
    assert env.get_nickname() == before_nickname, "drawing must never mutate state"
    assert env.get_country() == before_country


def _settle_view_transition(app, monkeypatch):
    holder = {"ms": pg.time.get_ticks()}
    monkeypatch.setattr(pg.time, "get_ticks", lambda: holder["ms"])
    app.draw_frame()
    holder["ms"] += VIEW_RISE_MS + 1
    app.draw_frame()


def test_avatar_color_matches_the_palette_seeded_by_the_nickname(app, view, monkeypatch):
    env.set_nickname("Hikaru")
    app.menu.goto_view("profile")
    _settle_view_transition(app, monkeypatch)
    win = pg.display.get_surface()
    rect = view._avatar_rect
    pixel = win.get_at((rect.x + 3, rect.centery))[:3]
    expected_fill, _ = avatar_palette("Hikaru")
    assert pixel == (expected_fill.r, expected_fill.g, expected_fill.b)


def test_avatar_color_changes_when_the_nickname_changes(app, view, monkeypatch):
    win = pg.display.get_surface()
    app.menu.goto_view("profile")

    env.set_nickname("Hikaru")
    _settle_view_transition(app, monkeypatch)
    rect = view._avatar_rect
    first = win.get_at((rect.x + 3, rect.centery))[:3]

    env.set_nickname("Magnus")
    app.draw_frame()
    second = win.get_at((rect.x + 3, rect.centery))[:3]

    assert first != second, "the avatar re-seeds when the nickname changes"


def test_esc_from_profile_returns_to_play(app):
    app.menu.goto_view("profile")
    result = app.menu.escape()
    assert result is True
    assert app.menu._active_view == "play"


def test_exit_blurs_the_nickname_input(app, view):
    app.menu.goto_view("profile")
    view._nickname_input.focused = True
    app.menu.goto_view("play")
    assert view._nickname_input.focused is False


def test_profile_not_in_view_order():
    from chessshootout.frontend.menu.shell import VIEW_ORDER
    assert "profile" not in VIEW_ORDER


def test_profile_not_a_rail_row():
    from chessshootout.frontend.menu.rail import ROWS, OPTIONS_ROW
    keys = [key for key, _, _ in ROWS] + [OPTIONS_ROW[0]]
    assert "profile" not in keys


def test_resize_while_on_profile_does_not_crash_the_rail_reticle(app):
    app.menu.goto_view("profile")
    assert app.menu.rail.active == "profile"
    w, h = app.window_width, app.window_height
    pg.event.clear()
    pg.event.post(pg.event.Event(pg.VIDEORESIZE, {"w": w + 60, "h": h + 20}))
    app.input_router.check_events()
    app.draw_frame()  # would KeyError if rail._draw_reticle / _remap_reticle
    # mishandled an active view that has no rail row


def test_profile_enter_exit_reenter_is_idempotent(app, view):
    app.menu.goto_view("profile")
    view.exit()
    view.exit()  # double-exit must not raise
    env.set_nickname("Rebound")
    view.enter()
    app.draw_frame()
    assert view._nickname_input.text == "Rebound"
    assert view._nickname_input.focused is False
