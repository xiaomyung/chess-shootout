import pygame as pg

from tests.conftest import pygame_display
from chessshootout.domain.match import Match
from chessshootout.backend.pieces import PieceType, PieceColor, Piece
from chessshootout.backend.utils import Square
from chessshootout.frontend.board import Board
from chessshootout.frontend.board import board as board_module
from chessshootout.frontend.board.board import PIECE_SCALE
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import scale_floor


_pygame_init = pygame_display(780, 780)


def _board(position_moves=()):
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    match = Match()
    match.new_game()
    for fr, to in position_moves:
        match.try_move(Square(*fr), Square(*to))
    board = Board(win, match)
    board.load_assets()
    board.set_rect(pg.Rect(40, 40, 680, 680))
    return board, win


def _cell_has(win, rect, predicate):
    return any(
        predicate(win.get_at((x, y)))
        for x in range(rect.x, rect.right) for y in range(rect.y, rect.bottom)
    )


def test_arena_frame_insets_grid_and_caches_surface():
    board, _ = _board()
    assert board.frame_pad == scale_floor(26, board.scale, 18)
    assert board.board_offset_x >= board.rect.x + board.frame_pad - 2
    assert board.board_offset_y >= board.rect.y + board.frame_pad - 2
    assert board.cell_size > 0
    assert board._frame_surf is not None
    built = board._frame_surf
    board.draw_board()
    board.draw_board()
    assert board._frame_surf is built, "the plate surface is baked once, not per frame"
    grid_px = board.cell_size * board.SIZE
    assert board.board_offset_x + grid_px <= board.rect.right
    assert board.board_offset_y + grid_px <= board.rect.bottom


def test_plate_exposes_backdrop_through_cut_corner_and_borders_top_edge():
    board, win = _board()
    backdrop = (10, 20, 30)
    win.fill(backdrop)
    board.draw_board()
    top = board.rect.top
    cut_px = win.get_at((board.rect.right - 4, top + 2))[:3]
    assert tuple(cut_px) == backdrop, "the top-right cut must expose the window backdrop"
    edge_px = win.get_at((board.rect.centerx, top))[:3]
    assert tuple(edge_px) in (
        tuple(pg.Color(Colors.border)[:3]), tuple(pg.Color(Colors.surface)[:3])), \
        "the plate top edge (away from the cut) is opaque border/surface, not backdrop"


def test_coord_labels_fit_within_the_plate_margin_on_a_huge_board():
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    match = Match()
    match.new_game()
    board = Board(win, match)
    board.load_assets()
    board.set_rect(pg.Rect(0, 0, 1400, 1400))
    assert board.cell_size > 90, "sanity: cells are huge, so the raw coord font would overflow"
    assert board.file_labels_rendered[0].get_height() <= board.frame_pad
    assert board.rank_labels_rendered[0].get_height() <= board.frame_pad


def test_gutter_coords_rendered():
    board, _ = _board()
    assert len(board.rank_labels_rendered) == 8
    assert len(board.file_labels_rendered) == 8


def test_selection_ring_is_opaque_accent():
    board, win = _board()
    board.selected_square = Square(6, 4)
    board.draw_board()
    rect = board._cell_rect(6, 4)
    assert win.get_at((rect.centerx, rect.top + 1))[:3] == pg.Color(Colors.accent)[:3]


def test_legal_move_ring_drawn_on_empty_target():
    board, win = _board()
    board.selected_square = Square(6, 4)
    board.draw_board()
    target = board._cell_rect(4, 4)

    def reddish(c):
        return c[0] - c[1] > 40 and c[0] - c[2] > 40 and c[0] > 120

    assert _cell_has(win, target, reddish), "legal-move ring (accent) should appear on e4"


def test_capture_shows_orange_hitmarker_on_piece():
    board, win = _board([((6, 4), (4, 4)), ((1, 3), (3, 3))])
    board.selected_square = Square(4, 4)
    board.draw_board()
    target = board._cell_rect(3, 3)

    def orange(c):
        return c[0] - c[1] > 60 and c[0] - c[2] > 60 and c[0] > 150

    assert _cell_has(win, target, orange), "orange capture hitmarker should appear on d5"


def test_en_passant_marks_captured_pawn_and_landing_square():
    board, win = _board([((6, 4), (4, 4)), ((1, 0), (2, 0)),
                         ((4, 4), (3, 4)), ((1, 3), (3, 3))])
    assert board.backend.en_passant_target == Square(2, 3)
    board.selected_square = Square(3, 4)
    board.draw_board()
    captured = board._cell_rect(3, 3)
    landing = board._cell_rect(2, 3)

    def orange(c):
        return c[0] - c[1] > 60 and c[0] - c[2] > 60 and c[0] > 150

    def reddish(c):
        return c[0] - c[1] > 40 and c[0] - c[2] > 40 and c[0] > 120

    assert _cell_has(win, captured, orange), "hitmarker should mark the en-passant pawn"
    assert _cell_has(win, landing, reddish), "ring should mark the en-passant landing square"


def test_check_shows_red_flash_ring_and_orange_hitmarker():
    board, win = _board([((6, 5), (5, 5)), ((1, 4), (3, 4)),
                         ((6, 6), (4, 6)), ((0, 3), (4, 7))])
    assert board.match.is_in_check(PieceColor.WHITE)
    board.draw_board()
    king = board._cell_rect(7, 4)
    assert win.get_at((king.centerx, king.top + 1))[:3] == pg.Color(Colors.check)[:3]

    def orange(c):
        return c[0] - c[1] > 60 and c[0] - c[2] > 60 and c[0] > 150

    assert _cell_has(win, king, orange), "orange hitmarker should appear on the checked king"


def test_promotion_popover_has_four_options_and_routes_click(monkeypatch):
    board, _ = _board()
    board.pending_promotion_square = Square(1, 4)
    board.draw_board()
    assert set(board._promotion_rects) == {
        PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT,
    }
    picked = []
    monkeypatch.setattr(board, "pick_promotion", picked.append)
    board.pick_promotion_at(board._promotion_rects[PieceType.ROOK].center)
    assert picked == [PieceType.ROOK]


def test_promotion_popover_flips_left_and_stays_within_board_right_edge():
    """A small board leaves a panel-sized gap to its right; the popover must flip and stay
    within the board, measured against the board rect, not the whole window."""
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    match = Match()
    match.new_game()
    board = Board(win, match)
    board.load_assets()
    board.set_rect(pg.Rect(40, 40, 360, 360))
    board.pending_promotion_square = Square(1, 7)
    board.draw_board()
    sq_rect = board._cell_rect(1, 7)
    cells = board._promotion_rects.values()
    assert min(r.left for r in cells) < sq_rect.left, \
        "popover must flip to the left of a right-edge square"
    assert max(r.right for r in cells) <= board.rect.right, \
        "popover must not spill past the board's right edge into the panel area"


def test_promotion_popover_stays_within_board_left_edge():
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    match = Match()
    match.new_game()
    board = Board(win, match)
    board.load_assets()
    board.set_rect(pg.Rect(40, 40, 360, 360))
    board.pending_promotion_square = Square(1, 0)
    board.draw_board()
    sq_rect = board._cell_rect(1, 0)
    cells = board._promotion_rects.values()
    assert max(r.right for r in cells) > sq_rect.right, \
        "popover must sit to the right of a left-edge square"
    assert min(r.left for r in cells) >= board.rect.x, \
        "popover must not spill past the board's left edge"


def _promotion_panel_rect(board):
    cells = list(board._promotion_rects.values())
    pad = board.PROMOTION_PLATE_PAD
    left = min(c.left for c in cells) - pad
    top = min(c.top for c in cells) - pad
    right = max(c.right for c in cells) + pad
    bottom = max(c.bottom for c in cells) + pad
    return pg.Rect(left, top, right - left, bottom - top)


def test_promotion_picker_plate_is_cut_corner_command_rail_shell():
    board, win = _board()
    win.fill((7, 11, 17))
    board.pending_promotion_square = Square(1, 4)
    board.draw_board()
    panel = _promotion_panel_rect(board)
    strong = pg.Color(Colors.border_strong)[:3]
    assert win.get_at((panel.centerx, panel.top + 4))[:3] == pg.Color(Colors.surface)[:3], \
        "the plate interior is filled with the Command Rail surface color"
    assert win.get_at((panel.left, panel.centery))[:3] == strong, \
        "the plate carries a strong 1px border down its straight edges"
    assert win.get_at((panel.left, panel.top))[:3] == strong, \
        "the square top-left corner keeps the border"
    assert win.get_at((panel.right - 1, panel.top))[:3] != strong, \
        "the top-right corner is cut away, matching the board plate"


def test_promotion_picker_cells_are_raised_shells_with_hover_accent(monkeypatch):
    board, win = _board()
    board.pending_promotion_square = Square(1, 4)
    board.draw_board()
    rook = board._promotion_rects[PieceType.ROOK]
    border = pg.Color(Colors.border)[:3]
    accent = pg.Color(Colors.accent)[:3]
    assert win.get_at((rook.left, rook.centery))[:3] == border, \
        "a resting cell wears the muted border"
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: rook.center)
    board.draw_board()
    assert win.get_at((rook.left, rook.centery))[:3] == accent, \
        "the hovered cell swaps its border to accent as a selection affordance"
    assert win.get_at((rook.centerx, rook.top))[:3] == accent
    other = board._promotion_rects[PieceType.KNIGHT]
    assert win.get_at((other.left, other.centery))[:3] == border, \
        "un-hovered cells keep the muted border"


def test_promotion_picker_draws_key_hint_micro_labels():
    """Key hints sit on a dark scrim nameplate so they stay readable over white
    piece art: text_dim ink plus near-bg scrim pixels in the corner region."""
    board, win = _board()
    board.pending_promotion_square = Square(1, 4)
    board.draw_board()
    dim = pg.Color(Colors.text_dim)[:3]
    bg = pg.Color(Colors.bg)[:3]
    for ptype in (PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT):
        cell = board._promotion_rects[ptype]
        corner = pg.Rect(cell.right - 20, cell.bottom - 18, 20, 18)
        assert _cell_has(win, corner, lambda c: tuple(c[:3]) == dim), \
            "each cell shows a text_dim key hint in its bottom-right corner"
        assert _cell_has(win, corner,
                         lambda c: all(abs(c[i] - bg[i]) <= 24 for i in range(3))), \
            "the key hint rides a dark scrim plate for contrast"


def test_promotion_picker_shows_role_tags_that_brighten_on_hover(monkeypatch):
    board, win = _board()
    board.pending_promotion_square = Square(1, 4)
    board.draw_board()
    dim = pg.Color(Colors.text_dim)[:3]
    amber = pg.Color(Colors.amber)[:3]
    for ptype in (PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT):
        cell = board._promotion_rects[ptype]
        corner = pg.Rect(cell.left + 2, cell.top + 2, cell.width - 8, 18)
        assert _cell_has(win, corner, lambda c: tuple(c[:3]) == dim), \
            "each cell wears its role tag (BOSS/TANK/SNIPER/WILDCARD) in dim ink"
    knight = board._promotion_rects[PieceType.KNIGHT]
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: knight.center)
    board.draw_board()
    corner = pg.Rect(knight.left + 2, knight.top + 2, knight.width - 8, 18)
    assert _cell_has(win, corner, lambda c: tuple(c[:3]) == amber), \
        "the hovered cell's role tag brightens to amber"


def test_promotion_picker_role_tags_fit_at_the_minimum_option_size():
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    match = Match()
    match.new_game()
    board = Board(win, match)
    board.load_assets()
    board.set_rect(pg.Rect(40, 40, 360, 360))
    opt = max(board.PROMOTION_OPTION_SIZE_MIN,
              min(int(board.cell_size), board.PROMOTION_OPTION_SIZE_MAX))
    assert opt == board.PROMOTION_OPTION_SIZE_MIN, "sanity: the small board hits the floor"
    plate_pad = 2 * board.PROMO_PLATE_TEXT_PAD[0]
    assert 1 + plate_pad + board._promo_tag_font.size("WILDCARD")[0] <= opt - 1, \
        "the longest tag nameplate stays inside the cell at the smallest option size"


def test_flipped_cell_rect_mirrors():
    board, _ = _board()
    normal = board._cell_rect(0, 0)
    board.flipped = True
    flipped = board._cell_rect(0, 0)
    assert normal.topleft != flipped.topleft


def test_load_assets_shares_piece_surfaces_across_boards():
    """piece_images_original is populated from a process-wide cache keyed on
    (type, color), so a second Board.load_assets() call (the review board in
    Frontend, or a second test's Board) reuses the same decoded Surface
    instead of re-reading the PNG from disk."""
    board_module._PIECE_IMAGE_CACHE.clear()
    win = pg.display.get_surface()
    match = Match()
    match.new_game()
    key = (PieceType.QUEEN, PieceColor.WHITE)

    first = Board(win, match)
    first.load_assets()
    second = Board(win, match)
    second.load_assets()

    assert first.piece_images_original[key] is second.piece_images_original[key]
    assert len(board_module._PIECE_IMAGE_CACHE) == len(PieceType) * len(PieceColor)


def test_piece_image_cache_survives_a_pygame_reinit_cycle():
    """Unlike pygame Fonts (SDL_ttf handles freed by pg.quit()), decoded image
    Surfaces stay valid after a display quit/init cycle in the dummy driver --
    which is exactly what happens at every test-module boundary in the suite.
    This pins the assumption the piece-image cache relies on to safely live
    across those boundaries."""
    win = pg.display.get_surface()
    match = Match()
    match.new_game()
    board = Board(win, match)
    board.load_assets()
    key = (PieceType.QUEEN, PieceColor.WHITE)
    cached = board.piece_images_original[key]
    before = [cached.get_at((x, x)) for x in range(0, cached.get_width(), 64)]

    pg.quit()
    pg.init()
    pg.display.set_mode((780, 780))

    after = [cached.get_at((x, x)) for x in range(0, cached.get_width(), 64)]
    assert after == before
    assert sum(sum(px) for px in after) > 0, "pixel data must not have gone blank/garbage"


def _lone_piece_board(ptype, color, at):
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    match = Match()
    match.new_game()
    match.backend.state = [[None] * 8 for _ in range(8)]
    match.backend.state[at.row][at.col] = Piece(ptype, color)
    board = Board(win, match)
    board.load_assets()
    board.set_rect(pg.Rect(40, 40, 680, 680))
    return board, win


def _sq_dist(a, b):
    return sum((a[i] - b[i]) ** 2 for i in range(3))


def test_piece_scale_is_ninety_percent():
    assert PIECE_SCALE == 0.9


def test_white_sprite_fills_cell_with_scaled_centered_art():
    """The sprite surface is the full cell, but the visible art is scaled to
    PIECE_SCALE and centered -- verified on a white piece so no rim glow inflates
    the measured bounding box."""
    board, _ = _board()
    cell = board.cell_size
    key = (PieceType.QUEEN, PieceColor.WHITE)
    sprite = board.piece_images_scaled[key]
    assert sprite.get_size() == (cell, cell)
    bbox = board._sprite_geom[key]["bbox"]
    assert bbox.width <= cell * PIECE_SCALE + 2
    assert bbox.height <= cell * PIECE_SCALE + 2
    assert abs(bbox.centerx - cell / 2) <= 1.5
    assert abs(bbox.centery - cell / 2) <= 1.5


def test_white_piece_casts_no_resting_shadow():
    """Every pixel of a white piece's cell that lies outside its art bounding box
    is exactly the underlying tile colour -- no shadow, tint, or glow bleeds out."""
    at = Square(4, 4)
    board, win = _lone_piece_board(PieceType.PAWN, PieceColor.WHITE, at)
    board.draw_board()
    tile = tuple(pg.Color(Colors.white_tile)[:3])
    rect = board._cell_rect(at.row, at.col)
    art = board._sprite_geom[(PieceType.PAWN, PieceColor.WHITE)]["bbox"].move(rect.x, rect.y)
    offenders = [
        (x, y) for x in range(rect.x, rect.right) for y in range(rect.y, rect.bottom)
        if not art.collidepoint(x, y) and tuple(win.get_at((x, y))[:3]) != tile
    ]
    assert offenders == [], "no pixel outside the art may differ from the tile colour"


def test_black_piece_has_warm_rim_and_white_piece_has_none():
    board, _ = _board()
    rim = tuple(pg.Color(Colors.rim_light)[:3])
    white_tile = tuple(pg.Color(Colors.white_tile)[:3])
    black_tile = tuple(pg.Color(Colors.black_tile)[:3])

    def is_rim(px):
        if not 0 < px.a < 255:
            return False
        c = (px.r, px.g, px.b)
        return _sq_dist(c, rim) < _sq_dist(c, white_tile) and \
            _sq_dist(c, rim) < _sq_dist(c, black_tile)

    key_b = (PieceType.PAWN, PieceColor.BLACK)
    black = board.piece_images_scaled[key_b]
    bbox_b = board._sprite_geom[key_b]["bbox"]
    rim_hits = [
        (x, y) for x in range(black.get_width()) for y in range(black.get_height())
        if not bbox_b.collidepoint(x, y) and is_rim(black.get_at((x, y)))
    ]
    assert rim_hits, "a black piece must carry a warm rim glow just outside its art"

    key_w = (PieceType.PAWN, PieceColor.WHITE)
    white = board.piece_images_scaled[key_w]
    bbox_w = board._sprite_geom[key_w]["bbox"]
    lit = [
        (x, y) for x in range(white.get_width()) for y in range(white.get_height())
        if not bbox_w.collidepoint(x, y) and white.get_at((x, y)).a > 0
    ]
    assert lit == [], "a white piece must be fully transparent outside its art -- no glow"


def test_scaled_sprites_are_shared_across_boards_at_the_same_cell():
    board_module._SCALED_PIECE_CACHE.clear()
    win = pg.display.get_surface()
    match = Match()
    match.new_game()
    first = Board(win, match)
    first.load_assets()
    first.set_rect(pg.Rect(40, 40, 680, 680))
    second = Board(win, match)
    second.load_assets()
    second.set_rect(pg.Rect(40, 40, 680, 680))
    for key in ((PieceType.QUEEN, PieceColor.WHITE), (PieceType.KNIGHT, PieceColor.BLACK)):
        assert first.piece_images_scaled[key] is second.piece_images_scaled[key]
