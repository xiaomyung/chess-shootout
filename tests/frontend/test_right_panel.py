"""RightMenu rendering: plain-text SAN move cells (no figurine images), the
current-move highlight (surface_active fill + inset accent border), click→ply
routing, and the scroll-reveal that fires only on review navigation — never as a
per-frame re-snap that would fight manual scrollback."""

from unittest.mock import MagicMock

import pygame as pg
import pytest

from tests.conftest import pygame_display
from tests.helpers import scan_region
from chessshootout.backend.backend import Backend
from chessshootout.backend.pieces import Piece, PieceType, PieceColor
from chessshootout.backend.utils import Square, Move, HistoryEntry
from chessshootout.frontend.panels.right import (
    RightMenu, CARD_INSET, CAPS, REVIEW_CAPS, SECTION_OPEN,
    LOG_HEADER_TOP, DEBUT_ROW_GAP, SIGNAL_NOTCH_COUNT,
)
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import dashed_hline, scale_floor


_pygame_init = pygame_display(1000, 800)


class _Board:
    def __init__(self):
        self.review_ply = None
        self.jumped = []

    def jump_to_review_ply(self, ply):
        self.jumped.append(ply)
        self.review_ply = ply


def _entry(piece_type, color, san):
    piece = Piece(piece_type, color)
    move = Move(Square(7, 6), Square(5, 5), piece)
    return HistoryEntry(move=move, prev_castling_rights=(), prev_en_passant_target=None,
                        prev_halfmove_clock=0, position_key_added=("k",), san=san)


def _menu(board=None):
    backend = Backend()
    backend.new_game()
    rm = RightMenu(pg.display.get_surface(), backend, {}, board=board)
    rm.set_rect(pg.Rect(0, 0, 320, 640))
    return rm, backend


def _has_color(win, rect, want_rgb, tol=8):
    rect = rect.clip(win.get_rect())
    for x in range(rect.x, rect.right, 2):
        for y in range(rect.y, rect.bottom, 2):
            c = win.get_at((x, y))
            if (abs(c.r - want_rgb[0]) <= tol and abs(c.g - want_rgb[1]) <= tol
                    and abs(c.b - want_rgb[2]) <= tol):
                return True
    return False


def _pawn_rows(backend, n):
    backend.move_history = [
        _entry(PieceType.PAWN, PieceColor.WHITE, f"a{i % 8 + 1}") for i in range(n)
    ]


def test_move_cell_renders_san_text():
    rm, backend = _menu()
    win = rm.window
    win.fill((0, 0, 0))
    backend.move_history = []
    rm.draw_menu()
    empty = pg.image.tobytes(win.subsurface(rm.moves_rect), "RGB")
    backend.move_history = [_entry(PieceType.KNIGHT, PieceColor.WHITE, "Nf3")]
    win.fill((0, 0, 0))
    rm.draw_menu()
    drawn = pg.image.tobytes(win.subsurface(rm.moves_rect), "RGB")
    assert drawn != empty, "the SAN move text should paint into the move list"
    assert _has_color(win, rm.moves_rect, pg.Color(Colors.text_dim)[:3], tol=45)


def test_current_move_highlight_uses_pressed_bg_and_accent_border():
    board = _Board()
    rm, backend = _menu(board)
    backend.move_history = [
        _entry(PieceType.PAWN, PieceColor.WHITE, "e4"),
        _entry(PieceType.PAWN, PieceColor.BLACK, "e5"),
    ]
    board.review_ply = 1
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    assert _has_color(rm.window, rm.moves_rect, pg.Color(Colors.surface_active)[:3]), \
        "current move cell uses the pressed surface as its background"
    assert _has_color(rm.window, rm.moves_rect, pg.Color(Colors.accent)[:3]), \
        "current move cell has an inset accent border"


def test_move_cell_click_jumps_to_ply():
    board = _Board()
    rm, backend = _menu(board)
    backend.move_history = [_entry(PieceType.PAWN, PieceColor.WHITE, "e4")]
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    cell_rect, ply = rm._move_cell_hits[0]
    assert rm.handle_click(cell_rect.center) is True
    assert board.jumped == [ply]


def test_review_nav_reveals_offscreen_ply():
    board = _Board()
    rm, backend = _menu(board)
    _pawn_rows(backend, 60)
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    assert rm.scroll_offset == 0
    board.review_ply = 2
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    assert rm.scroll_offset > 0, "navigating to an off-screen ply scrolls to reveal it"


def test_no_resnap_when_review_ply_unchanged():
    """Once revealed, manual scrollback must stick: the same review_ply across
    frames does not re-snap the offset."""
    board = _Board()
    rm, backend = _menu(board)
    _pawn_rows(backend, 60)
    board.review_ply = 2
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    rm.scroll_offset = 0
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    assert rm.scroll_offset == 0


def test_live_play_does_not_snap_offset():
    board = _Board()
    rm, backend = _menu(board)
    _pawn_rows(backend, 120)
    board.review_ply = None
    rm.scroll_offset = 5
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    assert rm.scroll_offset == 5, "no review nav → offset is left alone"


def test_card_floats_inset_from_menu_rect():
    """The panel is a floating card: 12px inset on top/right/bottom (backdrop shows
    through the gap); the left keeps its inner padding only."""
    rm, _ = _menu()
    rect = pg.Rect(0, 0, 320, 640)
    rm.set_rect(rect, scale=1.0)
    assert rm.outer_rect.top == rect.top + CARD_INSET
    assert rm.outer_rect.right == rect.right - CARD_INSET
    assert rm.outer_rect.bottom == rect.bottom - CARD_INSET


def test_card_top_right_corner_is_cut():
    """The card is a cut-corner (TR) rect: the top-right corner is carved away and
    shows the window backdrop, while the top edge elsewhere is covered by the card."""
    rm, _ = _menu()
    backdrop = (48, 96, 160)
    rm.window.fill(backdrop)
    rm.draw_menu()
    card = rm.outer_rect
    corner = rm.window.get_at((card.right - 2, card.top + 1))
    assert (corner.r, corner.g, corner.b) == backdrop, \
        "the card's top-right corner is cut, revealing the backdrop"
    edge = rm.window.get_at((card.centerx, card.top + 1))
    assert (edge.r, edge.g, edge.b) != backdrop, \
        "the top edge away from the cut is covered by the card"


def test_moves_well_uses_well_deep():
    rm, backend = _menu()
    backend.move_history = []
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    assert _has_color(rm.window, rm.moves_rect, pg.Color(Colors.well_deep)[:3]), \
        "the SHOT LOG well fills with well_deep"


def test_shot_log_header_counts_plies():
    """The micro-header renders SHOT LOG + the live PLY count in text_muted; the
    counter region changes as the history grows."""
    rm, backend = _menu()
    backend.move_history = []
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    zero = pg.image.tobytes(rm.window.subsurface(rm.moves_rect), "RGB")
    backend.move_history = [
        _entry(PieceType.PAWN, PieceColor.WHITE, "e4"),
        _entry(PieceType.PAWN, PieceColor.BLACK, "e5"),
    ]
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    two = pg.image.tobytes(rm.window.subsurface(rm.moves_rect), "RGB")
    assert zero != two, "the PLY counter changes when the history grows"
    band = pg.Rect(rm.moves_rect.x, rm.moves_rect.y, rm.moves_rect.width, 24)
    assert _has_color(rm.window, band, pg.Color(Colors.text_muted)[:3], tol=40), \
        "the micro-header paints text_muted glyphs"


def test_dashed_hline_alternates_opaque_and_transparent():
    surf = dashed_hline(60, "#ffcc00", dash=6, gap=5)
    alphas = [surf.get_at((x, 0))[3] for x in range(surf.get_width())]
    assert any(a == 0 for a in alphas), "gaps must be fully transparent"
    assert any(a > 0 for a in alphas), "dashes must paint the separator color"


def test_short_window_clips_body_to_card():
    """At a min-height panel the well hits its LOG_MIN_H floor; the clip keeps
    everything inside the card so the inset gap stays pure backdrop."""
    board = _Board()
    rm, backend = _menu(board)
    _pawn_rows(backend, 120)
    rm.set_rect(pg.Rect(0, 0, 300, 200))
    backdrop = (48, 96, 160)
    rm.window.fill(backdrop)
    rm.draw_menu()
    gap = rm.window.get_at((rm.outer_rect.centerx, rm.outer_rect.top - 4))
    assert (gap.r, gap.g, gap.b) == backdrop, "the top inset gap shows only backdrop"


def _review_menu():
    backend = Backend()
    backend.new_game()
    rm = RightMenu(pg.display.get_surface(), backend, {},
                   buttons_provider=lambda: REVIEW_CAPS, caps_stacked=True)
    rm.set_rect(pg.Rect(0, 0, 320, 640))
    return rm


def test_caps_provider_populates_expected_button_rects():
    rm, _ = _menu()
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    assert set(rm.button_rects) == {"undo", "draw", "resign", "give_time", "flip", "help"}


def test_review_caps_are_full_width_stacked_rows():
    rm = _review_menu()
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    assert set(rm.button_rects) == {"menu", "flip", "open_pgn"}
    inner = rm.moves_rect.width
    for rect in rm.button_rects.values():
        assert rect.width == inner, "review caps span the full inner width"


def test_toggle_section_collapses_actions_and_clears_caps():
    rm, _ = _menu()
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    assert set(rm.button_rects) == {cap.key for cap in CAPS}
    rm.toggle_section("actions")
    assert SECTION_OPEN["actions"] is False
    assert rm.button_rects == {}, "collapsing actions removes the cap hit rects"
    block = next(b for b in rm._section_blocks if b.key == "actions")
    assert block.show_body is False


def test_section_header_click_toggles_the_section():
    rm, _ = _menu()
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    header = next(b.header for b in rm._section_blocks if b.key == "signals")
    assert SECTION_OPEN["signals"] is True
    assert rm.handle_click(header.center) is True
    assert SECTION_OPEN["signals"] is False


def test_sections_default_closed_without_persisted_state():
    """Fresh install: no CHESS_RAIL_*_OPEN env keys and an empty cache means every
    section starts collapsed."""
    from chessshootout.frontend.panels.right import section_open
    import os
    from chessshootout.infra.env import _RAIL_SECTION_KEYS
    for key in _RAIL_SECTION_KEYS.values():
        os.environ.pop(key, None)
    SECTION_OPEN.clear()
    assert section_open("actions") is False
    assert section_open("signals") is False
    assert section_open("chat") is False


def test_toggle_section_persists_to_env_and_survives_cache_reset():
    """Toggling a section writes CHESS_RAIL_*_OPEN, so a fresh SECTION_OPEN cache
    (a new app run) re-reads the same state."""
    from chessshootout.frontend.panels.right import section_open
    from chessshootout.infra import env
    rm, _ = _menu()
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    rm.toggle_section("actions")
    assert env.get_rail_section_open("actions") is False
    SECTION_OPEN.clear()
    assert section_open("actions") is False
    rm.toggle_section("actions")
    assert env.get_rail_section_open("actions") is True
    SECTION_OPEN.clear()
    assert section_open("actions") is True


def test_section_open_state_is_shared_across_instances():
    rm1, _ = _menu()
    rm2, _ = _menu()
    rm1.window.fill((0, 0, 0))
    rm1.draw_menu()
    rm1.toggle_section("actions")
    rm2.set_rect(pg.Rect(0, 0, 320, 640))
    assert rm2.button_rects == {}, "the shared collapse hides caps on the second rail too"
    block = next(b for b in rm2._section_blocks if b.key == "actions")
    assert block.show_body is False


def test_disabled_cap_click_is_swallowed_without_callback():
    backend = Backend()
    backend.new_game()
    fired = []
    rm = RightMenu(pg.display.get_surface(), backend,
                   {"give_time": lambda: fired.append("give_time")},
                   buttons_provider=lambda: CAPS,
                   disabled_keys_provider=lambda: {"give_time"})
    rm.set_rect(pg.Rect(0, 0, 320, 640))
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    give = rm.button_rects["give_time"]
    assert rm.handle_click(give.center) is True
    assert fired == [], "a disabled cap swallows the click but never fires"


def test_cap_click_fires_callback_and_plays_cap_press():
    backend = Backend()
    backend.new_game()
    fired = []
    sounds = MagicMock()
    rm = RightMenu(pg.display.get_surface(), backend,
                   {"resign": lambda: fired.append("resign")},
                   buttons_provider=lambda: CAPS, sounds=sounds)
    rm.set_rect(pg.Rect(0, 0, 320, 640))
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    resign = rm.button_rects["resign"]
    assert rm.handle_click(resign.center) is True
    assert fired == ["resign"]
    sounds.play_cap_press.assert_called_once()


def test_section_toggle_plays_section_toggle_sound():
    backend = Backend()
    backend.new_game()
    sounds = MagicMock()
    rm = RightMenu(pg.display.get_surface(), backend, {},
                   buttons_provider=lambda: CAPS, sounds=sounds)
    rm.set_rect(pg.Rect(0, 0, 320, 640))
    rm.toggle_section("actions")
    sounds.play_section_toggle.assert_called_once()


def _debut_row_center(rm):
    ly = rm.moves_rect.y + scale_floor(LOG_HEADER_TOP, rm.scale, 6)
    row_y = ly + rm.micro_font.get_height() + scale_floor(DEBUT_ROW_GAP, rm.scale, 3)
    return (rm.moves_rect.centerx, row_y + rm.micro_font.get_height() // 2)


def test_debut_row_paints_only_when_provider_hits():
    rm, backend = _menu()
    backend.move_history = [_entry(PieceType.PAWN, PieceColor.WHITE, "e4")]
    rm.debut_provider = lambda: None
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    absent = pg.image.tobytes(rm.window.subsurface(rm.moves_rect), "RGB")
    rm.debut_provider = lambda: ("C50", "Italian Game: Giuoco Piano")
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    present = pg.image.tobytes(rm.window.subsurface(rm.moves_rect), "RGB")
    assert present != absent, "a debut hit adds a row under the micro-header"
    band = pg.Rect(rm.moves_rect.x, rm.moves_rect.y, rm.moves_rect.width, 44)
    assert _has_color(rm.window, band, pg.Color(Colors.text_dim)[:3], tol=45), \
        "the opening NAME paints in text_dim"


def test_debut_row_shrinks_move_viewport():
    rm, backend = _menu()
    _pawn_rows(backend, 60)
    rm.debut_provider = lambda: None
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    without = rm._max_lines
    without_top = rm._moves_viewport.y
    rm.debut_provider = lambda: ("C50", "Italian Game: Giuoco Piano")
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    assert rm._moves_viewport.y > without_top, "the debut row pushes the move rows down"
    assert rm._max_lines <= without, "the debut row never grows the move viewport"


def test_debut_marquee_slides_on_hover_and_eases_back(monkeypatch):
    rm, backend = _menu()
    long_name = ("Ruy Lopez Morphy Defense Chigorin Panov System Deferred "
                 "Extended Long Marquee Variation")
    rm.debut_provider = lambda: ("C99", long_name)
    rm.set_rect(pg.Rect(0, 0, 240, 640), scale=1.0)
    rm._marquee_off = 0.0
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: _debut_row_center(rm))
    offsets = []
    for _ in range(8):
        rm.window.fill((0, 0, 0))
        rm.draw_menu()
        offsets.append(rm._marquee_off)
    assert offsets[-1] > offsets[0] > 0, "the name slides left while the row is hovered"
    peak = rm._marquee_off
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: (0, 0))
    for _ in range(20):
        rm.window.fill((0, 0, 0))
        rm.draw_menu()
    assert rm._marquee_off < peak, "the offset eases back toward 0 once the mouse leaves"


# --- SIGNALS section: SHARE / AUTO-Q / SOUND chips + VOL notch row -----------

_SIGNAL_STATE = {
    "share_on": False, "share_enabled": True, "auto_q": False,
    "sound_on": True, "volume": 0.5, "review": False,
}


def _signals_menu(state, **callbacks):
    backend = Backend()
    backend.new_game()
    cb = {"share_toggle": lambda: None, "auto_q_toggle": lambda: None,
          "sound_toggle": lambda: None, "set_volume": lambda v: None}
    cb.update(callbacks)
    rm = RightMenu(pg.display.get_surface(), backend, cb,
                   signals_provider=lambda: dict(state))
    rm.set_rect(pg.Rect(0, 0, 320, 640))
    return rm


def _signal_chip(rm, key):
    return next(rect for chip, rect in rm._signal_chips if chip.key == key)


def _draw(rm):
    rm.window.fill((0, 0, 0))
    rm.draw_menu()


def test_signals_chips_render_all_three_live():
    state = dict(_SIGNAL_STATE)
    rm = _signals_menu(state)
    _draw(rm)
    assert [chip.key for chip, _ in rm._signal_chips] == ["share", "auto_q", "sound"]


def test_review_signals_show_only_the_sound_chip():
    state = dict(_SIGNAL_STATE, review=True)
    rm = _signals_menu(state)
    _draw(rm)
    assert [chip.key for chip, _ in rm._signal_chips] == ["sound"]


def test_signal_chip_on_paints_its_on_color_dot():
    """An ON chip wears a solid on-color status dot; OFF it is a muted border dot,
    so the on-colour never appears inside an OFF chip."""
    state = dict(_SIGNAL_STATE, auto_q=True)
    rm = _signals_menu(state)
    _draw(rm)
    rect = _signal_chip(rm, "auto_q")
    assert _has_color(rm.window, rect, pg.Color(Colors.accent)[:3], tol=12), \
        "the ON AUTO-Q chip shows an accent dot"
    state["auto_q"] = False
    _draw(rm)
    assert not _has_color(rm.window, rect, pg.Color(Colors.accent)[:3], tol=12), \
        "the OFF chip carries no accent"


def test_disabled_share_chip_is_inert_on_click():
    """SHARE is disabled off the board (local/bot): a click swallows but never
    fires the callback."""
    fired = []
    state = dict(_SIGNAL_STATE, share_enabled=False)
    rm = _signals_menu(state, share_toggle=lambda: fired.append("share"))
    _draw(rm)
    rect = _signal_chip(rm, "share")
    assert rm.handle_click(rect.center) is True
    assert fired == [], "the disabled SHARE chip swallows the click but never fires"


def test_live_chip_click_fires_callback_and_chip_toggle_sound():
    fired = []
    sounds = MagicMock()
    state = dict(_SIGNAL_STATE)
    backend = Backend()
    backend.new_game()
    rm = RightMenu(pg.display.get_surface(), backend,
                   {"auto_q_toggle": lambda: fired.append("auto_q"),
                    "share_toggle": lambda: None, "sound_toggle": lambda: None,
                    "set_volume": lambda v: None},
                   signals_provider=lambda: dict(state), sounds=sounds)
    rm.set_rect(pg.Rect(0, 0, 320, 640))
    _draw(rm)
    assert rm.handle_click(_signal_chip(rm, "auto_q").center) is True
    assert fired == ["auto_q"]
    sounds.play_chip_toggle.assert_called_once()


def _notch_center(rm, i):
    band = rm._signal_notch_band
    return (band.x + i * rm._signal_notch_step + rm._signal_notch_step // 2, band.centery)


def test_vol_notch_click_sets_that_level():
    vols = []
    state = dict(_SIGNAL_STATE, volume=0.0)
    rm = _signals_menu(state, set_volume=vols.append)
    _draw(rm)
    assert rm.handle_click(_notch_center(rm, 6)) is True
    assert vols == [pytest.approx(0.7)]
    rm.handle_click(_notch_center(rm, SIGNAL_NOTCH_COUNT - 1))
    assert vols[-1] == pytest.approx(1.0)


def test_vol_first_notch_zero_toggles_only_from_ten_percent():
    vols = []
    state = dict(_SIGNAL_STATE, volume=0.1)
    rm = _signals_menu(state, set_volume=vols.append)
    _draw(rm)
    rm.handle_click(_notch_center(rm, 0))
    assert vols[-1] == pytest.approx(0.0), "re-clicking notch 0 at 10% drops to 0%"
    state["volume"] = 0.5
    rm.handle_click(_notch_center(rm, 0))
    assert vols[-1] == pytest.approx(0.1), "notch 0 from any other level lands 10%, not 0%"


def test_sound_off_dims_vol_row_and_makes_notches_inert():
    vols = []
    state = dict(_SIGNAL_STATE, sound_on=True, volume=0.8)
    rm = _signals_menu(state, set_volume=vols.append)
    _draw(rm)
    band = rm._signal_notch_band
    assert _has_color(rm.window, band, pg.Color(Colors.accent)[:3], tol=12), \
        "a live VOL row paints full-accent filled notches"
    state["sound_on"] = False
    _draw(rm)
    assert not _has_color(rm.window, band, pg.Color(Colors.accent)[:3], tol=12), \
        "muted, the whole VOL row is dimmed below full accent"
    assert rm.handle_click(_notch_center(rm, 3)) is True
    assert vols == [], "a notch click is inert while sound is muted"


def test_vol_band_x_is_stable_across_readout_widths():
    """The N% readout sits in a fixed-width '100%' slot, so the notch band never
    shifts as the value moves between 0%, 50% and 100%."""
    state = dict(_SIGNAL_STATE)
    rm = _signals_menu(state)
    positions = []
    for v in (0.0, 0.5, 1.0):
        state["volume"] = v
        rm.set_rect(pg.Rect(0, 0, 320, 640))
        _draw(rm)
        positions.append(rm._signal_notch_band.x)
    assert positions[0] == positions[1] == positions[2]


def test_rail_tooltip_appears_over_hovered_cap(monkeypatch):
    rm, _ = _menu()
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    resign = rm.button_rects["resign"]
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: resign.center)
    ticks = {"t": 0}
    monkeypatch.setattr(pg.time, "get_ticks", lambda: ticks["t"])
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    labels = [label for _, _, label in rm.rail_tooltip.entries]
    assert any(label.startswith("RESIGN") for label in labels), \
        "the resign cap registers its tooltip label for the frame"
    ticks["t"] = 500
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    band = pg.Rect(rm.outer_rect.x, resign.top - 44, rm.outer_rect.width, 44)
    assert scan_region(rm.window, band, Colors.border_strong, tol=12, step=1), \
        "a border_strong-bordered bubble fades in above the hovered cap"
