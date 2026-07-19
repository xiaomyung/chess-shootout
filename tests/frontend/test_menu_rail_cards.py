"""Right-rail CardStack on the Play view: strict accordion (all cards start
collapsed, opening one collapses the others), the Profile card as a static
nav row (never expands in place, always routes to the profile sub-view),
Recent Matches (last 3, newest first, W/L/½ badge from the PGN Result tag +
player perspective, row -> review, footer -> History, hidden with no games),
and News (expandable feed, hidden when empty).

News, expanded, is a per-item single-open accordion: every item is a dated
header row and one open item renders its FULL body (no line cap); the newest
item auto-opens when the card expands. The card flex-heights to
min(natural content, rail space below the other cards) and scrolls its body
region internally (an owned NewsBox ScrollHost) when it overflows, leaving the
other cards' headers on-screen. An unread badge on the News header counts items
dated after the persisted last-seen date and clears (persists newest date) the
moment the card is expanded.
"""

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.menu.rail_cards import (
    AVATAR_SIZE, BODY_ROW_H, FOOTER_H, HEADER_H, PAD_X, _item_key,
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


def test_news_card_expanded_auto_opens_the_newest_item(app, stack):
    app.news_client._items = [
        {"title": "Newest", "body": "Body text", "date": "2026-07-14"},
        {"title": "Older one", "body": "B", "date": "2026-06-01"},
        {"title": "Even older", "body": "B", "date": "2026-01-01"},
    ]
    _refresh(app)
    stack._toggle("news")
    assert stack._open == "news"
    assert stack._open_news_item == _item_key(stack._news_items[0]), \
        "expanding the news card auto-opens the newest item"
    app.draw_frame()  # renders every item as a header row + the open body, no crash
    keys = [k for _, k in stack._news_item_hits]
    assert keys == [_item_key(i) for i in stack._news_items], \
        "every news item gets a header row recorded as a hit target"


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


def test_news_body_lines_are_not_capped(app, stack):
    """Cap-removal pin: the old 8-line ceiling is gone — an open item renders its
    FULL body (it scrolls internally when it overflows the card)."""
    app.news_client._items = [
        {"title": "T", "body": "\n".join(f"- item {i}" for i in range(20)),
         "date": "2026-07-14"},
    ]
    _refresh(app)
    app.draw_frame()
    lines = stack._news_body_lines(stack._news_items[0], 400)
    assert len(lines) == 20


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


# --- News feed: flex height, item accordion, inner scroll, unread badge -------


def _feed(items):
    return [{"title": t, "body": b, "date": d} for t, b, d in items]


def _big_feed(n=12, body_lines=60):
    body = "\n".join(f"- point {i}" for i in range(body_lines))
    return [{"title": f"Item {k}", "body": body if k == 0 else "brief note",
             "date": f"2026-07-{28 - k:02d}"} for k in range(n)]


def _expand_news(app, stack, items):
    app.news_client._items = items
    _refresh(app)
    stack._toggle("news")
    app.draw_frame()


def test_news_item_accordion_is_single_open(app, stack):
    items = _feed([("A", "body a", "2026-07-14"),
                   ("B", "body b", "2026-06-01"),
                   ("C", "body c", "2026-01-01")])
    _expand_news(app, stack, items)
    assert stack._open_news_item == _item_key(items[0])

    stack._toggle_news_item(_item_key(items[1]))
    assert stack._open_news_item == _item_key(items[1]), "opening one closes the previous"

    stack._toggle_news_item(_item_key(items[1]))
    assert stack._open_news_item is None, "re-clicking the open item closes it"


def test_news_item_toggle_plays_the_card_toggle_sound(app, stack):
    items = _feed([("A", "a", "2026-07-14"), ("B", "b", "2026-06-01")])
    _expand_news(app, stack, items)
    app.sound_manager.play_card_toggle.reset_mock()

    stack._toggle_news_item(_item_key(items[1]))

    app.sound_manager.play_card_toggle.assert_called_once()


def test_news_body_click_toggles_the_item_accordion(app, stack):
    items = _feed([("A", "a", "2026-07-14"), ("B", "b", "2026-06-01")])
    _expand_news(app, stack, items)
    hit = {k: rect for rect, k in stack._news_item_hits}
    stack.handle_click(hit[_item_key(items[1])].center)
    assert stack._open_news_item == _item_key(items[1]), \
        "clicking an item header (body region) toggles that item, not the card"


def test_news_open_item_survives_generation_refresh(app, stack):
    items = _feed([("A", "a", "2026-07-14"),
                   ("B", "b", "2026-06-01"),
                   ("C", "c", "2026-01-01")])
    _expand_news(app, stack, items)
    stack._toggle_news_item(_item_key(items[1]))
    assert stack._open_news_item == _item_key(items[1])

    # A fresh generation delivering equal-identity items (new dict objects).
    with app.news_client._lock:
        app.news_client._items = [dict(i) for i in items]
        app.news_client._generation += 1
    app.menu.update(0)
    assert stack._open_news_item == _item_key(items[1]), \
        "identity-keyed open state (date+title) survives a news refresh"

    # A generation where that item is gone drops the open state.
    with app.news_client._lock:
        app.news_client._items = _feed([("A", "a", "2026-07-14")])
        app.news_client._generation += 1
    app.menu.update(0)
    assert stack._open_news_item is None


def test_expanded_news_never_exceeds_rail_bottom(app, stack):
    _expand_news(app, stack, _big_feed())
    block = _block_rect(stack, "news")
    assert block.bottom <= stack._rect.bottom, "flex cap keeps the news card inside the rail"


def test_collapsed_headers_stay_visible_when_news_expands(app, tmp_path, stack):
    _write_pgn(tmp_path, "local-20260101-120000.pgn", "alice", "bob", "1-0")
    app.news_client._items = _big_feed()
    _refresh(app)
    stack._toggle("news")
    app.draw_frame()
    assert _block_rect(stack, "recent").height == stack._s(HEADER_H, 34), \
        "the other card stays collapsed (single-open) at header height"
    for key in ("profile", "recent"):
        assert _block_rect(stack, key).bottom <= stack._rect.bottom, \
            f"{key} header must stay on-screen while news is expanded"


def test_recent_card_keeps_its_natural_height(app, tmp_path, stack):
    for i in range(3):
        _write_pgn(tmp_path, f"local-2026010{i + 1}-120000.pgn", "alice", f"p{i}", "1-0")
    _refresh(app)
    stack._toggle("recent")
    natural = (stack._s(HEADER_H, 34) + 3 * stack._s(BODY_ROW_H, 32) + stack._s(FOOTER_H, 24))
    assert _block_rect(stack, "recent").height == natural, "recent keeps natural height (no cap)"


def test_overflowing_news_scrolls_internally_and_owns_the_wheel(app, stack):
    _expand_news(app, stack, _big_feed())
    assert stack.news_box.scroll.scrollable(), "overflowing news body is inner-scrollable"
    assert app.menu.active_scrollable() is stack.news_box, \
        "the wheel routes to the inner news box, not the outer stack"
    assert stack.news_box.scroll.thumb_rect() is not None, "an inner scroll thumb exists"

    center = stack.news_box._rect.center
    before = stack.news_box.scroll_offset
    app.menu.active_scrollable().handle_scroll(center, -3)
    assert stack.news_box.scroll_offset > before, "wheel scrolls the inner body down"


def test_inner_scroll_resets_to_top_on_card_expand(app, stack):
    _expand_news(app, stack, _big_feed())
    stack.news_box.handle_scroll(stack.news_box._rect.center, -3)
    assert stack.news_box.scroll_offset > 0
    stack._toggle("news")   # collapse
    stack._toggle("news")   # re-expand
    assert stack.news_box.scroll_offset == 0, "re-expanding resets the inner scroll to top"


def test_inner_scroll_offset_clamps_on_resize(app, stack):
    _expand_news(app, stack, _big_feed())
    stack.news_box.handle_scroll(stack.news_box._rect.center, -50)
    scrolled = stack.news_box.scroll_offset
    assert scrolled > 0
    w, h = app.window_width, app.window_height
    pg.event.clear()
    pg.event.post(pg.event.Event(pg.VIDEORESIZE, {"w": w, "h": h + 400}))
    app.input_router.check_events()
    app.draw_frame()
    max_off = max(0, stack.news_box._content_h - stack.news_box._rect.height)
    assert stack.news_box.scroll_offset <= max_off, "offset re-clamped after the rail grew"


def test_unread_badge_counts_items_newer_than_last_seen(app, stack):
    env.set_news_last_seen("2026-06-01")
    app.news_client._items = _feed([("A", "a", "2026-07-14"),
                                    ("B", "b", "2026-06-15"),
                                    ("C", "c", "2026-06-01"),
                                    ("D", "d", "2026-01-01")])
    _refresh(app)
    assert stack._unread_count() == 2, "only items dated strictly after last-seen are unread"


def test_no_unread_badge_when_everything_is_seen(app, stack):
    app.news_client._items = _feed([("A", "a", "2026-07-14"), ("B", "b", "2026-06-01")])
    _refresh(app)
    env.set_news_last_seen("2026-07-14")
    assert stack._unread_count() == 0


def test_expanding_news_clears_the_badge_and_persists_last_seen(app, stack):
    app.news_client._items = _feed([("A", "a", "2026-07-14"), ("B", "b", "2026-06-01")])
    _refresh(app)
    assert stack._unread_count() == 2
    stack._toggle("news")
    assert env.get_news_last_seen() == "2026-07-14", "expanding persists the newest date"
    assert stack._unread_count() == 0, "and clears the unread badge"


def test_malformed_news_date_is_excluded_from_unread_count(app, stack):
    app.news_client._items = _feed([("A", "a", "2026-07-14"), ("Bad", "b", "not-a-date")])
    _refresh(app)
    env.set_news_last_seen("2026-01-01")
    assert stack._unread_count() == 1, "malformed dates never count as unread"


def test_malformed_persisted_last_seen_is_treated_as_never_seen(app, stack):
    """A hand-edited .env can hold garbage in CHESS_NEWS_LAST_SEEN. A raw string
    compare against e.g. 'zzz' would make every valid date sort below it and
    silence the badge forever — the stored value must be validated too, and the
    next expand must overwrite the garbage with a real date."""
    env.set_news_last_seen("zzz")
    app.news_client._items = _feed([("A", "a", "2026-07-14"), ("B", "b", "2026-06-01")])
    _refresh(app)
    assert stack._unread_count() == 2, "garbage last-seen counts as never-seen"
    stack._toggle("news")
    assert env.get_news_last_seen() == "2026-07-14", "expand replaces the garbage value"


def test_expanding_never_regresses_the_persisted_last_seen(app, stack):
    """Last-seen is monotonic: a feed that temporarily rolls back to older items
    (cache fallback, server-side removal) must not shrink the persisted date,
    or already-seen items would flip back to unread later. It also means an
    expand with nothing new skips the .env disk write entirely."""
    env.set_news_last_seen("2026-07-20")
    app.news_client._items = _feed([("A", "a", "2026-07-14")])
    _refresh(app)
    assert stack._unread_count() == 0
    stack._toggle("news")
    assert env.get_news_last_seen() == "2026-07-20", "an older feed must not shrink last-seen"


def test_tap_on_the_scrollable_news_box_toggles_via_the_release_path(app, stack):
    """When the inner box is scrollable, a press inside it is grabbed by the
    scroll host and never reaches mouse_left_clicked — the item toggle (and its
    card-toggle sound) must also fire on the router's tap-on-release path."""
    _expand_news(app, stack, _big_feed())
    assert app.menu.active_scrollable() is stack.news_box
    app.sound_manager.play_card_toggle.reset_mock()
    pos = stack._news_item_hits[0][0].center
    router = app.input_router
    router._mouse_left_pressed(pos)
    assert router._scroll_pressed is stack.news_box, "press grabs the inner box, not a click"
    router._mouse_left_released(pos)
    assert stack._open_news_item is None, "tap release toggles the open item closed"
    app.sound_manager.play_card_toggle.assert_called_once()


def test_zero_height_inner_viewport_never_captures_the_wheel(app, stack):
    """Degenerate fallback: if the rail is so short that even collapsed headers
    overflow, the expanded news card clamps to header height and its inner
    viewport is zero-height. A zero-height viewport can never receive wheel or
    press events (collidepoint always misses), so it must not win
    active_scrollable and deaden the outer stack's wheel."""
    _expand_news(app, stack, _big_feed())
    stack.news_box._rect.height = 0
    assert not stack.news_box.is_visible()
    assert app.menu.active_scrollable() is not stack.news_box


def test_news_body_lines_are_memoized_until_refresh(app, stack):
    """The expanded card wraps the open body twice per frame (height pass +
    draw pass); wrap_words re-measures every word. Cache-first rule: the wrap
    is memoized per (item, width) and invalidated when the feed refreshes."""
    app.news_client._items = _feed([("A", "- a\n- b", "2026-07-14")])
    _refresh(app)
    first = stack._news_body_lines(stack._news_items[0], 300)
    assert stack._news_body_lines(stack._news_items[0], 300) is first
    _refresh(app)
    assert stack._news_body_lines(stack._news_items[0], 300) is not first
