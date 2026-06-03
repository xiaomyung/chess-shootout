"""The History page: it scans saved PGNs, groups them into matches by CSMatchId (rematches
stack, idless games stay solo), renders the match summary (W/L/D counted per match), match
cards with filters + a perspective-aware KO score, expands multi-game matches into per-game
rows, opens a game into review on click, and returns to the card via its Menu button."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.menu.history import HistoryView
from frontend.visual.colors import Colors
from tests.helpers import fake_uuid4


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def _write_pgn(directory, name, *, white="alice", black="Bob", result="1-0",
               match_id=None, tc="600+5", body="1. e4 d5 2. exd5 Qxd5 1-0"):
    headers = [f'[White "{white}"]', f'[Black "{black}"]',
               f'[Result "{result}"]', f'[TimeControl "{tc}"]']
    if match_id:
        headers.append(f'[CSMatchId "{match_id}"]')
    (directory / name).write_text("\n".join(headers) + "\n\n" + body + "\n")


def _view(directory, nickname="alice", on_open=None, on_back=None):
    view = HistoryView(pg.display.get_surface(), on_open or (lambda p: None),
                       on_back or (lambda: None))
    view.set_rect(pg.Rect(40, 60, 840, 700))
    view.show(str(directory), "*.pgn", nickname=nickname)
    return view


def _region_has_color(surface, rect, hex_color, tol=40):
    want = pg.Color(hex_color)[:3]
    for x in range(max(rect.x, 0), min(rect.right, surface.get_width()), 3):
        for y in range(max(rect.y, 0), min(rect.bottom, surface.get_height()), 3):
            got = surface.get_at((x, y))[:3]
            if all(abs(a - b) <= tol for a, b in zip(got, want)):
                return True
    return False


def _hit_for(view, kind):
    return [(rect, value) for rect, (k, value) in view._row_hits if k == kind]


def test_hidden_before_show():
    assert HistoryView(pg.display.get_surface(), lambda p: None, lambda: None).is_visible() is False


def test_show_makes_visible(tmp_path):
    assert _view(tmp_path).is_visible() is True


def test_rematch_games_group_into_one_card(tmp_path):
    mid = fake_uuid4(1)
    _write_pgn(tmp_path, "local-20260101-100000.pgn", match_id=mid)
    _write_pgn(tmp_path, "local-20260101-110000.pgn", match_id=mid)
    _write_pgn(tmp_path, "local-20260101-120000.pgn")
    view = _view(tmp_path)
    assert len(view._groups) == 2
    multi = [g for g in view._groups if len(g.games) > 1]
    assert len(multi) == 1 and len(multi[0].games) == 2


def test_single_game_card_opens_directly(tmp_path):
    _write_pgn(tmp_path, "local-20260101-120000.pgn")
    opened = []
    view = _view(tmp_path, on_open=opened.append)
    view.draw()
    rect, path = _hit_for(view, "open")[0]
    assert view.handle_click(rect.center) is True
    assert opened == [path]


def test_multi_game_card_expands_then_opens_a_game(tmp_path):
    mid = fake_uuid4(2)
    _write_pgn(tmp_path, "local-20260101-100000.pgn", match_id=mid)
    _write_pgn(tmp_path, "local-20260101-110000.pgn", match_id=mid)
    opened = []
    view = _view(tmp_path, on_open=opened.append)
    view.draw()
    rect, value = _hit_for(view, "toggle")[0]
    view.handle_click(rect.center)
    assert view.expanded_match_id == mid
    view.draw()
    game_rect, path = _hit_for(view, "open")[0]
    view.handle_click(game_rect.center)
    assert opened == [path]


def test_menu_button_invokes_on_back(tmp_path):
    fired = []
    view = _view(tmp_path, on_back=lambda: fired.append(1))
    view.draw()
    assert view.handle_click(view._menu_rect.center) is True
    assert fired == [1]


def test_filter_chip_restricts_groups(tmp_path):
    _write_pgn(tmp_path, "local-20260101-100000.pgn")
    _write_pgn(tmp_path, "online-20260101-110000.pgn")
    _write_pgn(tmp_path, "online-20260101-120000.pgn")
    view = _view(tmp_path)
    view.draw()
    assert len(view._visible_groups()) == 3
    view.handle_click(view._filter_rects["online"].center)
    assert view.filter == "online"
    assert len(view._visible_groups()) == 2


def test_stats_count_matches_not_games(tmp_path):
    mid = fake_uuid4(5)
    _write_pgn(tmp_path, "online-20260101-100000.pgn", white="alice", result="1-0", match_id=mid)
    _write_pgn(tmp_path, "online-20260101-110000.pgn", white="alice", result="1-0", match_id=mid)
    _write_pgn(tmp_path, "local-20260101-120000.pgn", white="alice", result="0-1")
    view = _view(tmp_path, nickname="alice")
    assert view._stats() == (1, 1, 0)


def test_drawn_match_counts_as_draw(tmp_path):
    _write_pgn(tmp_path, "local-20260101-100000.pgn", white="alice", result="1/2-1/2")
    view = _view(tmp_path, nickname="alice")
    assert view._stats() == (0, 0, 1)


def test_non_participant_game_buckets_by_white_perspective(tmp_path):
    _write_pgn(tmp_path, "online-20260101-100000.pgn", white="carl", black="dave", result="1-0")
    view = _view(tmp_path, nickname="alice")
    assert view._stats() == (1, 0, 0)


def test_count_equals_win_loss_draw_sum(tmp_path):
    mid = fake_uuid4(7)
    _write_pgn(tmp_path, "online-20260101-100000.pgn", white="alice", result="1-0", match_id=mid)
    _write_pgn(tmp_path, "online-20260101-110000.pgn", white="alice", result="0-1", match_id=mid)
    _write_pgn(tmp_path, "bot-20260101-120000.pgn", white="alice", result="1-0")
    _write_pgn(tmp_path, "local-20260101-130000.pgn", white="carl", black="dave", result="1/2-1/2")
    view = _view(tmp_path, nickname="alice")
    assert len(view._visible_groups()) == sum(view._stats())


def test_ko_score_is_perspective_aware(tmp_path):
    _write_pgn(tmp_path, "local-20260101-100000.pgn", white="alice", black="Bob",
               body="1. e4 d5 2. exd5 Qxd5 1-0")
    view = _view(tmp_path, nickname="alice")
    group = view._groups[0]
    assert (group.ko_you, group.ko_opp) == (1, 1)


def test_ko_score_swaps_when_player_is_black(tmp_path):
    _write_pgn(tmp_path, "local-20260101-100000.pgn", white="Bob", black="alice",
               body="1. e4 d5 2. exd5 e6 3. dxe6 Bxe6 1-0")
    view = _view(tmp_path, nickname="alice")
    group = view._groups[0]
    assert group.ko_you == group.games[0].black_captures
    assert group.ko_opp == group.games[0].white_captures


def test_you_highlighted_in_amber(tmp_path):
    _write_pgn(tmp_path, "local-20260101-100000.pgn", white="alice", black="Bob")
    view = _view(tmp_path, nickname="alice")
    view.draw()
    card_rect, _ = view._row_hits[0]
    region = pg.Rect(card_rect.x + 70, card_rect.y + 6, 220, view._name_font.get_height() + 8)
    assert _region_has_color(view.window, region, Colors.amber_hi)


def test_untimed_game_renders_without_crash(tmp_path):
    _write_pgn(tmp_path, "local-20260101-100000.pgn", tc="-")
    view = _view(tmp_path)
    view.draw()
    assert view._groups[0].time_control == "No clock"
    card_rect, _ = view._row_hits[0]
    tc_region = pg.Rect(card_rect.right - 220, card_rect.centery, 120, 24)
    assert _region_has_color(view.window, tc_region, Colors.white, tol=40)


def test_empty_state_has_no_rows(tmp_path):
    view = _view(tmp_path)
    view.draw()
    assert view._groups == []
    assert view._row_hits == []


def test_empty_state_draws_message(tmp_path):
    view = _view(tmp_path)
    view.window.fill((0, 0, 0))
    view.set_rect(pg.Rect(40, 60, 840, 700))
    view.show(str(tmp_path), "*.pgn", nickname="alice")
    view.draw()
    assert _region_has_color(view.window, view._list_rect, Colors.text_mute, tol=60)


def test_scroll_advances_and_caps(tmp_path):
    for i in range(40):
        _write_pgn(tmp_path, f"local-20260101-{100000 + i:06d}.pgn")
    view = _view(tmp_path)
    view.draw()
    assert view.handle_scroll(view._list_rect.center, -1) is True
    assert view.scroll_offset > 0
    for _ in range(200):
        view.handle_scroll(view._list_rect.center, -1)
    capped = view.scroll_offset
    view.handle_scroll(view._list_rect.center, -1)
    assert view.scroll_offset == capped


def test_scroll_outside_list_returns_false(tmp_path):
    for i in range(40):
        _write_pgn(tmp_path, f"local-20260101-{100000 + i:06d}.pgn")
    view = _view(tmp_path)
    view.draw()
    assert view.handle_scroll((5, 5), -1) is False


def test_history_does_not_handle_keys():
    view = HistoryView(pg.display.get_surface(), lambda p: None, lambda: None)
    assert not hasattr(view, "handle_key")
