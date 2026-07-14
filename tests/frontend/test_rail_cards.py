"""Right-rail CardStack on the Play view: strict accordion (all cards start
collapsed, opening one collapses the others), the Profile card as a static
nav row (never expands in place, always routes to the profile sub-view),
Recent Matches (last 3, newest first, W/L/½ badge from the PGN Result tag +
player perspective, row -> review, footer -> History, hidden with no games),
and News (newest item expanded, older as dated headlines, hidden when empty).
"""

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.menu.rail_cards import (
    AVATAR_SIZE, BODY_ROW_H, FOOTER_H, HEADER_H, PAD_X,
)
from chessshootout.frontend.visual.colors import Colors
from chessshootout.infra import env
from tests.helpers import assert_pixel_color, make_app


_pygame_init = pygame_display(1200, 900)


def _write_pgn(tmp_path, name, white, black, result, moves="1. e4 e5"):
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
def stack(app):
    return app.menu.card_stack


def _refresh(app):
    app.menu.card_stack.refresh()


def _block_rect(stack, key):
    for k, y, h in stack._blocks:
        if k == key:
            return pg.Rect(stack._rect.x, stack._rect.y + y, stack._rect.width, h)
    raise AssertionError(f"{key} card not visible: {[b[0] for b in stack._blocks]}")


def test_all_cards_start_collapsed(stack):
    assert stack._open is None


def test_opening_one_card_collapses_the_other(app, tmp_path, stack):
    _write_pgn(tmp_path, "local-20260101-120000.pgn", "alice", "bob", "1-0")
    app.news_client._items = [{"title": "News", "body": "Body", "date": "2026-07-14"}]
    _refresh(app)

    stack._toggle("recent")
    assert stack._open == "recent"

    stack._toggle("news")
    assert stack._open == "news", "opening news must collapse recent"


def test_reclicking_the_open_card_collapses_it(stack, tmp_path, app):
    _write_pgn(tmp_path, "local-20260101-120000.pgn", "alice", "bob", "1-0")
    _refresh(app)
    stack._toggle("recent")
    assert stack._open == "recent"
    stack._toggle("recent")
    assert stack._open is None


def test_profile_card_click_opens_the_profile_view(app, stack):
    assert app.menu._active_view == "play"

    handled = app.menu.handle_click(_block_rect(stack, "profile").center)

    assert handled is True
    assert app.menu._active_view == "profile"


def test_profile_card_never_accordion_opens(stack, app):
    stack.handle_click(_block_rect(stack, "profile").center)
    assert stack._open is None, "profile is a nav row, not an accordion participant"


def test_recent_matches_hidden_when_no_games(stack):
    assert "recent" not in stack._visible_card_keys()


def test_recent_matches_card_visible_after_a_game_is_saved(app, tmp_path, stack):
    _write_pgn(tmp_path, "local-20260101-120000.pgn", "alice", "bob", "1-0")
    _refresh(app)
    assert "recent" in stack._visible_card_keys()


def test_recent_matches_caps_at_three_newest_first(app, tmp_path, stack):
    _write_pgn(tmp_path, "local-20260101-120000.pgn", "alice", "p1", "1-0")
    _write_pgn(tmp_path, "local-20260102-120000.pgn", "alice", "p2", "1-0")
    _write_pgn(tmp_path, "local-20260103-120000.pgn", "alice", "p3", "1-0")
    _write_pgn(tmp_path, "local-20260104-120000.pgn", "alice", "p4", "1-0")
    _refresh(app)

    assert len(stack._recent_groups) == 3
    opponents = [g.black for g in stack._recent_groups]
    assert opponents == ["p4", "p3", "p2"], "newest first, oldest dropped"


def test_recent_match_badge_matches_pgn_result_from_player_perspective(app, tmp_path, stack):
    env.set_nickname("alice")
    _write_pgn(tmp_path, "local-20260101-120000.pgn", "alice", "bob", "1-0")
    _write_pgn(tmp_path, "local-20260102-120000.pgn", "bob", "alice", "1-0")
    _write_pgn(tmp_path, "local-20260103-120000.pgn", "alice", "bob", "1/2-1/2")
    _refresh(app)

    results = [g.result for g in stack._recent_groups]
    assert results == ["draw", "loss", "win"]


def test_recent_match_row_click_opens_review(app, tmp_path, stack, monkeypatch):
    _write_pgn(tmp_path, "local-20260101-120000.pgn", "alice", "bob", "1-0")
    _refresh(app)
    stack._toggle("recent")

    opened = []
    monkeypatch.setattr(app, "_open_pgn_review", lambda path: opened.append(path))

    block = _block_rect(stack, "recent")
    row = pg.Rect(block.x, block.y + stack._s(HEADER_H, 34), block.width,
                  stack._s(BODY_ROW_H, 32))
    stack.handle_click(row.center)

    assert opened == [stack._recent_groups[0].games[0].path]


def test_view_all_link_goes_to_history(app, tmp_path, stack):
    _write_pgn(tmp_path, "local-20260101-120000.pgn", "alice", "bob", "1-0")
    _refresh(app)
    stack._toggle("recent")

    block = _block_rect(stack, "recent")
    footer_h = stack._s(FOOTER_H, 24)
    footer_center = (block.centerx, block.bottom - footer_h // 2)
    stack.handle_click(footer_center)

    assert app.menu._active_view == "history"


def test_news_card_hidden_when_no_news(app, stack):
    app.news_client._items = []
    _refresh(app)
    assert "news" not in stack._visible_card_keys()


def test_news_card_visible_with_items(app, stack):
    app.news_client._items = [{"title": "Hello", "body": "World", "date": "2026-07-14"}]
    _refresh(app)
    assert "news" in stack._visible_card_keys()


def test_news_card_expanded_shows_newest_plus_headlines(app, stack):
    app.news_client._items = [
        {"title": "Newest", "body": "Body text", "date": "2026-07-14"},
        {"title": "Older one", "body": "B", "date": "2026-06-01"},
        {"title": "Even older", "body": "B", "date": "2026-01-01"},
    ]
    _refresh(app)
    stack._toggle("news")
    assert stack._open == "news"
    app.draw_frame()  # renders without crashing: newest expanded + 2 headline rows


def test_news_summary_shows_newest_title_when_collapsed(app, stack):
    app.news_client._items = [
        {"title": "Zulu newest", "body": "B", "date": "2026-07-14"},
        {"title": "Alpha oldest", "body": "B", "date": "2026-01-01"},
    ]
    _refresh(app)
    assert stack._news_summary() == "Zulu newest"


def test_cards_only_render_on_the_play_view(app, tmp_path):
    _write_pgn(tmp_path, "local-20260101-120000.pgn", "alice", "bob", "1-0")
    _refresh(app)
    app.menu.goto_view("history")
    app.draw_frame()
    assert app.menu._menu_layout.right_rail_rect.width == 0, \
        "no right rail while a sub-view other than play is active"

    app.menu.goto_view("play")
    app.draw_frame()
    assert app.menu._menu_layout.right_rail_rect.width > 0
    assert "recent" in app.menu.card_stack._visible_card_keys()


def test_right_rail_absent_off_the_play_view(app):
    app.menu.goto_view("history")
    assert app.menu._menu_layout.right_rail_rect.width == 0


def _profile_avatar_rect(stack):
    block = _block_rect(stack, "profile")
    pad = stack._s(PAD_X, 10)
    av = stack._s(AVATAR_SIZE, 30)
    return pg.Rect(block.x + pad, block.centery - av // 2, av, av)


def test_profile_avatar_is_a_flat_accent_tile_not_a_gradient(app, stack):
    """cp3: the right-rail avatar was a blurry vertical gradient blob, off the
    flat-fill card language. It is now a crisp flat accent tile with a dark bold
    letter — a flat fill means top and mid sample the SAME colour (a gradient
    would not), and that colour is the accent."""
    env.set_nickname("alice")
    _refresh(app)
    app.draw_frame()
    av = _profile_avatar_rect(stack)
    win = pg.display.get_surface()
    top = win.get_at((av.x + 3, av.y + av.height // 4))[:3]
    mid = win.get_at((av.x + 3, av.centery))[:3]
    assert top == mid, "flat fill: no vertical gradient across the avatar tile"
    assert_pixel_color(win, av.x + 3, av.centery, Colors.accent, tol=12)


def test_profile_avatar_draws_a_dark_letter_on_the_tile(app, stack):
    env.set_nickname("alice")
    _refresh(app)
    app.draw_frame()
    av = _profile_avatar_rect(stack)
    win = pg.display.get_surface()
    dark = tuple(pg.Color(Colors.on_accent))[:3]
    found = any(
        max(abs(a - b) for a, b in zip(win.get_at((x, y))[:3], dark)) <= 36
        for x in range(av.x + av.width // 4, av.right - av.width // 6)
        for y in range(av.y + av.height // 4, av.bottom - av.height // 4))
    assert found, "a dark bold letter renders on the flat accent tile"
