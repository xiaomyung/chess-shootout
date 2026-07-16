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
from chessshootout.frontend.screens.menu import VIEW_RISE_MS
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.widgets import avatar_palette
from chessshootout.infra import env
from chessshootout.online.news import NewsClient
from tests.helpers import assert_pixel_color, write_pgn_fixture as _write_pgn


_pygame_init = pygame_display(1200, 900)


@pytest.fixture
def stack(app):
    return app.menu.card_stack


def _refresh(app):
    app.menu.card_stack.refresh()


def _block_rect(stack, key):
    for k, y, h in stack._cards:
        if k == key:
            return pg.Rect(stack._rect.x, stack._rect.y + y, stack._rect.width, h)
    raise AssertionError(f"{key} card not visible: {[b[0] for b in stack._cards]}")


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


def test_toggle_plays_the_card_toggle_sound_both_ways(app, stack):
    stack._toggle("recent")
    app.sound_manager.play_card_toggle.assert_called_once()
    stack._toggle("recent")
    assert app.sound_manager.play_card_toggle.call_count == 2


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


def test_news_body_bullet_lines_get_bullets_and_hanging_indent(app, stack):
    """News bodies are authored as '- item' lists: each list line renders with a
    bullet glyph, wrapped continuations hang-indent under the text (not the
    bullet), and plain intro lines render unindented."""
    long_item = "- " + "really " * 30 + "long entry"
    app.news_client._items = [
        {"title": "T", "body": f"Intro line\n- First change\n{long_item}",
         "date": "2026-07-14"},
    ]
    _refresh(app)
    app.draw_frame()
    lines = stack._news_body_lines(stack._news_items[0], 200)
    assert lines[0] == (0, "Intro line")
    assert lines[1][0] == 0 and lines[1][1].startswith("• First change")
    bullet_starts = [line for indent, line in lines if line.startswith("•")]
    assert len(bullet_starts) == 2
    continuations = [indent for indent, line in lines[2:] if not line.startswith("•")]
    assert continuations and all(indent > 0 for indent in continuations)


def test_news_body_line_count_capped(app, stack):
    app.news_client._items = [
        {"title": "T", "body": "\n".join(f"- item {i}" for i in range(20)),
         "date": "2026-07-14"},
    ]
    _refresh(app)
    app.draw_frame()
    lines = stack._news_body_lines(stack._news_items[0], 400)
    assert len(lines) == 8


def test_news_arriving_after_construction_surfaces_via_update(app, tmp_path, stack):
    """Cold-cache landing: the async fetch replaces NewsClient's items and bumps
    its generation counter after the menu is already built. MenuScreen.update()
    watches that counter and re-refreshes the card stack in place — the news card
    appears on the live Play view with no tab switch."""
    fresh = NewsClient(url="unused://", cache_path=tmp_path / "news.json")
    app.news_client = fresh
    stack.refresh()
    assert app.menu._active_view == "play"
    assert "news" not in stack._visible_card_keys()

    with fresh._lock:
        fresh._items = [{"title": "Breaking", "body": "B", "date": "2026-07-14"}]
        fresh._generation += 1
    assert "news" not in stack._visible_card_keys(), \
        "the fetch landing alone must not refresh the card stack"

    app.menu.update(0)

    assert "news" in stack._visible_card_keys()
    assert stack._news_summary() == "Breaking"


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


def test_profile_avatar_is_a_flat_tile_not_a_gradient(app, stack):
    """cp3: the right-rail avatar was a blurry vertical gradient blob, off the
    flat-fill card language. It is now a crisp flat tile with a dark bold
    letter — a flat fill means top and mid sample the SAME colour (a gradient
    would not), and that colour comes from the nickname-seeded avatar palette."""
    env.set_nickname("alice")
    _refresh(app)
    app.draw_frame()
    av = _profile_avatar_rect(stack)
    win = pg.display.get_surface()
    top = win.get_at((av.x + 3, av.y + av.height // 4))[:3]
    mid = win.get_at((av.x + 3, av.centery))[:3]
    assert top == mid, "flat fill: no vertical gradient across the avatar tile"
    expected_fill, _ = avatar_palette("alice")
    assert_pixel_color(win, av.x + 3, av.centery, expected_fill, tol=12)


def test_profile_avatar_color_is_stable_for_the_same_nickname(app, stack):
    env.set_nickname("carol")
    _refresh(app)
    app.draw_frame()
    av = _profile_avatar_rect(stack)
    win = pg.display.get_surface()
    first = win.get_at((av.x + 3, av.centery))[:3]
    _refresh(app)
    app.draw_frame()
    second = win.get_at((av.x + 3, av.centery))[:3]
    assert first == second, "the same nickname always maps to the same avatar color"


def test_rail_and_profile_view_avatars_agree_for_the_same_nickname(app, stack, monkeypatch):
    env.set_nickname("dave")
    _refresh(app)
    app.draw_frame()
    av = _profile_avatar_rect(stack)
    win = pg.display.get_surface()
    rail_color = win.get_at((av.x + 3, av.centery))[:3]

    app.menu.goto_view("profile")
    holder = {"ms": pg.time.get_ticks()}
    monkeypatch.setattr(pg.time, "get_ticks", lambda: holder["ms"])
    app.draw_frame()
    holder["ms"] += VIEW_RISE_MS + 1
    app.draw_frame()
    view = app.menu.views["profile"]
    profile_rect = view._avatar_rect
    profile_color = win.get_at(
        (profile_rect.x + 3, profile_rect.centery))[:3]

    assert rail_color == profile_color, \
        "rail card and profile view resolve the same avatar color for the same nickname"


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
