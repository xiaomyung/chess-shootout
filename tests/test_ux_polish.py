import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from collections import Counter
from unittest.mock import MagicMock

import pygame as pg
import pytest

from backend.backend import Backend
from backend.pieces import Piece, PieceColor, PieceType
from backend.utils import Square
from frontend.board import Board, DRAG_THRESHOLD_PX
from domain.capture_summary import captured_by, material_advantage
from frontend.modals.confirm import ConfirmModal


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


@pytest.fixture
def board():
    backend = Backend()
    backend.new_game()
    bd = Board(pg.display.get_surface(), backend)
    bd.load_assets()
    bd.set_rect(pg.Rect(0, 0, 400, 400))
    return bd


def _new_app():
    from frontend.frontend import Frontend
    app = Frontend(900, 500)
    app.sound_manager = MagicMock()
    app._on_start_game({"mode": "single_screen", "nickname": "a",
                        "time_minutes": None, "increment_seconds": 5,
                        "side": "white"})
    return app


def setup_position(board, piece_map, turn=PieceColor.WHITE):
    bk = board.backend
    bk.state = [[None] * 8 for _ in range(8)]
    for sq, piece in piece_map.items():
        bk.state[sq.row][sq.col] = piece
    bk.turn = turn
    bk.move_history = []
    bk.position_counts = Counter()
    bk.position_counts[bk._position_key()] = 1


def fire_animation(board):
    for a in list(board.animations):
        a.start_ms = pg.time.get_ticks() - 10_000
    board._draw_animations()


def _cell_block(board, row, col):
    rect = board._cell_rect(row, col)
    cx, cy = rect.centerx, rect.centery
    return [board.window.get_at((cx + dx, cy + dy))
            for dx in (-2, 0, 2) for dy in (-2, 0, 2)]


def test_last_move_highlight_renders_when_history_nonempty(board):
    """Both from/to squares get the translucent last-move overlay blitted."""
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    fire_animation(board)
    before_from = _cell_block(board, 6, 4)
    before_to = _cell_block(board, 4, 4)
    board._draw_last_move_highlight()
    assert _cell_block(board, 6, 4) != before_from
    assert _cell_block(board, 4, 4) != before_to


def test_last_move_highlight_skipped_when_history_empty(board):
    rects = []
    original_cell_rect = board._cell_rect
    board._cell_rect = lambda r, c: rects.append((r, c)) or original_cell_rect(r, c)
    try:
        board._draw_last_move_highlight()
    finally:
        board._cell_rect = original_cell_rect
    assert rects == []


def test_last_move_highlight_uses_both_squares(board):
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    fire_animation(board)
    rects = []
    original = board._cell_rect

    def capture(row, col):
        rects.append((row, col))
        return original(row, col)

    board._cell_rect = capture
    board._draw_last_move_highlight()
    board._cell_rect = original
    assert (6, 4) in rects
    assert (4, 4) in rects


def test_confirm_modal_hidden_by_default():
    modal = ConfirmModal(pg.display.get_surface())
    modal.set_rect(pg.Rect(0, 0, 200, 100))
    assert modal.is_visible() is False


def test_confirm_modal_show_makes_visible():
    modal = ConfirmModal(pg.display.get_surface())
    modal.set_rect(pg.Rect(0, 0, 200, 100))
    modal.show("Resign?", on_yes=lambda: None)
    assert modal.is_visible() is True


def test_confirm_modal_yes_invokes_callback_and_hides():
    modal = ConfirmModal(pg.display.get_surface())
    modal.set_rect(pg.Rect(0, 0, 200, 100))
    fired = [False]
    modal.show("Resign?", on_yes=lambda: fired.__setitem__(0, True),
               yes_label="Resign", no_label="Cancel")
    modal.draw()
    yes_rect = modal.button_rects["yes"]
    consumed = modal.handle_click(yes_rect.center)
    assert consumed is True
    assert fired[0] is True
    assert modal.is_visible() is False


def test_confirm_modal_no_dismisses_without_callback_change():
    modal = ConfirmModal(pg.display.get_surface())
    modal.set_rect(pg.Rect(0, 0, 200, 100))
    fired = [False]
    modal.show("Resign?", on_yes=lambda: fired.__setitem__(0, True),
               yes_label="Resign", no_label="Cancel")
    modal.draw()
    no_rect = modal.button_rects["no"]
    modal.handle_click(no_rect.center)
    assert fired[0] is False
    assert modal.is_visible() is False


def test_confirm_modal_click_outside_buttons_does_nothing():
    modal = ConfirmModal(pg.display.get_surface())
    modal.set_rect(pg.Rect(0, 0, 200, 100))
    modal.show("Q?", on_yes=lambda: None)
    modal.draw()
    assert modal.handle_click((10, 5)) is False
    assert modal.is_visible() is True


def test_resign_button_shows_modal_and_does_not_resign():
    app = _new_app()
    app._on_resign()
    assert app.confirm_modal.is_visible() is True
    assert app.manual_result is None


def test_resign_modal_yes_completes_resign():
    """White on turn resigns -> compound code so subtitle reads 'by resignation'."""
    app = _new_app()
    app._on_resign()
    app.draw_frame()
    yes_rect = app.confirm_modal.button_rects["yes"]
    app.mouse_left_clicked(yes_rect.center)
    assert app.confirm_modal.is_visible() is False
    assert app.manual_result == "black_wins_by_resignation"


def test_resign_modal_no_keeps_game_active():
    app = _new_app()
    app._on_resign()
    app.draw_frame()
    no_rect = app.confirm_modal.button_rects["no"]
    app.mouse_left_clicked(no_rect.center)
    assert app.confirm_modal.is_visible() is False
    assert app.manual_result is None


def test_resign_blocks_other_clicks_while_modal_open():
    """With the confirm modal up, board clicks must not select a piece."""
    app = _new_app()
    app._on_resign()
    app.draw_frame()
    app.mouse_left_clicked((50, 50))
    assert app.board.selected_square is None


def test_draw_button_shows_modal_and_does_not_draw():
    app = _new_app()
    app._on_draw()
    assert app.confirm_modal.is_visible() is True
    assert app.manual_result is None


def test_draw_modal_yes_completes_draw():
    app = _new_app()
    app._on_draw()
    app.draw_frame()
    yes_rect = app.confirm_modal.button_rects["yes"]
    app.mouse_left_clicked(yes_rect.center)
    assert app.manual_result == "draw_agreement"


def test_drag_threshold_constant_is_six():
    assert DRAG_THRESHOLD_PX == 6


def test_begin_press_records_position(board):
    board.begin_press((100, 100))
    assert board._press_pos == (100, 100)


def test_motion_below_threshold_does_not_start_drag(board):
    board.handle_click(Square(6, 4))
    board.begin_press((10, 10))
    board.update_drag_motion((11, 11))
    assert board.dragging_from is None


def test_motion_past_threshold_starts_drag(board):
    board.handle_click(Square(6, 4))
    board.begin_press((10, 10))
    board.update_drag_motion((50, 50))
    assert board.dragging_from == Square(6, 4)


def test_drag_ignores_motion_when_no_selection(board):
    board.begin_press((10, 10))
    board.update_drag_motion((50, 50))
    assert board.dragging_from is None


def test_drag_blocked_during_pending_promotion(board):
    board.handle_click(Square(6, 4))
    board.pending_promotion_square = Square(0, 0)
    board.begin_press((10, 10))
    board.update_drag_motion((50, 50))
    assert board.dragging_from is None


def test_end_press_clears_state(board):
    board.handle_click(Square(6, 4))
    board.begin_press((10, 10))
    board.update_drag_motion((50, 50))
    assert board.dragging_from == Square(6, 4)
    was_dragging = board.end_press()
    assert was_dragging is True
    assert board.dragging_from is None
    assert board._press_pos is None


def test_drag_skips_origin_in_draw_pieces(board):
    board.handle_click(Square(6, 4))
    board.begin_press((10, 10))
    board.update_drag_motion((50, 50))
    visited = []
    original_cell_rect = board._cell_rect
    board._cell_rect = lambda r, c: visited.append((r, c)) or original_cell_rect(r, c)
    try:
        board.draw_pieces()
    finally:
        board._cell_rect = original_cell_rect
    assert (6, 4) not in visited


def test_dragged_piece_renders_at_cursor(board):
    board.handle_click(Square(6, 4))
    board.begin_press((10, 10))
    board.update_drag_motion((123, 234))
    board._draw_dragged_piece()
    assert board._drag_cursor == (123, 234)


def test_dragged_piece_no_op_without_drag_state(board):
    """Without dragging_from, the dragged-piece draw is a no-op even with a cursor set."""
    assert board.dragging_from is None
    board._drag_cursor = (10, 10)
    board._draw_dragged_piece()


def test_drag_and_drop_executes_legal_move():
    app = _new_app()
    e2_rect = app.board._cell_rect(6, 4)
    e4_rect = app.board._cell_rect(4, 4)
    app._mouse_left_pressed(e2_rect.center)
    midpoint = (e4_rect.centerx, e2_rect.centery - DRAG_THRESHOLD_PX * 4)
    app.board.update_drag_motion(midpoint)
    app._mouse_left_released(e4_rect.center)
    fire_animation(app.board)
    assert len(app.backend.move_history) == 1
    last = app.backend.move_history[-1].move
    assert last.from_sq == Square(6, 4)
    assert last.to_sq == Square(4, 4)


def test_drag_drop_skips_slide_animation():
    """A drag-landed move queues no slide animation -- the drag already showed arrival."""
    app = _new_app()
    e2_rect = app.board._cell_rect(6, 4)
    e4_rect = app.board._cell_rect(4, 4)
    app._mouse_left_pressed(e2_rect.center)
    app.board.update_drag_motion(e4_rect.center)
    app._mouse_left_released(e4_rect.center)
    assert len(app.backend.move_history) == 1
    assert app.board.animations == []


def test_click_click_still_animates():
    """Counter-test to drag-drop: a two-click (non-drag) move DOES animate."""
    app = _new_app()
    e2_rect = app.board._cell_rect(6, 4)
    e4_rect = app.board._cell_rect(4, 4)
    app.mouse_left_clicked(e2_rect.center)
    app.mouse_left_clicked(e4_rect.center)
    assert len(app.backend.move_history) == 1
    assert len(app.board.animations) == 1


def test_drag_below_threshold_falls_back_to_click_click():
    app = _new_app()
    e2_rect = app.board._cell_rect(6, 4)
    app._mouse_left_pressed(e2_rect.center)
    app.board.update_drag_motion((e2_rect.centerx + 1, e2_rect.centery))
    app._mouse_left_released((e2_rect.centerx + 1, e2_rect.centery))
    assert app.board.selected_square == Square(6, 4)
    assert len(app.backend.move_history) == 0


def test_captured_by_empty_at_start():
    backend = Backend()
    backend.new_game()
    assert captured_by(backend.move_history, PieceColor.WHITE) == []
    assert captured_by(backend.move_history, PieceColor.BLACK) == []


def test_captured_by_after_pawn_capture():
    """1. e4 d5 2. exd5 -- white's capture list holds the one black pawn."""
    backend = Backend()
    backend.new_game()
    backend.try_move(Square(6, 4), Square(4, 4))
    backend.try_move(Square(1, 3), Square(3, 3))
    backend.try_move(Square(4, 4), Square(3, 3))
    assert captured_by(backend.move_history, PieceColor.WHITE) == [PieceType.PAWN]
    assert captured_by(backend.move_history, PieceColor.BLACK) == []


def test_material_advantage_zero_at_start():
    backend = Backend()
    backend.new_game()
    assert material_advantage(backend.move_history, PieceColor.WHITE) == 0
    assert material_advantage(backend.move_history, PieceColor.BLACK) == 0


def test_material_advantage_after_pawn_capture():
    backend = Backend()
    backend.new_game()
    backend.try_move(Square(6, 4), Square(4, 4))
    backend.try_move(Square(1, 3), Square(3, 3))
    backend.try_move(Square(4, 4), Square(3, 3))
    assert material_advantage(backend.move_history, PieceColor.WHITE) == 1
    assert material_advantage(backend.move_history, PieceColor.BLACK) == -1


def test_material_advantage_after_queen_trade():
    backend = Backend()
    backend.state = [[None] * 8 for _ in range(8)]
    backend.state[0][0] = Piece(PieceType.KING, PieceColor.BLACK)
    backend.state[7][7] = Piece(PieceType.KING, PieceColor.WHITE)
    backend.state[4][4] = Piece(PieceType.QUEEN, PieceColor.WHITE)
    backend.state[3][4] = Piece(PieceType.QUEEN, PieceColor.BLACK)
    backend.state[2][3] = Piece(PieceType.PAWN, PieceColor.BLACK)
    backend.turn = PieceColor.WHITE
    backend.move_history = []
    backend.position_counts = Counter()
    backend.position_counts[backend._position_key()] = 1
    res1 = backend.try_move(Square(4, 4), Square(3, 4))
    assert res1.legal
    res2 = backend.try_move(Square(2, 3), Square(3, 4))
    assert res2.legal
    assert material_advantage(backend.move_history, PieceColor.WHITE) == 0
    assert material_advantage(backend.move_history, PieceColor.BLACK) == 0


def test_player_strip_set_state_accepts_captures():
    from frontend.panels.player_strip import PlayerStrip
    strip = PlayerStrip(pg.display.get_surface())
    strip.set_rect(pg.Rect(0, 0, 400, 40))
    strip.set_state("Alice", 100, True,
                    captured=[PieceType.PAWN], advantage=1,
                    captured_color=PieceColor.BLACK)
    assert strip.captured == [PieceType.PAWN]
    assert strip.advantage == 1
    assert strip.captured_color == PieceColor.BLACK


class _AdvantageFontSpy:
    def __init__(self, real):
        self._real = real
        self.rendered = []

    def render(self, text, *args, **kwargs):
        self.rendered.append(text)
        return self._real.render(text, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _make_strip(window, icons, captured, advantage):
    from frontend.panels.player_strip import PlayerStrip
    strip = PlayerStrip(window)
    strip.set_rect(pg.Rect(0, 0, 400, 40))
    strip.set_piece_icons(icons)
    strip.set_state("Alice", 100, True, captured=captured,
                    advantage=advantage, captured_color=PieceColor.BLACK)
    return strip


def _strip_region_bytes(window):
    region = window.subsurface(pg.Rect(0, 0, 400, 40)).copy()
    return pg.image.tostring(region, "RGBA")


def test_player_strip_draws_with_captures_smoke(board):
    """Captured PAWN+KNIGHT icons actually paint the strip's capture region."""
    window = pg.display.get_surface()
    icons = board.piece_images_scaled
    _make_strip(window, icons, [], 0).draw()
    before = _strip_region_bytes(window)
    _make_strip(window, icons, [PieceType.PAWN, PieceType.KNIGHT], 0).draw()
    assert _strip_region_bytes(window) != before


def test_player_strip_advantage_negative_not_rendered(board):
    """Only the leading side renders '+N'; a negative advantage draws no number."""
    from frontend.panels.player_strip import PlayerStrip
    leading = PlayerStrip(pg.display.get_surface())
    leading.set_rect(pg.Rect(0, 0, 400, 40))
    leading.set_piece_icons(board.piece_images_scaled)
    leading.set_state("Alice", 100, True, captured=[PieceType.PAWN],
                      advantage=3, captured_color=PieceColor.WHITE)
    leading.advantage_font = _AdvantageFontSpy(leading.advantage_font)
    leading.draw()
    assert leading.advantage_font.rendered == ["+3"]

    trailing = PlayerStrip(pg.display.get_surface())
    trailing.set_rect(pg.Rect(0, 0, 400, 40))
    trailing.set_piece_icons(board.piece_images_scaled)
    trailing.set_state("Alice", 100, True, captured=[PieceType.PAWN],
                       advantage=-3, captured_color=PieceColor.WHITE)
    trailing.advantage_font = _AdvantageFontSpy(trailing.advantage_font)
    trailing.draw()
    assert trailing.advantage_font.rendered == []


def test_f_key_flips_board():
    app = _new_app()
    initial = app.board.flipped
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_f, mod=0)
    app._handle_shortcut_key(event)
    assert app.board.flipped != initial


def test_ctrl_z_undoes_last_move():
    app = _new_app()
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    fire_animation(app.board)
    assert len(app.backend.move_history) == 1
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_z, mod=pg.KMOD_CTRL)
    app._handle_shortcut_key(event)
    assert len(app.backend.move_history) == 0


def test_z_without_ctrl_does_not_undo():
    app = _new_app()
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    fire_animation(app.board)
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_z, mod=0)
    handled = app._handle_shortcut_key(event)
    assert handled is False
    assert len(app.backend.move_history) == 1


def test_shortcuts_blocked_while_confirm_modal_open():
    app = _new_app()
    app._on_resign()
    initial_flipped = app.board.flipped
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_f, mod=0)
    handled = app._handle_shortcut_key(event)
    assert handled is False
    assert app.board.flipped == initial_flipped


def test_unrelated_key_returns_false():
    app = _new_app()
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_q, mod=0)
    assert app._handle_shortcut_key(event) is False
