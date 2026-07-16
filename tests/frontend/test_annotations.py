from collections import Counter
from unittest.mock import MagicMock

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.backend import Backend
from chessshootout.backend.pieces import Piece, PieceColor, PieceType
from chessshootout.backend.utils import Square
from chessshootout.frontend.board import Board
from chessshootout.frontend.board.annotations import Annotations
from chessshootout.frontend.visual.colors import Colors
from chessshootout.server.protocol import MAX_SHARED_ARROWS
from tests.helpers import make_app as _shared_make_app
from tests.helpers import start_single_screen


_pygame_init = pygame_display(1000, 800)


@pytest.fixture
def board():
    backend = Backend()
    backend.new_game()
    bd = Board(pg.display.get_surface(), backend)
    bd.load_assets()
    bd.set_rect(pg.Rect(0, 0, 400, 400))
    return bd


def make_app():
    return start_single_screen(_shared_make_app(900, 500), nickname="a",
                               time_minutes=None, increment_seconds=5, side="white")


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
    if not board.animations:
        return
    for a in list(board.animations):
        a.start_ms = pg.time.get_ticks() - 10_000
    board._draw_animations()


def _cell_center(board, sq):
    rect = board._cell_rect(sq.row, sq.col)
    return rect.center


def _arrow_region(board, sq):
    rect = board._cell_rect(sq.row, sq.col)
    return pg.Rect(rect.centerx - 8, rect.centery - 8, 16, 16).clip(board.window.get_rect())


def _arrow_marks_cells(board, squares):
    """Pixel-diff: which cells gain pixels when the arrows/drag-preview are drawn."""
    win = board.window

    def snapshot():
        board.annotations._arrow_cache = None
        win.fill((0, 0, 0))
        board.draw_board()
        return {sq: pg.image.tobytes(win.subsurface(_arrow_region(board, sq)), "RGB")
                for sq in squares}

    with_arrows = snapshot()
    arrows, drag = board.arrows, board.annotations._right_drag_start_square
    board.arrows, board.annotations._right_drag_start_square = [], None
    without = snapshot()
    board.arrows, board.annotations._right_drag_start_square = arrows, drag
    board.annotations._arrow_cache = None
    return {sq: with_arrows[sq] != without[sq] for sq in squares}


def _spy_cell_rects(board, monkeypatch):
    seen = []
    orig = board._cell_rect

    def spy(row, col):
        seen.append(Square(row, col))
        return orig(row, col)

    monkeypatch.setattr(board, "_cell_rect", spy)
    return seen


def _spy_arrow_geometry(monkeypatch):
    circle_centers = []
    arrow_tips = []
    line_segments = []
    orig_circle = pg.draw.circle
    orig_polygon = pg.draw.polygon
    orig_line = pg.draw.line

    def circle_spy(surface, color, center, radius, width=0):
        circle_centers.append(tuple(center))
        return orig_circle(surface, color, center, radius, width)

    def polygon_spy(surface, color, points, width=0):
        arrow_tips.append(tuple(points[0]))
        return orig_polygon(surface, color, points, width)

    def line_spy(surface, color, start, end, width=1):
        line_segments.append((tuple(start), tuple(end)))
        return orig_line(surface, color, start, end, width)

    monkeypatch.setattr(pg.draw, "circle", circle_spy)
    monkeypatch.setattr(pg.draw, "polygon", polygon_spy)
    monkeypatch.setattr(pg.draw, "line", line_spy)
    return circle_centers, arrow_tips, line_segments


def _assert_arrow_drawn(board, from_sq, to_sq):
    marks = _arrow_marks_cells(board, [from_sq, to_sq])
    assert marks[from_sq], "arrow should mark its from-square"
    assert marks[to_sq], "arrow should mark its to-square"


def test_toggle_highlight_adds(board):
    board.toggle_highlight(Square(4, 4))
    assert Square(4, 4) in board.highlighted_squares


def test_toggle_highlight_removes(board):
    board.toggle_highlight(Square(4, 4))
    board.toggle_highlight(Square(4, 4))
    assert Square(4, 4) not in board.highlighted_squares


def test_toggle_arrow_adds(board):
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    assert (Square(6, 0), Square(4, 0)) in board.arrows


def test_toggle_arrow_removes_on_second_call(board):
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    assert (Square(6, 0), Square(4, 0)) not in board.arrows


def test_toggle_arrow_direction_specific(board):
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    board.toggle_arrow(Square(4, 0), Square(6, 0))
    assert len(board.arrows) == 2
    assert (Square(6, 0), Square(4, 0)) in board.arrows
    assert (Square(4, 0), Square(6, 0)) in board.arrows


def test_is_square_annotated_via_highlight(board):
    board.toggle_highlight(Square(4, 4))
    assert board.is_square_annotated(Square(4, 4)) is True
    assert board.is_square_annotated(Square(0, 0)) is False


def test_is_square_annotated_via_arrow_endpoints(board):
    board.toggle_arrow(Square(6, 4), Square(4, 4))
    assert board.is_square_annotated(Square(6, 4)) is True
    assert board.is_square_annotated(Square(4, 4)) is True
    assert board.is_square_annotated(Square(5, 4)) is False


def test_is_square_annotated_neutral_returns_false(board):
    assert board.is_square_annotated(Square(3, 3)) is False


def test_clear_annotations_empties_state(board):
    board.toggle_highlight(Square(4, 4))
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    board.annotations._right_drag_start_square = Square(2, 2)
    board.clear_annotations()
    assert board.highlighted_squares == set()
    assert board.arrows == []
    assert board.annotations._right_drag_start_square is None


def post_event(event_type, **kwargs):
    pg.event.post(pg.event.Event(event_type, kwargs))


def test_right_click_down_on_board_sets_drag_start():
    app = make_app()
    sq = Square(6, 4)
    rect = app.game.board._cell_rect(sq.row, sq.col)
    post_event(pg.MOUSEBUTTONDOWN, button=3, pos=rect.center)
    app.input_router.check_events()
    assert app.game.board.annotations._right_drag_start_square == sq


def test_right_click_down_off_board_no_drag_start():
    app = make_app()
    post_event(pg.MOUSEBUTTONDOWN, button=3, pos=(2000, 2000))
    app.input_router.check_events()
    assert app.game.board.annotations._right_drag_start_square is None


def test_right_click_during_left_drag_does_not_start_highlight():
    """Right-click is reserved for premove chaining during a left-drag; it must
    NOT register a highlight start, even when the chain extension is rejected."""
    app = make_app()
    app.game.board.dragging_from = Square(6, 4)
    other_sq = Square(2, 2)
    rect = app.game.board._cell_rect(other_sq.row, other_sq.col)
    post_event(pg.MOUSEBUTTONDOWN, button=3, pos=rect.center)
    app.input_router.check_events()
    assert app.game.board.annotations._right_drag_start_square is None
    post_event(pg.MOUSEBUTTONUP, button=3, pos=rect.center)
    app.input_router.check_events()
    assert other_sq not in app.game.board.highlighted_squares


def test_right_click_release_same_square_toggles_highlight():
    app = make_app()
    sq = Square(6, 4)
    rect = app.game.board._cell_rect(sq.row, sq.col)
    post_event(pg.MOUSEBUTTONDOWN, button=3, pos=rect.center)
    post_event(pg.MOUSEBUTTONUP, button=3, pos=rect.center)
    app.input_router.check_events()
    assert sq in app.game.board.highlighted_squares
    assert app.game.board.annotations._right_drag_start_square is None


def test_right_click_release_different_square_creates_arrow():
    app = make_app()
    a = Square(6, 4)
    b = Square(4, 4)
    a_rect = app.game.board._cell_rect(a.row, a.col)
    b_rect = app.game.board._cell_rect(b.row, b.col)
    post_event(pg.MOUSEBUTTONDOWN, button=3, pos=a_rect.center)
    post_event(pg.MOUSEBUTTONUP, button=3, pos=b_rect.center)
    app.input_router.check_events()
    assert (a, b) in app.game.board.arrows
    assert app.game.board.annotations._right_drag_start_square is None


def test_right_click_release_off_board_cancels():
    app = make_app()
    a = Square(6, 4)
    a_rect = app.game.board._cell_rect(a.row, a.col)
    post_event(pg.MOUSEBUTTONDOWN, button=3, pos=a_rect.center)
    post_event(pg.MOUSEBUTTONUP, button=3, pos=(2000, 2000))
    app.input_router.check_events()
    assert app.game.board.highlighted_squares == set()
    assert app.game.board.arrows == []
    assert app.game.board.annotations._right_drag_start_square is None


def test_right_click_on_already_highlighted_removes_it():
    app = make_app()
    sq = Square(6, 4)
    app.game.board.toggle_highlight(sq)
    assert sq in app.game.board.highlighted_squares
    rect = app.game.board._cell_rect(sq.row, sq.col)
    post_event(pg.MOUSEBUTTONDOWN, button=3, pos=rect.center)
    post_event(pg.MOUSEBUTTONUP, button=3, pos=rect.center)
    app.input_router.check_events()
    assert sq not in app.game.board.highlighted_squares


def test_right_click_drag_twice_toggles_arrow_off():
    app = make_app()
    a = Square(6, 4)
    b = Square(4, 4)
    a_rect = app.game.board._cell_rect(a.row, a.col)
    b_rect = app.game.board._cell_rect(b.row, b.col)
    for _ in range(2):
        post_event(pg.MOUSEBUTTONDOWN, button=3, pos=a_rect.center)
        post_event(pg.MOUSEBUTTONUP, button=3, pos=b_rect.center)
        app.input_router.check_events()
    assert (a, b) not in app.game.board.arrows


def test_right_click_in_menu_mode_is_noop():
    from chessshootout.frontend.frontend import Frontend
    app = Frontend(900, 500)
    app.sound_manager = MagicMock()
    rect = app.game.board._cell_rect(0, 0)
    post_event(pg.MOUSEBUTTONDOWN, button=3, pos=rect.center)
    post_event(pg.MOUSEBUTTONUP, button=3, pos=rect.center)
    app.input_router.check_events()
    assert app.game.board.highlighted_squares == set()


def test_left_click_neutral_square_clears_annotations():
    app = make_app()
    app.game.board.toggle_highlight(Square(4, 4))
    rect = app.game.board._cell_rect(7, 7)
    post_event(pg.MOUSEBUTTONDOWN, button=1, pos=rect.center)
    app.input_router.check_events()
    assert app.game.board.highlighted_squares == set()


def test_left_click_on_highlighted_square_preserves_annotations():
    app = make_app()
    sq = Square(4, 4)
    app.game.board.toggle_highlight(sq)
    rect = app.game.board._cell_rect(sq.row, sq.col)
    post_event(pg.MOUSEBUTTONDOWN, button=1, pos=rect.center)
    app.input_router.check_events()
    assert sq in app.game.board.highlighted_squares


@pytest.mark.parametrize(
    "clicked_endpoint",
    [
        pytest.param("from", id="click_arrow_from_endpoint_preserves"),
        pytest.param("to", id="click_arrow_to_endpoint_preserves"),
    ],
)
def test_left_click_on_arrow_endpoint_preserves(clicked_endpoint):
    app = make_app()
    a = Square(6, 4)
    b = Square(4, 4)
    app.game.board.toggle_arrow(a, b)
    target = a if clicked_endpoint == "from" else b
    rect = app.game.board._cell_rect(target.row, target.col)
    post_event(pg.MOUSEBUTTONDOWN, button=1, pos=rect.center)
    app.input_router.check_events()
    assert (a, b) in app.game.board.arrows


def test_left_click_off_board_does_not_clear():
    app = make_app()
    app.game.board.toggle_highlight(Square(4, 4))
    post_event(pg.MOUSEBUTTONDOWN, button=1, pos=(2000, 2000))
    app.input_router.check_events()
    assert Square(4, 4) in app.game.board.highlighted_squares


def test_normal_move_clears_annotations(board):
    board.toggle_highlight(Square(0, 0))
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert board.highlighted_squares == set()


def test_capture_move_clears_annotations(board):
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(4, 4): Piece(PieceType.QUEEN, PieceColor.WHITE),
        Square(2, 4): Piece(PieceType.PAWN, PieceColor.BLACK),
    })
    board.toggle_highlight(Square(7, 7))
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    board.handle_click(Square(4, 4))
    board.handle_click(Square(2, 4))
    assert board.highlighted_squares == set()
    assert board.arrows == []


def test_castle_move_clears_annotations(board):
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(7, 7): Piece(PieceType.ROOK, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
    })
    board.backend.castling_rights = {"WK": True, "WQ": False, "BK": False, "BQ": False}
    board.toggle_highlight(Square(0, 0))
    board.handle_click(Square(7, 4))
    board.handle_click(Square(7, 6))
    assert board.highlighted_squares == set()


def test_promotion_pending_clears_annotations(board):
    """Cleared at _start_move_animation, before the promotion picker shows."""
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(1, 0): Piece(PieceType.PAWN, PieceColor.WHITE),
    })
    board.toggle_highlight(Square(4, 4))
    board.handle_click(Square(1, 0))
    board.handle_click(Square(0, 0))
    assert board.highlighted_squares == set()


def test_premove_fire_clears_annotations(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert len(board.premoves) == 1
    board.toggle_highlight(Square(0, 0))
    board.toggle_arrow(Square(7, 7), Square(0, 7))
    board.backend.turn = PieceColor.WHITE
    board.try_apply_next_premove()
    assert board.highlighted_squares == set()
    assert board.arrows == []


def test_undo_clears_annotations():
    app = make_app()
    app.game.board.handle_click(Square(6, 4))
    app.game.board.handle_click(Square(4, 4))
    fire_animation(app.game.board)
    app.game.board.toggle_highlight(Square(0, 0))
    app.game.board.toggle_arrow(Square(6, 0), Square(4, 0))
    app.game._on_undo()
    assert app.game.board.highlighted_squares == set()
    assert app.game.board.arrows == []


def test_resign_clears_annotations():
    app = make_app()
    app.game.board.toggle_highlight(Square(0, 0))
    app.game._perform_resign()
    assert app.game.board.highlighted_squares == set()


def test_draw_clears_annotations():
    app = make_app()
    app.game.board.toggle_arrow(Square(6, 0), Square(4, 0))
    app.game._perform_draw()
    assert app.game.board.arrows == []


def test_new_game_clears_annotations():
    app = make_app()
    app.game.board.toggle_highlight(Square(4, 4))
    app.game.board.toggle_arrow(Square(6, 0), Square(4, 0))
    app._on_new_game()
    assert app.game.board.highlighted_squares == set()
    assert app.game.board.arrows == []


def test_back_to_menu_clears_annotations():
    app = make_app()
    app.game.board.toggle_highlight(Square(4, 4))
    app._on_back_to_menu()
    assert app.game.board.highlighted_squares == set()


def test_draw_annotation_highlights_renders_each_square(board, monkeypatch):
    """Each highlighted square's cell is resolved and tinted; the pixel under
    the cell changes from the cleared background."""
    squares = [Square(4, 4), Square(3, 3)]
    for sq in squares:
        board.toggle_highlight(sq)
    centers = {_cell_center(board, sq) for sq in squares}
    board.window.fill((0, 0, 0))
    seen = _spy_cell_rects(board, monkeypatch)
    board._draw_annotation_highlights()
    assert set(seen) == set(squares)
    for center in centers:
        assert board.window.get_at(center) != (0, 0, 0, 255)


def test_draw_annotation_highlights_empty_draws_nothing(board, monkeypatch):
    board.window.fill((0, 0, 0))
    seen = _spy_cell_rects(board, monkeypatch)
    board._draw_annotation_highlights()
    assert seen == []
    assert board.window.get_at(_cell_center(board, Square(4, 4))) == (0, 0, 0, 255)


@pytest.mark.parametrize(
    "from_sq, to_sq",
    [
        pytest.param(Square(6, 0), Square(4, 0), id="vertical_arrow"),
        pytest.param(Square(7, 0), Square(0, 7), id="diagonal_arrow"),
        pytest.param(Square(4, 0), Square(4, 7), id="horizontal_arrow"),
    ],
)
def test_draw_arrows_renders_from_and_to(board, from_sq, to_sq):
    board.toggle_arrow(from_sq, to_sq)
    _assert_arrow_drawn(board, from_sq, to_sq)


def test_draw_arrows_renders_every_arrow(board):
    """All queued arrows are rendered, each marking its from- and to-square."""
    pairs = [
        (Square(6, 0), Square(4, 0)),
        (Square(7, 0), Square(0, 7)),
        (Square(4, 0), Square(4, 7)),
    ]
    for from_sq, to_sq in pairs:
        board.toggle_arrow(from_sq, to_sq)
    cells = [sq for pair in pairs for sq in pair]
    marks = _arrow_marks_cells(board, cells)
    assert all(marks[sq] for sq in cells)


@pytest.mark.parametrize(
    "dr, dc",
    [
        pytest.param(-2, -1, id="up2_left1"),
        pytest.param(-2, 1, id="up2_right1"),
        pytest.param(-1, -2, id="up1_left2"),
        pytest.param(-1, 2, id="up1_right2"),
        pytest.param(1, -2, id="down1_left2"),
        pytest.param(1, 2, id="down1_right2"),
        pytest.param(2, -1, id="down2_left1"),
        pytest.param(2, 1, id="down2_right1"),
    ],
)
def test_draw_knight_arrow_renders_with_elbow(board, dr, dc):
    """A knight arrow draws an L: the shaft routes through the elbow corner,
    so the from-, corner-, and to-squares all gain arrow pixels."""
    center = Square(4, 4)
    target = Square(center.row + dr, center.col + dc)
    corner = Annotations._knight_arrow_corner(center, target)
    board.toggle_arrow(center, target)
    marks = _arrow_marks_cells(board, [center, corner, target])
    assert marks[center] and marks[corner] and marks[target]


@pytest.mark.parametrize(
    "from_sq, to_sq",
    [
        pytest.param(Square(7, 6), Square(5, 5), id="knight_elbow"),
        pytest.param(Square(7, 0), Square(0, 7), id="long_diagonal"),
        pytest.param(Square(6, 0), Square(4, 0), id="short_straight"),
    ],
)
def test_arrow_overlap_does_not_double_alpha(board, from_sq, to_sq):
    """Shaft capsules and the head are composited with BLEND_RGBA_MAX, so where
    they overlap (knight elbow, shaft/head junction) the alpha takes the max
    instead of summing — no opaque seam. The peak alpha anywhere on the arrow
    must equal the color's own alpha and never exceed it; the summing bug would
    clamp the overlap to 255."""
    max_a = pg.Color(Colors.annotation_arrow).a
    assert max_a < 255
    layer = pg.Surface(board.rect.size, pg.SRCALPHA)
    board.annotations._render_arrow(layer, 1, from_sq, to_sq, Colors.annotation_arrow)
    w, h = layer.get_size()
    peak = max(layer.get_at((x, y)).a for x in range(w) for y in range(h))
    assert peak == max_a, f"overlap summed alpha to {peak}, expected exactly {max_a}"


@pytest.mark.parametrize(
    "from_sq, to_sq, expected",
    [
        pytest.param(Square(7, 6), Square(5, 5), Square(5, 6),
                     id="long_vertical_first_g1_f3"),
        pytest.param(Square(4, 3), Square(3, 5), Square(4, 5),
                     id="long_horizontal_first_d4_f5"),
        pytest.param(Square(4, 4), Square(6, 3), Square(6, 4),
                     id="negative_dirs_e4_d6"),
        pytest.param(Square(4, 4), Square(2, 3), Square(2, 4), id="up2_left1"),
        pytest.param(Square(4, 4), Square(2, 5), Square(2, 4), id="up2_right1"),
        pytest.param(Square(4, 4), Square(3, 2), Square(4, 2), id="up1_left2"),
        pytest.param(Square(4, 4), Square(3, 6), Square(4, 6), id="up1_right2"),
        pytest.param(Square(4, 4), Square(5, 2), Square(4, 2), id="down1_left2"),
        pytest.param(Square(4, 4), Square(5, 6), Square(4, 6), id="down1_right2"),
        pytest.param(Square(4, 4), Square(6, 5), Square(6, 4), id="down2_right1"),
        pytest.param(Square(6, 4), Square(4, 4), None, id="rook_move_is_none"),
        pytest.param(Square(0, 0), Square(7, 7), None, id="bishop_move_is_none"),
        pytest.param(Square(4, 4), Square(4, 4), None, id="same_square_is_none"),
        pytest.param(Square(4, 4), Square(2, 2), None, id="diagonal_is_none"),
    ],
)
def test_knight_arrow_corner(from_sq, to_sq, expected):
    assert Annotations._knight_arrow_corner(from_sq, to_sq) == expected


def test_draw_drag_preview_arrow_no_drag_is_noop(board, monkeypatch):
    """No drag start -> nothing is rendered (no caps, no head, no shaft)."""
    board.annotations._right_drag_start_square = None
    circle_centers, arrow_tips, line_segments = _spy_arrow_geometry(monkeypatch)
    board._draw_arrows()
    assert circle_centers == []
    assert arrow_tips == []
    assert line_segments == []


def test_draw_drag_preview_arrow_with_active_drag(board, monkeypatch):
    """An active right-drag previews an arrow from the start square to the
    square under the mouse."""
    start = Square(6, 4)
    end = Square(4, 4)
    board.annotations._right_drag_start_square = start
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: _cell_center(board, end))
    marks = _arrow_marks_cells(board, [start, end])
    assert marks[start] and marks[end]


def test_draw_drag_preview_arrow_same_square_is_noop(board, monkeypatch):
    """Hovering back over the start square previews nothing."""
    start = Square(6, 4)
    board.annotations._right_drag_start_square = start
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: _cell_center(board, start))
    circle_centers, arrow_tips, line_segments = _spy_arrow_geometry(monkeypatch)
    board._draw_arrows()
    assert circle_centers == []
    assert arrow_tips == []
    assert line_segments == []


def test_draw_full_board_with_annotations_renders_all_layers(board, monkeypatch):
    """The full board draw path emits the highlight cells, the committed arrow,
    and the in-progress drag-preview arrow together without dropping any layer."""
    highlights = [Square(3, 3), Square(5, 5)]
    board.draw_board()
    plain_pixels = {sq: board.window.get_at(_cell_center(board, sq)) for sq in highlights}
    for sq in highlights:
        board.toggle_highlight(sq)
    arrow_from, arrow_to = Square(6, 4), Square(4, 4)
    board.toggle_arrow(arrow_from, arrow_to)
    drag_start, drag_end = Square(0, 0), Square(2, 2)
    board.annotations._right_drag_start_square = drag_start
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: _cell_center(board, drag_end))
    marks = _arrow_marks_cells(board, [arrow_from, arrow_to, drag_start, drag_end])
    assert all(marks.values())
    board.draw_board()
    for sq in highlights:
        assert board.window.get_at(_cell_center(board, sq)) != plain_pixels[sq]


def test_highlights_and_arrows_coexist(board):
    board.toggle_highlight(Square(4, 4))
    board.toggle_highlight(Square(3, 3))
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    board.toggle_arrow(Square(6, 7), Square(4, 7))
    assert len(board.highlighted_squares) == 2
    assert len(board.arrows) == 2


def test_can_re_annotate_after_clear(board):
    board.toggle_highlight(Square(4, 4))
    board.clear_annotations()
    board.toggle_highlight(Square(4, 4))
    assert Square(4, 4) in board.highlighted_squares


def test_selection_only_does_not_clear_annotations(board):
    board.toggle_highlight(Square(4, 4))
    board.handle_click(Square(6, 4))
    assert Square(4, 4) in board.highlighted_squares


def test_premove_queueing_does_not_clear_annotations(board):
    """Premove enqueues without firing animation, so highlights persist."""
    board.backend.turn = PieceColor.BLACK
    board.toggle_highlight(Square(4, 4))
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert len(board.premoves) == 1
    assert Square(4, 4) in board.highlighted_squares


def _seed_opp_annotations(board, hi=Square(2, 2), arrow=(Square(6, 6), Square(5, 5))):
    board.annotations.opp_highlighted_squares.add(hi)
    board.annotations.opp_arrows.append(arrow)
    return hi, arrow


def test_local_move_clears_own_and_opp_annotations(board):
    board.toggle_highlight(Square(0, 0))
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    _seed_opp_annotations(board)
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert board.highlighted_squares == set()
    assert board.arrows == []
    assert board.annotations.opp_highlighted_squares == set()
    assert board.annotations.opp_arrows == []


def test_remote_move_clears_own_and_opp_annotations(board):
    board.match.try_move(Square(6, 4), Square(4, 4))
    board.toggle_highlight(Square(0, 0))
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    _seed_opp_annotations(board)
    board.animate_remote_move(Square(6, 4), Square(4, 4))
    assert board.highlighted_squares == set()
    assert board.arrows == []
    assert board.annotations.opp_highlighted_squares == set()
    assert board.annotations.opp_arrows == []


def test_review_browse_click_clears_own_keeps_opp(board):
    board.toggle_highlight(Square(4, 4))
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    opp_hi, opp_arrow = _seed_opp_annotations(board)
    board.review_ply = 0
    board.handle_click(Square(3, 3))
    assert board.highlighted_squares == set()
    assert board.arrows == []
    assert board.annotations.opp_highlighted_squares == {opp_hi}
    assert board.annotations.opp_arrows == [opp_arrow]


def test_right_drag_highlight_does_not_touch_opp(board):
    opp_hi, opp_arrow = _seed_opp_annotations(board)
    sq = Square(6, 4)
    board.begin_right_press(_cell_center(board, sq))
    board.end_right_press(_cell_center(board, sq))
    assert sq in board.highlighted_squares
    assert board.annotations.opp_highlighted_squares == {opp_hi}
    assert board.annotations.opp_arrows == [opp_arrow]


def test_right_drag_arrow_does_not_touch_opp(board):
    opp_hi, opp_arrow = _seed_opp_annotations(board)
    a, b = Square(6, 4), Square(4, 4)
    board.begin_right_press(_cell_center(board, a))
    board.end_right_press(_cell_center(board, b))
    assert (a, b) in board.arrows
    assert board.annotations.opp_highlighted_squares == {opp_hi}
    assert board.annotations.opp_arrows == [opp_arrow]


def test_end_right_press_highlight_descriptor(board):
    sq = Square(6, 4)
    center = _cell_center(board, sq)
    board.begin_right_press(center)
    assert board.end_right_press(center) == ("highlight", sq, True)
    board.begin_right_press(center)
    assert board.end_right_press(center) == ("highlight", sq, False)


def test_end_right_press_arrow_descriptor(board):
    a, b = Square(6, 4), Square(4, 4)
    board.begin_right_press(_cell_center(board, a))
    assert board.end_right_press(_cell_center(board, b)) == ("arrow", a, b, True)
    board.begin_right_press(_cell_center(board, a))
    assert board.end_right_press(_cell_center(board, b)) == ("arrow", a, b, False)


def test_end_right_press_without_drag_returns_none(board):
    board.annotations._right_drag_start_square = None
    assert board.end_right_press(_cell_center(board, Square(4, 4))) is None


def test_end_right_press_off_board_returns_none(board):
    board.begin_right_press(_cell_center(board, Square(6, 4)))
    assert board.end_right_press((5000, 5000)) is None


def test_own_arrow_cap_blocks_add_beyond_max(board):
    squares = [Square(r, c) for r in range(8) for c in range(8)]
    pairs = [(a, b) for a in squares for b in squares if a != b]
    for a, b in pairs[:MAX_SHARED_ARROWS]:
        assert board.toggle_arrow(a, b) is True
    assert len(board.arrows) == MAX_SHARED_ARROWS
    extra_a, extra_b = pairs[MAX_SHARED_ARROWS]
    assert board.toggle_arrow(extra_a, extra_b) is False
    assert len(board.arrows) == MAX_SHARED_ARROWS
    assert (extra_a, extra_b) not in board.arrows


def test_own_arrow_toggle_off_still_works_at_cap(board):
    squares = [Square(r, c) for r in range(8) for c in range(8)]
    pairs = [(a, b) for a in squares for b in squares if a != b]
    for a, b in pairs[:MAX_SHARED_ARROWS]:
        board.toggle_arrow(a, b)
    first_a, first_b = pairs[0]
    assert board.toggle_arrow(first_a, first_b) is False
    assert (first_a, first_b) not in board.arrows
    assert len(board.arrows) == MAX_SHARED_ARROWS - 1


def test_clear_annotations_keeps_opp(board):
    """Own-only clear() leaves the opponent's shared annotations intact."""
    board.toggle_highlight(Square(4, 4))
    opp_hi, opp_arrow = _seed_opp_annotations(board)
    board.clear_annotations()
    assert board.highlighted_squares == set()
    assert board.annotations.opp_highlighted_squares == {opp_hi}
    assert board.annotations.opp_arrows == [opp_arrow]


def test_clear_opp_only_clears_opp(board):
    board.toggle_highlight(Square(4, 4))
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    _seed_opp_annotations(board)
    board.annotations.clear_opp()
    assert board.highlighted_squares == {Square(4, 4)}
    assert board.arrows == [(Square(6, 0), Square(4, 0))]
    assert board.annotations.opp_highlighted_squares == set()
    assert board.annotations.opp_arrows == []


def test_clear_all_clears_own_and_opp(board):
    board.toggle_highlight(Square(4, 4))
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    _seed_opp_annotations(board)
    board.annotations._right_drag_start_square = Square(1, 1)
    board.clear_all_annotations()
    assert board.highlighted_squares == set()
    assert board.arrows == []
    assert board.annotations.opp_highlighted_squares == set()
    assert board.annotations.opp_arrows == []
    assert board.annotations._right_drag_start_square is None


def test_own_and_opp_highlights_use_distinct_hues(board):
    """Own highlights read warm (amber), opponent highlights read cool (blue)."""
    own_sq, opp_sq = Square(4, 4), Square(3, 3)
    board.toggle_highlight(own_sq)
    board.annotations.opp_highlighted_squares.add(opp_sq)
    board.window.fill((0, 0, 0))
    board._draw_annotation_highlights()
    own = board.window.get_at(_cell_center(board, own_sq))
    opp = board.window.get_at(_cell_center(board, opp_sq))
    assert own.r > own.b, "own highlight reads warm"
    assert opp.b > opp.r and opp.b > opp.g, "opp highlight reads blue"


def _opp_arrow_changed_pixels(board, sq):
    """Pixels in a cell region that the opp arrow introduces (with vs without)."""
    win = board.window
    region = _arrow_region(board, sq)

    def frame():
        board.annotations._arrow_cache = None
        win.fill((0, 0, 0))
        board.draw_board()
        return [win.get_at((region.x + x, region.y + y))
                for x in range(region.width) for y in range(region.height)]

    with_arrow = frame()
    saved = board.annotations.opp_arrows
    board.annotations.opp_arrows = []
    without = frame()
    board.annotations.opp_arrows = saved
    board.annotations._arrow_cache = None
    return [wp for wp, bp in zip(with_arrow, without) if wp != bp]


def test_opp_arrow_adds_blueish_pixels(board):
    from_sq, to_sq = Square(6, 0), Square(4, 0)
    board.annotations.opp_arrows.append((from_sq, to_sq))
    changed = _opp_arrow_changed_pixels(board, to_sq)
    assert changed, "opp arrow should mark its to-square"
    assert any(c.b > c.r and c.b > c.g for c in changed), "opp arrow pixels read blue"


def test_opp_arrow_renders_alongside_own_arrow(board):
    board.toggle_arrow(Square(6, 7), Square(4, 7))
    board.annotations.opp_arrows.append((Square(6, 0), Square(4, 0)))
    own_changed = _arrow_marks_cells(board, [Square(6, 7), Square(4, 7)])
    assert all(own_changed.values()), "own arrow still rendered when opp arrows exist"
    opp_changed = _opp_arrow_changed_pixels(board, Square(4, 0))
    assert any(c.b > c.r and c.b > c.g for c in opp_changed)
