import math
from collections.abc import Callable
from itertools import product
from typing import Any, cast

import pygame as pg

from chessshootout.backend.backend import Backend
from chessshootout.backend.pseudo_legal import piece_can_pseudo_reach, king_square, checking_square
from chessshootout.backend.utils import BOARD_SIZE, HistoryEntry, Move, MoveResult, Square
from chessshootout.frontend.board.annotations import Annotations
from chessshootout.frontend.board.drag import DragPhysics
from chessshootout.frontend.visual.animation import PieceAnimation
from chessshootout.frontend.visual.cache import (
    new_cache, new_size_cache, memoized_surface,
)
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import (
    supersample, smoothstep, scale_floor, cut_rect_surface, soft_blur,
)
from chessshootout.frontend.visual.effects import EffectManager
from chessshootout.frontend.visual.icons import piece_png_path
from chessshootout.domain.match import Match
from chessshootout.domain.premoves import Premove, speculative_board
from chessshootout.backend.pieces import PieceType, PieceColor, Piece, opponent_of
from chessshootout.frontend.visual.fonts import get_font


_OVERLAY_CACHE = new_size_cache()
_PROMO_OPTION_CACHE = new_size_cache()
_PROMO_PLATE_CACHE = new_size_cache()
_MARKER_CACHE = new_size_cache()
_PIECE_IMAGE_CACHE = new_cache()
_SCALED_PIECE_CACHE = new_size_cache()

CAPTURE_ICON_FRACTION = 0.42

PIECE_SCALE = 0.9
RIM_ALPHA = 54
RIM_BLUR_PASSES = 2


def _rim_glow(canvas: pg.Surface) -> pg.Surface:
    """
    Build the pale halo that keeps a dark piece readable on a dark square. The
    sprite's own silhouette is blurred and tinted, so the outline follows the
    artwork exactly without the artwork itself being touched

    :param canvas: cell-sized piece sprite the silhouette is taken from
    :returns: a cell-sized surface holding only the halo
    """
    rim_rgb = pg.Color(Colors.rim_light)[:3]
    sil = canvas.copy()
    sil.fill((0, 0, 0, 255), special_flags=pg.BLEND_RGBA_MULT)
    sil.fill((*rim_rgb, 0), special_flags=pg.BLEND_RGBA_ADD)
    sil = soft_blur(sil, RIM_BLUR_PASSES)
    sil.fill((255, 255, 255, RIM_ALPHA), special_flags=pg.BLEND_RGBA_MULT)
    return sil


def _build_scaled_sprite(original: pg.Surface, cell: int,
                         color: PieceColor) -> tuple[pg.Surface, dict[str, Any]]:
    """
    Fit one piece image to the current square size and measure it, producing
    the sprite every piece on the board is drawn from. Black pieces get their
    rim halo baked in here, and the measurements travel with the sprite because
    the drag physics grabs and swings the piece around them

    :param original: full-size piece image as it was loaded from disk
    :param cell: square size in pixels the sprite is fitted into
    :param color: side the piece belongs to; only black gets the halo
    :returns: the sprite and its geometry -- ink bounding box, centre and top
        centre, all in sprite-local pixels
    """
    art_size = max(int(cell * PIECE_SCALE), 1)
    art = pg.transform.smoothscale(original, (art_size, art_size))
    off = ((cell - art_size) // 2, (cell - art_size) // 2)
    canvas = pg.Surface((cell, cell), pg.SRCALPHA)
    canvas.blit(art, off)
    art_bbox = art.get_bounding_rect().move(off)
    geom = {
        "bbox": art_bbox,
        "center": art_bbox.center,
        "top_center": (art_bbox.centerx, art_bbox.top),
    }
    if color == PieceColor.WHITE:
        return canvas, geom
    sprite = pg.Surface((cell, cell), pg.SRCALPHA)
    sprite.blit(_rim_glow(canvas), (0, 0))
    sprite.blit(canvas, (0, 0))
    return sprite, geom


RESTORE_MS = 480
RESTORE_DROP_FRAC = 0.8
RESTORE_FALL_PORTION = 0.46
RESTORE_FADE_PORTION = 0.36
RESTORE_REBOUND_FRAC = 0.13
RESTORE_SETTLE_DECAY = 4.0
RESTORE_SETTLE_WAVES = 1.25
RESTORE_ROCK_DEG = 7.5
RESTORE_ROCK_WAVES = 1.15


def _draw_capsule(surf: pg.Surface, p1: tuple[float, float], p2: tuple[float, float],
                  width: int, color: str) -> None:
    """
    Draw one rounded bar between two points, the stroke the crosshair marks are
    built out of

    :param surf: surface to draw on
    :param p1: one end of the bar in surface pixels
    :param p2: the other end in surface pixels
    :param width: bar thickness in pixels, which is also its cap diameter
    :param color: bar colour as a hex string
    """
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    bar = pg.Surface((int(length) + width, width), pg.SRCALPHA)
    pg.draw.rect(bar, color, bar.get_rect(), border_radius=width // 2)
    rotated = pg.transform.rotate(bar, -math.degrees(math.atan2(dy, dx)))
    surf.blit(rotated, rotated.get_rect(center=((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)))


class Board:
    """
    The chessboard on screen: where the squares are, how the position is drawn
    and what every click, drag and right-drag on it means. It reads the game
    through its match and owns the premove queue, the drag physics, the drawn
    marks, the shot effects and the browse position, and both the game screen
    and the read-only review screen build one
    """

    PLATE_MARGIN = 26
    PLATE_MARGIN_FLOOR = 18
    PLATE_CUT = 18
    COORD_PAD_FRACTION = 0.6

    PROMOTION_OPTION_SIZE_MIN = 48
    PROMOTION_OPTION_SIZE_MAX = 72
    PROMOTION_PLATE_PAD = 10
    PROMOTION_OPTION_GAP = 8
    PROMOTION_PLATE_CUT = 10
    PROMOTION_CELL_CUT = 6
    PROMOTION_SQUARE_GAP = 6
    PROMO_PLATE_TEXT_PAD = (3, 2)
    PROMO_PLATE_SCRIM_ALPHA = 200
    PROMOTION_SCREEN_MARGIN = 8

    HITMARKER_SIZE_MIN = 8
    KING_HITMARKER_SIZE_FACTOR = 1.0
    KING_HITMARKER_THICKNESS = 3.4
    CAPTURE_HITMARKER_SIZE_FACTOR = 0.55
    CAPTURE_HITMARKER_THICKNESS = 4.2

    def __init__(self, window: pg.Surface, match: Match | Backend,
                 move_landed_callback: Callable[[HistoryEntry], None] | None = None,
                 on_premove_queued: Callable[[PieceType], None] | None = None,
                 shot_callback: Callable[[HistoryEntry], None] | None = None,
                 announce_callback: Callable[[str, Piece | None], None] | None = None) -> None:
        """
        Build a board for one screen. It starts with no geometry and no art --
        set_rect gives it a place on screen and load_assets gives it the piece
        images -- and every callback is optional, which is how the review
        screen builds a board that only ever draws

        :param window: display surface the board paints into
        :param match: game to read the position from, the Match the screens
            hold or a bare engine in tests
        :param move_landed_callback: called with the history entry once a ply
            has finished landing, where the move sounds and the per-ply
            bookkeeping hang
        :param on_premove_queued: called with the piece type each time a
            premove is queued, for the queue sound
        :param shot_callback: called with the history entry at the frame the
            capture choreography pulls the trigger, so the bang lands with the
            muzzle flash rather than with the move
        :param announce_callback: called with a kill key and the piece that was
            taken, for the hit sound and the announcer
        """
        self.window = window
        self.match = match
        self.move_landed_callback = move_landed_callback
        self.shot_callback = shot_callback
        self.announce_callback = announce_callback
        self.on_premove_queued = on_premove_queued
        self.skillcheck_gate: Callable[..., bool] | None = None
        self.skillcheck_armed: Callable[[], bool] | None = None
        self.locked_targets: Callable[[Square, Square], bool] | None = None
        self.auto_queen_provider: Callable[[], bool] = lambda: False

        self.rect = pg.Rect(0, 0, 0, 0)
        self.scale = 1.0
        self.needs_present = False
        self.frame_pad = 0
        self.cell_size = 0
        self.board_offset_x = 0
        self.board_offset_y = 0
        self._promotion_rects: dict[PieceType, pg.Rect] = {}
        self._frame_surf: pg.Surface | None = None
        self._checkerboard_surf: pg.Surface | None = None
        self._check_squares_key: tuple[int, Move | None] | None = None
        self._check_squares: list[Square] = []
        self._review_grid_memo: tuple[
            tuple[int, int], list[list[Piece | None]]] | None = None
        self._shake_dx = 0
        self._shake_dy = 0

        self.file_labels = "abcdefgh"
        self.file_labels_rendered: list[pg.Surface] = []
        self.rank_labels_rendered: list[pg.Surface] = []

        self.piece_images_original: dict[tuple[PieceType, PieceColor], pg.Surface] = {}
        self.piece_images_scaled: dict[tuple[PieceType, PieceColor], pg.Surface] = {}
        self._sprite_geom: dict[tuple[PieceType, PieceColor], dict[str, Any]] = {}
        self.selected_square: Square | None = None
        self.pending_promotion_square: Square | None = None
        self._promotion_from: Square | None = None
        self.aim_suppressed_square: Square | None = None
        self.attacker_suppressed_square: Square | None = None
        self.flipped = False
        self.animations: list[PieceAnimation] = []
        self._restore_anims: list[dict[str, Any]] = []
        self.effects = EffectManager()
        self.effects.geom = (
            lambda sq: self._cell_rect(cast(Square, sq).row, cast(Square, sq).col).center)
        self.animation_duration_ms = 180
        self.last_animation_completed_at_ms = 0
        self.premoves: list[Premove] = []
        self.premove_color: PieceColor | None = None
        self.annotations = Annotations(self)
        self.dragging_from: Square | None = None
        self.drag = DragPhysics(self)
        self.review_ply: int | None = None
        self._target_ply: int | None = None
        self.read_only = False
        self._promo_hotkey_font = get_font(9, bold=True, mono=True)
        self._promo_tag_font = get_font(8, bold=True, mono=True)

    @property
    def backend(self) -> Backend:
        """
        The chess engine underneath, however this board was handed its game --
        through the Match wrapper the screens hold, or as a bare engine in
        tests

        :returns: the engine that owns the live position
        """
        inner = getattr(self.match, "backend", None)
        return cast(Backend, inner if inner is not None else self.match)

    @property
    def _local_color(self) -> PieceColor | None:
        """
        The colour this client is allowed to move online, read off the match
        every time so a board handed a bare engine in tests simply has none.
        Every click policy that has to tell your own pieces from the
        opponent's asks here

        :returns: the local player's colour, None when both sides are played
            on this machine
        """
        return cast("PieceColor | None", getattr(self.match, "local_color", None))

    @property
    def highlighted_squares(self) -> set[Square]:
        """
        The squares this player has coloured in by right-clicking. The
        annotations helper keeps them; the board exposes them because the
        screens and the panels talk to the board

        :returns: the marked squares, the helper's own live set
        """
        return self.annotations.highlighted_squares

    @highlighted_squares.setter
    def highlighted_squares(self, value: set[Square]) -> None:
        """
        Replace this player's coloured squares outright, which is how a resume
        puts their marks back after a reconnect

        :param value: the squares that should now be marked
        """
        self.annotations.highlighted_squares = value

    @property
    def arrows(self) -> list[tuple[Square, Square]]:
        """
        The arrows this player has drawn by right-dragging, kept in the order
        they were made because that is the order they are drawn in

        :returns: from and to square pairs, the helper's own live list
        """
        return self.annotations.arrows

    @arrows.setter
    def arrows(self, value: list[tuple[Square, Square]]) -> None:
        """
        Replace this player's arrows outright, which is how a resume puts their
        marks back after a reconnect

        :param value: the arrows that should now be drawn, in draw order
        """
        self.annotations.arrows = value

    def reset_for_new_game(self) -> None:
        """
        Wipe the board back to a fresh game: orientation, selection, a pending
        promotion, animations, effects, premoves, the squares a skill check was
        hiding, every mark, the memoised positions and the browse position.
        Screens call this between games, so nothing from the last one can
        survive into the next
        """
        self.flipped = False
        self.selected_square = None
        self.pending_promotion_square = None
        self._promotion_from = None
        self.cancel_animations()
        self.effects.clear()
        self.clear_premoves()
        self.aim_suppressed_square = None
        self.attacker_suppressed_square = None
        self.clear_all_annotations()
        self.end_press()
        self.review_ply = None
        self.forget_position_memos()

    def forget_position_memos(self) -> None:
        """
        Throw away everything remembered about the position itself -- which
        kings are in check and the browsed grid. Both are keyed on the ply
        count, which a position adopted from a FEN can repeat while standing
        for something completely different, so anything that rewrites the
        board underneath them has to say so here
        """
        self._check_squares_key = None
        self._check_squares = []
        self._review_grid_memo = None

    def _render_text(self) -> None:
        """
        Pre-render the file letters and rank numbers at a size that suits the
        current squares, so the coordinates around the board cost nothing per
        frame. It runs again every time the board is resized
        """
        size = max(int(self.cell_size * 0.30), 11) if self.cell_size else 13
        if self.frame_pad:
            size = min(size, max(int(self.frame_pad * self.COORD_PAD_FRACTION), 8))
        coord_font = get_font(size, bold=True, mono=True)
        self.file_labels_rendered = [
            coord_font.render(self.file_labels[i], True, Colors.text_muted)
            for i in range(BOARD_SIZE)
        ]
        self.rank_labels_rendered = [
            coord_font.render(str(BOARD_SIZE - r), True, Colors.text_muted)
            for r in range(BOARD_SIZE)
        ]

    def _load_piece_images(self) -> None:
        """
        Load the twelve piece images once. They come out of a module-level
        cache shared by every board in the app, so the game screen and the
        review screen never decode the same file twice
        """
        for piece_color in PieceColor:
            for piece_type in PieceType:
                piece = Piece(piece_type, piece_color)
                key = (piece_type, piece_color)
                self.piece_images_original[key] = memoized_surface(
                    _PIECE_IMAGE_CACHE, key,
                    cast(Callable[[], pg.Surface],
                         lambda p=piece: pg.image.load(piece_png_path(p)).convert_alpha()))

    def _cell_rect_base(self, row: int, col: int) -> pg.Rect:
        """
        Where a square sits on screen before any screen shake, with the board's
        orientation already applied. Anything that has to stay put while the
        board is being shaken -- the promotion picker, the drawn arrows --
        measures from here

        :param row: board row, 0 being Black's back rank
        :param col: board column, 0 being the a-file
        :returns: the square's rect in window pixels
        """
        if self.flipped:
            row = BOARD_SIZE - 1 - row
            col = BOARD_SIZE - 1 - col
        return pg.Rect(
            col * self.cell_size + self.board_offset_x,
            row * self.cell_size + self.board_offset_y,
            self.cell_size,
            self.cell_size
        )

    def _cell_rect(self, row: int, col: int) -> pg.Rect:
        """
        Where a square sits on screen this frame, screen shake included. Pieces
        and square highlights are placed with this, which is what makes the
        whole board lurch when a shot goes off

        :param row: board row, 0 being Black's back rank
        :param col: board column, 0 being the a-file
        :returns: the square's rect in window pixels for this frame
        """
        return self._cell_rect_base(row, col).move(self._shake_dx, self._shake_dy)

    PROMOTION_OPTIONS = [
        (PieceType.QUEEN, "Q", "BOSS"), (PieceType.ROOK, "R", "TANK"),
        (PieceType.BISHOP, "B", "SNIPER"), (PieceType.KNIGHT, "N", "WILDCARD"),
    ]

    def _promo_option_sprite(self, ptype: PieceType, color: PieceColor,
                             opt: int) -> pg.Surface:
        """
        The piece image on one promotion button, cached per size so reopening
        the picker costs nothing

        :param ptype: piece the button offers
        :param color: side that is promoting
        :param opt: button size in pixels; the sprite is square
        :returns: the scaled piece image
        """
        key = (ptype, color, opt)
        return memoized_surface(
            _PROMO_OPTION_CACHE, key,
            lambda: pg.transform.smoothscale(
                self.piece_images_original[(ptype, color)], (opt, opt)))

    def _draw_promotion_picker(self) -> None:
        """
        Draw the four-piece promotion panel beside the promoting square and
        remember where each option landed, which is what a later click is
        tested against. The panel jumps to the other side of the square, and is
        pushed back inside the window, when there is not enough room
        """
        self._promotion_rects = {}
        if self.pending_promotion_square is None:
            return
        sq = self.pending_promotion_square
        origin = self._promotion_from if self._promotion_from is not None else sq
        pawn = self.match.piece_at(origin)
        if pawn is None:
            return
        color = pawn.color
        opt = max(self.PROMOTION_OPTION_SIZE_MIN,
                  min(int(self.cell_size), self.PROMOTION_OPTION_SIZE_MAX))
        pad, gap = self.PROMOTION_PLATE_PAD, self.PROMOTION_OPTION_GAP
        panel_w = pad * 2 + 4 * opt + 3 * gap
        panel_h = pad * 2 + opt
        sq_rect = self._cell_rect_base(sq.row, sq.col)
        win_w, win_h = self.window.get_size()
        square_gap = scale_floor(self.PROMOTION_SQUARE_GAP, self.scale, 4)
        left_bound = max(self.rect.x, self.PROMOTION_SCREEN_MARGIN)
        right_bound = min(self.rect.right, win_w - self.PROMOTION_SCREEN_MARGIN)
        x = sq_rect.right + square_gap
        if x + panel_w > right_bound:
            x = sq_rect.left - panel_w - square_gap
        x = max(left_bound, min(x, right_bound - panel_w))
        y = max(self.rect.y,
                min(sq_rect.centery - panel_h // 2,
                    win_h - panel_h - self.PROMOTION_SCREEN_MARGIN))
        panel = pg.Rect(x, y, panel_w, panel_h)
        plate = cut_rect_surface(
            panel.size, scale_floor(self.PROMOTION_PLATE_CUT, self.scale, 7),
            Colors.surface, border=Colors.border_strong, border_width=1, corners=("tr",))
        self.window.blit(plate, panel.topleft)
        mouse = pg.mouse.get_pos()
        cell_cut = scale_floor(self.PROMOTION_CELL_CUT, self.scale, 4)
        for i, (ptype, hotkey, tag) in enumerate(self.PROMOTION_OPTIONS):
            cell = pg.Rect(panel.x + pad + i * (opt + gap), panel.y + pad, opt, opt)
            hovered = cell.collidepoint(mouse)
            shell = cut_rect_surface(
                cell.size, cell_cut,
                Colors.surface_hover if hovered else Colors.surface_raised,
                border=Colors.accent if hovered else Colors.border,
                border_width=1, corners=("tr",))
            self.window.blit(shell, cell.topleft)
            img = self._promo_option_sprite(ptype, color, opt)
            self.window.blit(img, cell.topleft)
            hk = self._promo_nameplate(hotkey, self._promo_hotkey_font, Colors.text_dim)
            self.window.blit(hk, (cell.right - hk.get_width() - 3,
                                  cell.bottom - hk.get_height() - 3))
            tag_surf = self._promo_nameplate(
                tag, self._promo_tag_font,
                Colors.amber if hovered else Colors.text_dim)
            tag_inset = max(1, min(3, cell.width - tag_surf.get_width() - 1))
            self.window.blit(tag_surf, (cell.left + tag_inset, cell.top + 3))
            self._promotion_rects[ptype] = cell

    def _promo_nameplate(self, text: str, font: pg.font.Font, color: str) -> pg.Surface:
        """
        The small dark plate carrying a promotion button's hotkey letter or its
        nickname, cached by text, font height and colour so it is built only
        once. The font's height stands in for the font itself in the key, so a
        cached plate never keeps a font replaced by a resize alive

        :param text: label to show, a hotkey letter or a piece nickname
        :param font: font the label is rendered with
        :param color: label colour as a hex string
        :returns: the label on its scrim, ready to blit
        """
        def build() -> pg.Surface:
            """
            Render the label onto a rounded scrim the first time this plate is
            asked for

            :returns: the finished plate surface
            """
            label = font.render(text, True, pg.Color(color))
            pad_x, pad_y = self.PROMO_PLATE_TEXT_PAD
            surf = pg.Surface((label.get_width() + 2 * pad_x,
                               label.get_height() + 2 * pad_y), pg.SRCALPHA)
            scrim = pg.Color(Colors.bg)
            scrim.a = self.PROMO_PLATE_SCRIM_ALPHA
            pg.draw.rect(surf, scrim, surf.get_rect(), border_radius=3)
            surf.blit(label, (pad_x, pad_y))
            return surf
        return memoized_surface(
            _PROMO_PLATE_CACHE, (text, font.get_height(), color), build)

    def pick_promotion(self, ptype: PieceType) -> None:
        """
        Take the player's choice of promotion piece, whether it came from a
        click on the picker or from the Q, R, B and N hotkeys. A promotion
        whose pawn has already arrived is simply completed; one still waiting
        to be played has to clear the skill-check gate first, because
        promotions are checked too

        :param ptype: piece the pawn becomes
        """
        if self.pending_promotion_square is None:
            return
        sq = self.pending_promotion_square
        if self._promotion_from is not None:
            from_sq = self._promotion_from
            self.pending_promotion_square = None
            self._promotion_rects = {}
            self._promotion_from = None
            self._resolve_promotion_pick(from_sq, sq, ptype)
            return
        self._promote_landed(sq, ptype)

    def _promote_landed(self, sq: Square, ptype: PieceType) -> None:
        """
        Finish a promotion whose pawn has already arrived: the engine completes
        the ply and the screen is told the move has landed

        :param sq: square the promoting pawn stands on
        :param ptype: piece the pawn becomes
        """
        self.match.promote(sq, ptype)
        self.pending_promotion_square = None
        self._promotion_rects = {}
        self._fire_move_landed()

    def _resolve_promotion_pick(self, from_sq: Square, to_sq: Square,
                                ptype: PieceType) -> None:
        """
        Play a promotion the player has now chosen a piece for. The skill-check
        gate gets first refusal -- online it sends the move and waits for the
        server -- and only an ungated promotion is applied here and now

        :param from_sq: square the pawn moves from
        :param to_sq: promotion square
        :param ptype: piece the pawn becomes
        """
        if self.skillcheck_gate is not None and self.skillcheck_gate(from_sq, to_sq, ptype):
            return
        self.apply_gated_move(from_sq, to_sq, ptype)

    def cancel_unapplied_promotion(self) -> bool:
        """
        Drop a promotion the player never chose a piece for, used when a game
        ends with the picker still open. Only a promotion whose move has not
        been played yet can be dropped this way -- one already on the board has
        to be completed instead

        :returns: True when there was an unplayed promotion to cancel
        """
        if self._promotion_from is None:
            return False
        self.pending_promotion_square = None
        self._promotion_rects = {}
        self._promotion_from = None
        return True

    def pick_promotion_at(self, pos: tuple[int, int]) -> None:
        """
        Turn a click into a promotion choice by testing it against the buttons
        the picker last drew. A click that misses every button changes nothing,
        so the picker stays open until a piece is actually chosen

        :param pos: click position in window pixels
        """
        if self.pending_promotion_square is None:
            return
        for ptype, cell in self._promotion_rects.items():
            if cell.collidepoint(pos):
                self.pick_promotion(ptype)
                return

    def load_assets(self) -> None:
        """
        Load everything the board draws with -- the coordinate labels and the
        piece images -- which the shell does once at startup, before the first
        frame is painted
        """
        self._render_text()
        self._load_piece_images()

    def rescale_pieces(self) -> None:
        """
        Rebuild the piece sprites for the current square size and remeasure
        them. The scaled sprites sit in a module-level cache keyed by piece and
        size, shared across boards, so resizing back to an earlier size costs
        nothing
        """
        if self.cell_size <= 0:
            return

        cell = int(self.cell_size)
        self.piece_images_scaled = {}
        self._sprite_geom = {}
        for k, original in self.piece_images_original.items():
            ptype, color = k
            sprite, geom = memoized_surface(
                _SCALED_PIECE_CACHE, (ptype, color, cell),
                cast(Callable[[], tuple[pg.Surface, dict[str, Any]]],
                     lambda o=original, c=color: _build_scaled_sprite(o, cell, c)))
            self.piece_images_scaled[k] = sprite
            self._sprite_geom[k] = geom

    def _draw_vertical_guides(self) -> None:
        """
        Draw the rank numbers down the left gutter, following the board's
        orientation so they still read correctly when it is turned round
        """
        gutter_cx = (self.rect.x + self.board_offset_x) // 2
        for visual_row in range(BOARD_SIZE):
            array_row = (BOARD_SIZE - 1 - visual_row) if self.flipped else visual_row
            label = self.rank_labels_rendered[array_row]
            cy = self.board_offset_y + visual_row * self.cell_size + self.cell_size // 2
            self.window.blit(label, (gutter_cx - label.get_width() // 2 + self._shake_dx,
                                     cy - label.get_height() // 2 + self._shake_dy))

    def _draw_horizontal_guides(self) -> None:
        """
        Draw the file letters along the bottom gutter, following the board's
        orientation so they still read correctly when it is turned round
        """
        grid_bottom = self.board_offset_y + self.cell_size * BOARD_SIZE
        gutter_cy = (grid_bottom + self.rect.bottom) // 2
        for visual_col in range(BOARD_SIZE):
            array_col = (BOARD_SIZE - 1 - visual_col) if self.flipped else visual_col
            label = self.file_labels_rendered[array_col]
            cx = self.board_offset_x + visual_col * self.cell_size + self.cell_size // 2
            self.window.blit(label, (cx - label.get_width() // 2 + self._shake_dx,
                                     gutter_cy - label.get_height() // 2 + self._shake_dy))

    def draw_board(self) -> None:
        """
        Paint the board for this frame, back to front: plate, squares,
        highlights, pieces, shot effects, arrows and the promotion picker.
        While the player is browsing an earlier position it paints a stripped
        version instead -- no check or premove hints, no effects and no shake --
        because none of that belongs to the position being looked at
        """
        now = pg.time.get_ticks()
        self.update_drag_physics(now)
        self.effects.update(now)
        if self.review_ply is None:
            self._shake_dx, self._shake_dy = self.effects.shake_offset(now)
        else:
            self._shake_dx = self._shake_dy = 0
        if self._frame_surf is not None:
            self.window.blit(self._frame_surf,
                             (self.rect.x + self._shake_dx, self.rect.y + self._shake_dy))
        if self._checkerboard_surf is not None:
            self.window.blit(self._checkerboard_surf,
                             (self.board_offset_x + self._shake_dx,
                              self.board_offset_y + self._shake_dy))
        if self.review_ply is not None:
            self._draw_last_move_highlight()
            self._draw_annotation_highlights()
            self._draw_vertical_guides()
            self._draw_horizontal_guides()
            self.draw_pieces()
            self._draw_animations()
            self._draw_arrows()
            self._draw_review_cue()
            return
        self._draw_check_highlight()
        self._draw_premove_highlights()
        self._draw_last_move_highlight()
        self._draw_annotation_highlights()
        self._draw_vertical_guides()
        self._draw_horizontal_guides()
        self._draw_selection_highlight()
        self._draw_move_indicators()
        self.effects.draw_holes(self.window, now)
        self.draw_pieces()
        self._draw_front_markers()
        self._draw_animations()
        self._draw_restores(now)
        self.effects.draw_over(self.window, now)
        self._draw_arrows()
        self._draw_promotion_picker()

    def draw_drag_overlay(self) -> None:
        """
        Draw the piece the player is holding, on top of everything else the
        screen has painted. It is kept apart from draw_board so a held piece is
        never hidden behind the panels drawn after the board
        """
        self.drag.draw_drag_overlay()

    def _cell_overlay(self, color: str) -> pg.Surface:
        """
        A square-sized wash of one colour, the tint every square highlight is
        drawn with. They are cached per size and colour, since a single frame
        can ask for the same wash a dozen times

        :param color: wash colour as a hex string, its alpha included
        :returns: the tinted square-sized surface
        """
        cs = int(self.cell_size)

        def build() -> pg.Surface:
            """
            Fill a fresh square-sized surface the first time this wash is asked
            for

            :returns: the tinted square-sized surface
            """
            surf = pg.Surface((cs, cs), pg.SRCALPHA)
            surf.fill(color)
            return surf
        return memoized_surface(_OVERLAY_CACHE, (cs, color), build)

    def _in_check_king_squares(self) -> list[Square]:
        """
        Which kings are in check right now, for the red square and the
        crosshair over them. The answer is memoised against the ply, since
        working it out means asking the engine about every king on the board

        :returns: the squares of the kings currently in check
        """
        history = self.match.move_history
        last_move = history[-1].move if history else None
        key = (len(history), last_move)
        if key != self._check_squares_key:
            self._check_squares_key = key
            result = []
            for row, col in product(range(BOARD_SIZE), repeat=2):
                piece = self.match.piece_at(Square(row, col))
                if (piece is not None and piece.type == PieceType.KING
                        and self.match.is_in_check(piece.color)):
                    result.append(Square(row, col))
            self._check_squares = result
        return self._check_squares

    def _reviewed_grid(self, ply: int) -> list[list[Piece | None]]:
        """
        The position as it stood after a ply, memoised because rebuilding it
        means replaying the game into a copy of the engine and the browsed
        board is redrawn every frame. The key carries the ply count as well,
        so a move or a takeback under the browse position drops it

        :param ply: half-move being browsed, 0 being the starting position
        :returns: an 8x8 grid of pieces, None where a square is empty
        """
        key = (ply, len(self.match.move_history))
        cached = self._review_grid_memo
        if cached is None or cached[0] != key:
            cached = (key, self.match.position_at(ply))
            self._review_grid_memo = cached
        return cached[1]

    def _draw_last_move_highlight(self) -> None:
        """
        Tint the two squares of the move just played, or of the move being
        looked at while the player browses back through the game
        """
        history = self.match.move_history
        if not history:
            return
        if self.review_ply is not None:
            if self.review_ply == 0:
                return
            move = history[self.review_ply - 1].move
        else:
            move = history[-1].move
        for sq in (move.from_sq, move.to_sq):
            rect = self._cell_rect(sq.row, sq.col)
            self.window.blit(self._cell_overlay(Colors.last_move), rect.topleft)

    def _draw_premove_highlights(self) -> None:
        """
        Tint the squares of every queued premove, with the end of the chain the
        player is currently holding picked out in its own colour, so a bouncing
        chain can be read at a glance
        """
        if not self.premoves:
            return
        seen = set()
        for pm in self.premoves:
            for sq in (pm.from_sq, pm.to_sq):
                if sq in seen:
                    continue
                seen.add(sq)
                rect = self._cell_rect(sq.row, sq.col)
                self.window.blit(self._cell_overlay(Colors.premove), rect.topleft)
        chain_tip = self._active_chain_tip()
        if chain_tip is not None:
            rect = self._cell_rect(chain_tip.row, chain_tip.col)
            self.window.blit(self._cell_overlay(Colors.premove_chain_tip), rect.topleft)

    def _active_chain_tip(self) -> Square | None:
        """
        Where the piece the player is holding will actually be standing once
        the queued premoves have run, so the highlight follows the piece rather
        than sitting on the square it started from

        :returns: the end of the chain, or None when the held piece has nothing
            to do with the premove queue
        """
        active_sq = self.dragging_from or self.selected_square
        if active_sq is None or not self.premoves:
            return None
        tip = self._resolve_chain_tip(active_sq)
        if tip != active_sq:
            return tip
        for pm in self.premoves:
            if pm.to_sq == active_sq:
                return active_sq
        return None

    def toggle_highlight(self, sq: Square) -> bool:
        """
        Colour a square in or clear it again, the mark a plain right-click
        makes

        :param sq: square that was right-clicked
        :returns: True when the square is now marked, False when it was cleared
        """
        return self.annotations.toggle_highlight(sq)

    def toggle_arrow(self, from_sq: Square, to_sq: Square) -> bool | None:
        """
        Draw an arrow between two squares or remove the one already there, the
        mark a right-drag makes. There is a cap on how many arrows may exist at
        once, because online they are shared with the opponent

        :param from_sq: square the drag started on
        :param to_sq: square it ended on
        :returns: True when the arrow was added, False when it was removed, and
            None when the cap refused it
        """
        return self.annotations.toggle_arrow(from_sq, to_sq)

    def is_square_annotated(self, sq: Square) -> bool:
        """
        Whether this player has drawn anything on a square, which is what
        decides if a left click there clears the marks or leaves them alone

        :param sq: square being clicked
        :returns: True when a mark of this player's touches it
        """
        return self.annotations.is_square_annotated(sq)

    def clear_annotations(self) -> None:
        """
        Wipe this player's own marks off the board, leaving anything the
        opponent is sharing exactly where it is
        """
        self.annotations.clear()

    def clear_all_annotations(self) -> None:
        """
        Wipe every mark off the board, this player's and the opponent's alike,
        which is what a landing move and a new game both do
        """
        self.annotations.clear_all()

    def begin_right_press(self, pos: tuple[int, int]) -> Square | None:
        """
        Start a right-button gesture, remembering the square it began on so a
        drag can be told from a click when the button comes back up

        :param pos: press position in window pixels
        :returns: the square pressed, or None when the press missed the board
        """
        return self.annotations.begin_right_press(pos)

    def end_right_press(self, pos: tuple[int, int]) -> tuple[Any, ...] | None:
        """
        Finish a right-button gesture and commit the mark it drew: pressing and
        releasing on one square colours it in, dragging between two draws an
        arrow. Online the screen forwards whatever comes back to the opponent
        while mark sharing is on

        :param pos: release position in window pixels
        :returns: ("highlight", square, added) or ("arrow", from, to, added),
            or None when the gesture did not land on the board
        """
        return self.annotations.end_right_press(pos)

    def _draw_annotation_highlights(self) -> None:
        """
        Draw the coloured squares, this player's and the opponent's shared
        ones, each side in its own colour
        """
        self.annotations.draw_highlights()

    def _draw_review_cue(self) -> None:
        """
        Outline the board in the accent colour while the player is browsing an
        earlier position on a live game's board. It is the one cue that what is
        on screen is not the current position, so the review screen -- where
        browsing is the whole point -- never draws it
        """
        if self.read_only or self._frame_surf is None:
            return
        cue = cut_rect_surface(
            self.rect.size, scale_floor(self.PLATE_CUT, self.scale, 12),
            "#00000000", border=Colors.accent, border_width=2, corners=("tr",))
        self.window.blit(cue, self.rect.topleft)

    def _draw_arrows(self) -> None:
        """
        Draw the arrows over the board, including the one currently being
        dragged out
        """
        self.annotations.draw_arrows()

    def _draw_check_highlight(self) -> None:
        """
        Mark every king that is in check with a red wash and a red border, the
        board's loudest warning
        """
        for sq in self._in_check_king_squares():
            rect = self._cell_rect(sq.row, sq.col)
            self.window.blit(self._cell_overlay(Colors.check_fill), rect.topleft)
            pg.draw.rect(self.window, Colors.check, rect, 3)

    def _draw_hitmarker(self, rect: pg.Rect, size: int, color: str, thick: float) -> None:
        """
        Stamp the four-stroke crosshair over a square, this game's mark for a
        piece that can be shot and for a king already under the gun. The sprite
        is supersampled and cached, so the strokes stay clean at any board size

        :param rect: square to centre the mark on, in window pixels
        :param size: mark size in pixels
        :param color: mark colour as a hex string
        :param thick: stroke thickness relative to the mark's own grid
        """
        def build() -> pg.Surface:
            """
            Draw the four strokes once for this size, colour and thickness

            :returns: the finished crosshair sprite
            """
            def render(surf: pg.Surface, k: int) -> None:
                """
                Lay the four strokes out on the oversized surface the
                supersampler hands in

                :param surf: oversized surface to draw on
                :param k: supersampling factor the coordinates are scaled by
                """
                u = size * k / 40.0
                tw = max(int(thick * u), 2)
                for (x1, y1), (x2, y2) in (((7, 7), (14.5, 14.5)), ((33, 7), (25.5, 14.5)),
                                           ((7, 33), (14.5, 25.5)), ((33, 33), (25.5, 25.5))):
                    _draw_capsule(surf, (x1 * u, y1 * u), (x2 * u, y2 * u), tw, color)
            return supersample(size, render)
        surf = memoized_surface(_MARKER_CACHE, (size, color, thick, "hit"), build)
        self.window.blit(surf, (rect.centerx - size // 2, rect.centery - size // 2))

    def draw_pieces(self) -> None:
        """
        Draw every piece standing on the board, skipping the ones something
        else is drawing this frame: a piece in mid-animation, one a shot effect
        is holding, one being dragged or settling, and the squares a live skill
        check has taken over. Those suppressed squares belong to the check --
        the skill-check session sets them when it arms and clears them when it
        releases -- and the board only reads them. While the player is browsing,
        the reviewed position is drawn from the memoised history instead
        """
        if self.review_ply is not None:
            grid = self._reviewed_grid(self.review_ply)
            hidden = {a.from_sq for a in self.animations}
            for row, col in product(range(BOARD_SIZE), repeat=2):
                sq = Square(row, col)
                if sq in hidden:
                    continue
                piece = grid[row][col]
                if piece is None:
                    continue
                rect = self._cell_rect(row, col)
                surface = self.piece_images_scaled[(piece.type, piece.color)]
                self.window.blit(surface, rect.topleft)
            return

        now = pg.time.get_ticks()
        hidden = {(a.from_sq if a.bump else a.to_sq) for a in self.animations}
        hidden |= self.effects.held_squares()
        hidden |= {a["sq"] for a in self._restore_anims}
        if self.aim_suppressed_square is not None:
            hidden.add(self.aim_suppressed_square)
        if self.attacker_suppressed_square is not None:
            hidden.add(self.attacker_suppressed_square)
        if self.dragging_from is not None:
            hidden.add(self.dragging_from)
        settle_sq = self.drag.settle_target()
        if settle_sq is not None:
            hidden.add(settle_sq)
        for row, col in product(range(BOARD_SIZE), repeat=2):
            sq = Square(row, col)
            if sq in hidden:
                continue
            piece = self.match.piece_at(sq)
            if piece is None:
                continue

            rect = self._cell_rect(row, col)
            surface = self.piece_images_scaled[(piece.type, piece.color)]
            dx, dy = self.effects.piece_offset(sq, now)
            self.window.blit(surface, (rect.x + dx, rect.y + dy))

    def _draw_animations(self) -> None:
        """
        Draw and advance the pieces sliding between squares, dropping each one
        as it arrives and running whatever was hung on it landing. The moment
        the last animation finishes is stamped, because the screen waits on
        that before flipping the board or firing the next premove
        """
        if not self.animations:
            return
        now = pg.time.get_ticks()
        completed = []
        for a in self.animations:
            progress = a.progress(now)
            eased = math.sin(progress * math.pi) if a.bump else 1 - (1 - progress) ** 3
            fr = self._cell_rect(a.from_sq.row, a.from_sq.col)
            to = self._cell_rect(a.to_sq.row, a.to_sq.col)
            x = fr.x + (to.x - fr.x) * eased
            y = fr.y + (to.y - fr.y) * eased
            surface = self.piece_images_scaled[(a.piece.type, a.piece.color)]
            self.window.blit(surface, (x, y))
            if a.is_done(now):
                completed.append(a)
        for a in completed:
            self.animations.remove(a)
        if completed and not self.animations:
            self.last_animation_completed_at_ms = now
        for a in completed:
            if a.on_complete is not None:
                a.on_complete()

    def is_animating(self) -> bool:
        """
        Whether a piece is still moving, either sliding between squares or
        settling out of a drag. Clicks are refused and premoves held back while
        this is true, so a move can never land on top of another

        :returns: True while something is still in motion
        """
        if self.drag.is_settling():
            return True
        return bool(self.animations)

    def is_dragging(self) -> bool:
        """
        Whether the player has a piece in hand right now

        :returns: True while a drag is in progress
        """
        return self.drag.is_dragging()

    def is_restoring(self) -> bool:
        """
        Whether a piece is dropping back onto its square after surviving a
        missed shot

        :returns: True while a restore animation is playing
        """
        return bool(self._restore_anims)

    def mark_needs_present(self) -> None:
        """
        Flag that the board has changed in a way the screen cannot work out for
        itself -- a mark drawn or cleared -- so the next frame presents the
        board even though no piece has moved
        """
        self.needs_present = True

    def consume_needs_present(self) -> bool:
        """
        Read the needs-present flag and clear it, so one change asks for
        exactly one present

        :returns: True when the board changed since this was last asked
        """
        was = self.needs_present
        self.needs_present = False
        return was

    def animation_dirty_rect(self) -> pg.Rect:
        """
        The region a move animation is touching, so the screen can present just
        that instead of the whole window. With nothing animating, or a region
        that cannot be worked out, it falls back to the whole board

        :returns: the region to present, clipped to the board
        """
        if not self.animations:
            return pg.Rect(self.rect)
        pad = int(self.cell_size)
        region = None
        for a in self.animations:
            span = self._cell_rect(a.from_sq.row, a.from_sq.col).union(
                self._cell_rect(a.to_sq.row, a.to_sq.col)).inflate(pad, pad)
            region = span if region is None else region.union(span)
        return region.clip(self.rect) if region is not None else pg.Rect(self.rect)

    def start_animation(self, from_sq: Square, to_sq: Square, piece: Piece,
                        on_complete: Callable[[], None] | None = None,
                        bump: bool = False) -> None:
        """
        Slide a piece from one square to another. How long it takes is the
        board's animation duration, which the game screen works out from the
        time control and clamps to between 140 and 280 ms, so bullet games stay
        snappy and long games stay readable

        :param from_sq: square the piece starts on
        :param to_sq: square it slides to
        :param piece: piece to draw in flight
        :param on_complete: called once it arrives, which is where a move's
            consequences are hung
        :param bump: play it as a nudge towards the target and back instead,
            used when a move was refused rather than played
        """
        self.animations.append(PieceAnimation(
            from_sq=from_sq,
            to_sq=to_sq,
            piece=piece,
            start_ms=pg.time.get_ticks(),
            duration_ms=self.animation_duration_ms,
            on_complete=on_complete,
            bump=bump,
        ))

    def cancel_animations(self) -> None:
        """
        Drop every piece and restore animation on the spot. Anything hung on an
        animation finishing goes with it, so a caller that needs the
        consequence has to apply it itself
        """
        self.animations = []
        self._restore_anims = []

    def cancel_drag_physics(self) -> None:
        """
        Abandon a drag in flight, done when the board is resized, flipped or
        left behind. A piece that had already begun settling still lands, so a
        move in progress is not lost
        """
        self.drag.cancel_drag_physics()

    def jump_to_review_ply(self, ply: int | None) -> None:
        """
        Show the position as it stood after a given ply, or go back to the live
        one. This and animate_review_ply are the only ways the browse position
        may be moved: review_ply and _target_ply together are the single index
        the board browses by, and assigning review_ply directly is yanked back
        by any animation still in flight

        :param ply: half-move to show, 0 being the starting position; None, or
            a ply at or past the end of the history, means the live position
        """
        self.cancel_animations()
        self.effects.clear_transients()
        self._target_ply = None
        history_len = len(self.match.move_history)
        if ply is None or ply >= history_len:
            self.review_ply = None
        else:
            self.review_ply = max(0, ply)

    def review_anchor(self, history_len: int) -> int:
        """
        Where the player is currently looking, counting a step that is still
        animating as though it had already arrived. That is what lets a held
        arrow key walk the game ply by ply instead of stalling on the animation

        :param history_len: number of plies played, used when the board is live
        :returns: the ply currently being browsed
        """
        if self._target_ply is not None:
            return self._target_ply
        if self.review_ply is not None:
            return self.review_ply
        return history_len

    def step_review(self, delta: int) -> None:
        """
        Walk the browse position forwards or backwards, which is what the arrow
        keys do on both the game and the review screen. Stepping forwards
        animates the move so it can be watched; stepping back jumps, because a
        move played in reverse reads as a mistake

        :param delta: how many plies to move, negative to go back
        """
        history_len = len(self.match.move_history)
        if history_len == 0:
            return
        current = self.review_anchor(history_len)
        new_ply = max(0, min(history_len, current + delta))
        if new_ply == current:
            return
        if delta > 0:
            self.animate_review_ply(new_ply)
        else:
            self.jump_to_review_ply(new_ply)

    def reviewed_history(self) -> list[HistoryEntry]:
        """
        The game as far as the player is currently looking, which the move
        list, the captured-piece rows and the opening name are all read from

        :returns: history entries up to the browsed ply, or the whole game when
            the board is live
        """
        history = self.match.move_history
        if self.review_ply is None:
            return history
        return history[:self.review_ply]

    def scaled_capture_icons(self, strip_height: float) -> dict[
            tuple[PieceType, PieceColor], pg.Surface] | None:
        """
        Small piece icons sized for the player strips, so the captured pieces
        beside a name are drawn from the same art as the board itself

        :param strip_height: strip height in pixels, which sets the icon size
        :returns: one icon per piece type and colour, or None before the piece
            art has been loaded
        """
        if not self.piece_images_original:
            return None
        size = max(int(strip_height * CAPTURE_ICON_FRACTION), 1)
        return {
            key: pg.transform.smoothscale(surface, (size, size))
            for key, surface in self.piece_images_original.items()
        }

    def _snap_in_flight_review_animation(self) -> None:
        """
        Land an animated review step at once, adopting the ply it was heading
        for. Every new step starts here, so a player holding an arrow key ends
        up exactly where the steps say rather than wherever a half-played
        animation left them
        """
        if self._target_ply is None:
            self.cancel_animations()
            return
        history_len = len(self.match.move_history)
        if self._target_ply >= history_len:
            self.review_ply = None
        else:
            self.review_ply = self._target_ply
        self._target_ply = None
        self.cancel_animations()

    def animate_review_ply(self, ply: int | None) -> None:
        """
        Step forward to a ply and play the move that got there, castling rook
        included. It works the same single browse index jump_to_review_ply
        does: the board shows the previous ply while the piece is in flight and
        only adopts the new one once the animation lands

        :param ply: half-move to step to; None, or a ply past the end of the
            history, returns to the live position
        """
        self._snap_in_flight_review_animation()
        history_len = len(self.match.move_history)
        if ply is None or ply > history_len:
            self.review_ply = None
            self._target_ply = None
            return
        if ply <= 0:
            self.review_ply = 0
            self._target_ply = None
            return
        entry = self.match.move_history[ply - 1]
        move = entry.move
        self.review_ply = ply - 1
        self._target_ply = ply
        target_ply = ply
        end_ply = None if ply == history_len else ply

        def finish() -> None:
            """
            Adopt the ply this animation was heading for, unless another step
            has been started meanwhile and now owns the target
            """
            self.review_ply = end_ply
            if self._target_ply == target_ply:
                self._target_ply = None

        self.start_animation(move.from_sq, move.to_sq, move.piece,
                             on_complete=finish)
        if move.is_castle:
            rook_from, rook_to = self._castle_rook_squares(
                move.from_sq.row, move.to_sq.col)
            rook_piece = Piece(PieceType.ROOK, move.piece.color)
            self.start_animation(rook_from, rook_to, rook_piece)

    def _selected_legal_targets(self) -> list[Square]:
        """
        Where the selected piece may legally go, the set the move dots and the
        capture crosshairs are drawn from. A piece that does not belong to the
        side to move shows nothing

        :returns: legal destination squares, empty when nothing is selected
        """
        if self.selected_square is None:
            return []
        piece = self.match.piece_at(self.selected_square)
        if piece is None or piece.color != self.match.current_turn():
            return []
        return self.match.legal_moves_from(self.selected_square)

    def _is_target_locked(self, target: Square) -> bool:
        """
        Whether the selected piece's move to a square has been locked out by a
        missed skill check, in which case it is drawn as a dead grey marker
        rather than a live move dot

        :param target: destination being considered
        :returns: True when that exact move is barred for the rest of the turn
        """
        return (self.locked_targets is not None
                and self.selected_square is not None
                and self.locked_targets(self.selected_square, target))

    def _draw_move_indicators(self) -> None:
        """
        Dot every empty square the selected piece may move to, greying out the
        ones a missed skill check has locked. Captures are marked separately,
        on top of the pieces rather than under them
        """
        for target in self._selected_legal_targets():
            if self.match.piece_at(target) is not None:
                continue
            if self._is_target_locked(target):
                self._draw_locked_marker(self._cell_rect(target.row, target.col))
            else:
                self._draw_dot(self._cell_rect(target.row, target.col))

    def _draw_front_markers(self) -> None:
        """
        Draw the marks that belong over the pieces rather than under them:
        crosshairs on everything the selected piece could shoot, the en passant
        victim included, and one over every king already in check
        """
        ep = self.match.en_passant_target
        sel = self.selected_square
        for target in self._selected_legal_targets():
            if self.match.piece_at(target) is not None:
                if self._is_target_locked(target):
                    self._draw_locked_marker(self._cell_rect(target.row, target.col))
                else:
                    self._draw_capture_hitmarker(self._cell_rect(target.row, target.col))
            elif ep is not None and target == ep and sel is not None:
                mover = self.match.piece_at(sel)
                if mover is not None and mover.type == PieceType.PAWN and target.col != sel.col:
                    captured = Square(sel.row, target.col)
                    self._draw_capture_hitmarker(self._cell_rect(captured.row, captured.col))
        now = pg.time.get_ticks()
        for sq in self._in_check_king_squares():
            dx, dy = self.effects.piece_offset(sq, now)
            self._draw_hitmarker(
                self._cell_rect(sq.row, sq.col).move(dx, dy),
                max(int(self.cell_size * self.KING_HITMARKER_SIZE_FACTOR),
                    self.HITMARKER_SIZE_MIN),
                Colors.accent, self.KING_HITMARKER_THICKNESS)

    def _marker_dot_surface(self, color: str) -> pg.Surface:
        """
        The hollow ring drawn on a square the selected piece may move to,
        supersampled and cached per square size and colour

        :param color: ring colour as a hex string
        :returns: a square-sized surface with the ring on it
        """
        s = int(self.cell_size)
        radius = max(int(s * 0.16), 4)
        thickness = max(int(s * 0.05), 3)

        def build() -> pg.Surface:
            """
            Draw the ring once for this square size and colour

            :returns: the finished marker surface
            """
            def render(surf: pg.Surface, k: int) -> None:
                """
                Draw the ring on the oversized surface the supersampler hands
                in

                :param surf: oversized surface to draw on
                :param k: supersampling factor the radius is scaled by
                """
                pg.draw.circle(surf, color, (s * k // 2, s * k // 2),
                               radius * k, thickness * k)
            return supersample(s, render)
        return memoized_surface(_MARKER_CACHE, (s, color, "dot"), build)

    def _draw_dot(self, rect: pg.Rect) -> None:
        """
        Mark an empty square the selected piece may move to

        :param rect: the square's rect in window pixels
        """
        self.window.blit(self._marker_dot_surface(Colors.move_indicator), rect.topleft)

    def _draw_locked_marker(self, rect: pg.Rect) -> None:
        """
        Mark a move a missed skill check has locked for this turn, in the muted
        colour that says it cannot be played

        :param rect: the square's rect in window pixels
        """
        self.window.blit(self._marker_dot_surface(Colors.text_muted), rect.topleft)

    def _draw_capture_hitmarker(self, rect: pg.Rect) -> None:
        """
        Put the crosshair on a piece the selected piece could take

        :param rect: the target square's rect in window pixels
        """
        self._draw_hitmarker(
            rect,
            max(int(self.cell_size * self.CAPTURE_HITMARKER_SIZE_FACTOR),
                self.HITMARKER_SIZE_MIN),
            Colors.accent, self.CAPTURE_HITMARKER_THICKNESS)

    def set_rect(self, rect: pg.Rect, scale: float = 1.0) -> None:
        """
        Place and size the board, which the layout pass does at startup, on
        every resize and on every screen switch. Squares, coordinate labels,
        piece sprites and the plate behind them are all rebuilt for the new
        size, and a drag in flight is dropped because its pixels no longer mean
        anything

        :param rect: area the board and its frame occupy, in window pixels
        :param scale: UI scale factor, which sets the frame padding and the
            corner cuts
        """
        self.scale = scale
        self.cancel_drag_physics()
        self.rect = pg.Rect(rect)
        self.effects.board_rect = pg.Rect(rect)
        self.frame_pad = scale_floor(self.PLATE_MARGIN, self.scale, self.PLATE_MARGIN_FLOOR)
        inner = rect.width - 2 * self.frame_pad
        cell_size = max(inner // BOARD_SIZE, 1)
        if cell_size != self.cell_size:
            self.effects.clear_weapon_cache()
            opt = max(self.PROMOTION_OPTION_SIZE_MIN,
                      min(int(cell_size), self.PROMOTION_OPTION_SIZE_MAX))
            self._promo_hotkey_font = get_font(max(int(opt * 0.18), 9), bold=True, mono=True)
            self._promo_tag_font = get_font(max(int(opt * 0.13), 8), bold=True, mono=True)
        self.cell_size = cell_size
        used = self.cell_size * BOARD_SIZE
        free_w = rect.width - 2 * self.frame_pad - used
        free_h = rect.height - 2 * self.frame_pad - used
        self.board_offset_x = rect.x + self.frame_pad + free_w // 2
        self.board_offset_y = rect.y + self.frame_pad + free_h // 2
        self.rescale_pieces()
        self._render_text()
        self._build_frame_surface()
        self._build_checkerboard_surface()

    def _build_checkerboard_surface(self) -> None:
        """
        Pre-render the sixty-four squares onto one surface, so a frame blits the
        whole grid in a single go instead of drawing square after square
        """
        gs = self.cell_size * BOARD_SIZE
        if gs <= 0:
            self._checkerboard_surf = None
            return
        surf = pg.Surface((gs, gs)).convert()
        cs = self.cell_size
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                color = Colors.white_tile if (r + c) % 2 == 0 else Colors.black_tile
                pg.draw.rect(surf, color, pg.Rect(c * cs, r * cs, cs, cs))
        self._checkerboard_surf = surf

    def _build_frame_surface(self) -> None:
        """
        Pre-render the cut-cornered plate the board sits on, together with the
        thin line around the grid. It is rebuilt only when the board is resized
        """
        if self.rect.width <= 0 or self.rect.height <= 0:
            self._frame_surf = None
            return
        plate = cut_rect_surface(
            self.rect.size, scale_floor(self.PLATE_CUT, self.scale, 12),
            Colors.surface, border=Colors.border, border_width=1, corners=("tr",))
        surf = plate.copy()
        gx = self.board_offset_x - self.rect.x
        gy = self.board_offset_y - self.rect.y
        gs = self.cell_size * BOARD_SIZE
        pg.draw.rect(surf, Colors.border, pg.Rect(gx - 1, gy - 1, gs + 2, gs + 2), 1)
        self._frame_surf = surf

    def begin_press(self, pos: tuple[int, int]) -> None:
        """
        Note where the left button went down, the point a drag is later
        measured from once the cursor has moved far enough to count as one

        :param pos: press position in window pixels
        """
        self.drag.begin_press(pos)

    def update_drag_physics(self, now: int) -> None:
        """
        Advance the held piece's swing and settle for this frame, which is what
        gives a dragged piece its weight

        :param now: pygame tick count in milliseconds
        """
        self.drag.update_drag_physics(now)

    def update_drag_motion(self, pos: tuple[int, int]) -> None:
        """
        Follow the cursor with the held piece, and begin the drag the moment
        the cursor has moved far enough from where the button went down

        :param pos: cursor position in window pixels
        """
        self.drag.update_drag_motion(pos)

    def end_press(self) -> bool:
        """
        Let go of the left button: a held piece starts settling onto the square
        under it, and a press that never became a drag is simply forgotten

        :returns: True when a piece really was being dragged
        """
        return self.drag.end_press()

    def queue_premove_from_drag(self, target_sq: Square) -> bool:
        """
        Queue a premove for the piece being dragged, which is how a plan is
        lined up during the opponent's turn without putting the piece down. It
        is only checked loosely -- the piece has to be yours, it has to be the
        opponent's turn and the move has to be shaped like one that piece could
        make -- because the position it will meet is not known yet

        :param target_sq: square the premove aims at
        :returns: True when a premove was queued
        """
        if self.read_only or self.review_ply is not None:
            return False
        if self.dragging_from is None:
            return False
        chain_tip = self._resolve_chain_tip(self.dragging_from)
        if target_sq == chain_tip:
            return False
        if self.pending_promotion_square is not None:
            return False
        grid = self._effective_grid()
        piece = grid[chain_tip.row][chain_tip.col]
        if piece is None:
            return False
        local_color = self._local_color
        if local_color is not None and piece.color != local_color:
            return False
        if piece.color == self.match.current_turn():
            return False
        if not piece_can_pseudo_reach(piece, chain_tip, target_sq):
            return False
        self._queue_premove(chain_tip, target_sq, piece)
        return True

    def cell_at(self, pos: tuple[int, int]) -> Square | None:
        """
        Turn a window position into the square under it, honouring the board's
        orientation. Every click and gesture on the board starts here

        :param pos: position in window pixels
        :returns: the square there, or None when the position is off the board
        """
        x, y = pos
        fcol = (x - self.board_offset_x) / self.cell_size
        frow = (y - self.board_offset_y) / self.cell_size
        if not (0 <= fcol < BOARD_SIZE and 0 <= frow < BOARD_SIZE):
            return None
        col = int(fcol)
        row = int(frow)
        if self.flipped:
            row = BOARD_SIZE - 1 - row
            col = BOARD_SIZE - 1 - col
        return Square(row, col)

    def handle_click(self, square: Square) -> str | None:
        """
        Play a click on a square -- the board's whole click policy in one
        place. On your own turn a click picks a piece up, puts it down, or
        switches to another of your pieces, and a move goes through the
        skill-check gate before it reaches the engine. Off your turn the same
        clicks build the premove queue instead, read against the position with
        the queue already projected onto it, which is what lets a chain bounce
        through squares a piece has yet to leave. A read-only board ignores
        clicks entirely, and while the player is browsing the click first
        clears the drawn marks and only then snaps back to the live position

        :param square: square that was clicked
        :returns: what the click did -- "select", "move", "premove",
            "promotion" or "skillcheck" -- or None when it did nothing
        """
        if self.read_only:
            return None
        if self.review_ply is not None:
            if self.highlighted_squares or self.arrows:
                self.clear_annotations()
            else:
                self.jump_to_review_ply(None)
            return None
        if self.is_animating():
            return None

        if self.pending_promotion_square is not None:
            return None

        grid = self._effective_grid()
        piece_at_clicked = grid[square.row][square.col]
        live_at_clicked = self.match.state[square.row][square.col]
        current_turn = self.match.current_turn()
        local_color = self._local_color

        if self.selected_square is None:
            chain_piece = self._premove_chain_piece(
                piece_at_clicked, live_at_clicked, current_turn, local_color)
            if chain_piece is not None:
                return self._premove_select(square, chain_piece)
            if self._is_real_move_eligible(live_at_clicked, current_turn, local_color):
                return self._select_signal(self._try_select(square))
            if piece_at_clicked is None:
                resolved = self._resolve_chain_tip(square)
                if resolved != square:
                    resolved_piece = grid[resolved.row][resolved.col]
                    if resolved_piece is not None:
                        if resolved_piece.color == current_turn:
                            return self._select_signal(self._try_select(resolved))
                        return self._premove_select(resolved, resolved_piece)
                if self.premoves:
                    self.clear_premoves()
                    return "premove"
                return None
            return self._premove_select(square, piece_at_clicked)

        if square == self.selected_square:
            self.selected_square = None
            return None

        if self._should_switch_focus_to(grid, live_at_clicked, current_turn, local_color):
            self.selected_square = None
            if self._is_real_move_eligible(live_at_clicked, current_turn, local_color):
                return self._select_signal(self._try_select(square))
            return self._premove_select(square, cast(Piece, live_at_clicked))

        from_sq = self.selected_square
        self.selected_square = None
        live_from_piece = self.match.state[from_sq.row][from_sq.col]
        spec_from_piece = grid[from_sq.row][from_sq.col]
        chain_from_piece = self._premove_chain_piece(
            spec_from_piece, live_from_piece, current_turn, local_color)
        if chain_from_piece is not None:
            return "premove" if self._queue_premove(from_sq, square, chain_from_piece) else None
        if self._is_real_move_eligible(live_from_piece, current_turn, local_color):
            if self._skillcheck_armed() and self._is_promotion_move(from_sq, square):
                if self.locked_targets is not None and self.locked_targets(from_sq, square):
                    return None
                if self.auto_queen_provider():
                    self._resolve_promotion_pick(from_sq, square, PieceType.QUEEN)
                else:
                    self._begin_promotion_pick(from_sq, square)
                return "promotion"
            if self.skillcheck_gate is not None and self.skillcheck_gate(from_sq, square):
                return "skillcheck"
            result = self.match.try_move(from_sq, square)
            if not result.legal:
                return None
            self._start_move_animation(from_sq, square, result.promotion_required)
            return "move"

        if spec_from_piece is None:
            return None
        return "premove" if self._queue_premove(from_sq, square, spec_from_piece) else None

    @staticmethod
    def _select_signal(selected: bool) -> str | None:
        """
        Turn a selection attempt into the signal the screen reads, which is
        what decides whether the pickup sound plays

        :param selected: whether a piece was actually picked up
        :returns: "select" when one was, None when nothing happened
        """
        return "select" if selected else None

    def _premove_select(self, square: Square, piece: Piece) -> str | None:
        """
        Pick a piece up to premove with and report it back as premove activity

        :param square: square the piece is on
        :param piece: piece being picked up, read from the projected position
        :returns: "premove" when the piece was picked up, None when it was
            refused
        """
        return "premove" if self._try_select_for_premove(square, piece) else None

    def apply_gated_move(self, from_sq: Square, to_sq: Square,
                         promo_type: PieceType | None = None) -> MoveResult:
        """
        Play a move that has already cleared its skill check -- how a won check
        and a server-confirmed move both land on this board. A promotion piece
        is applied in the same breath, so the ply is never left half finished

        :param from_sq: square the piece leaves
        :param to_sq: square it lands on
        :param promo_type: piece a promoting pawn becomes, None for an ordinary
            move
        :returns: the engine's verdict on the move
        """
        result = self.match.try_move(from_sq, to_sq)
        if not result.legal:
            return result
        if result.promotion_required and promo_type is not None:
            self.match.promote(to_sq, promo_type)
            self._start_move_animation(from_sq, to_sq, promotion_required=False)
        else:
            self._start_move_animation(from_sq, to_sq, result.promotion_required)
        return result

    def _skillcheck_armed(self) -> bool:
        """
        Whether skill checks are switched on for this game, which decides
        whether a promotion piece has to be chosen up front, before the move is
        offered to the gate

        :returns: True when captures and promotions are checked
        """
        return self.skillcheck_armed is not None and self.skillcheck_armed()

    def _is_promotion_move(self, from_sq: Square, to_sq: Square) -> bool:
        """
        Whether a move would promote a pawn, asked before the move is played so
        the piece can be picked while a skill check is still waiting

        :param from_sq: square the pawn stands on
        :param to_sq: square it is aimed at
        :returns: True when this is a legal promotion move
        """
        piece = self.match.piece_at(from_sq)
        if piece is None or piece.type != PieceType.PAWN:
            return False
        if to_sq.row not in (0, BOARD_SIZE - 1):
            return False
        return to_sq in self.match.legal_moves_from(from_sq)

    def _begin_promotion_pick(self, from_sq: Square, to_sq: Square) -> None:
        """
        Open the promotion picker before the move has been played, which is
        what a checked promotion needs -- the piece has to be known before the
        shot is taken. The selection and any drag are dropped so the pawn is
        not left in hand

        :param from_sq: square the pawn moves from
        :param to_sq: promotion square
        """
        self.selected_square = None
        self.drag.clear_drag_state()
        self.pending_promotion_square = to_sq
        self._promotion_from = from_sq

    def cell_rect(self, square: Square) -> pg.Rect:
        """
        Where a square is on screen, the geometry every overlay anchored to the
        board -- a skill-check dial, a speech bubble -- asks for

        :param square: board square to place
        :returns: the square's rect in window pixels
        """
        return self._cell_rect(square.row, square.col)

    @staticmethod
    def _is_real_move_eligible(live_piece: Piece | None, current_turn: PieceColor,
                               local_color: PieceColor | None) -> bool:
        """
        Whether a piece may be moved for real right now: it has to be there, it
        has to belong to the side to move, and online it has to be yours. Every
        other click on a piece is premove territory

        :param live_piece: piece really standing there in the live position
        :param current_turn: side to move
        :param local_color: colour this client plays online, None when both
            sides are played on this machine
        :returns: True when a real move could start from that piece
        """
        if live_piece is None or live_piece.color != current_turn:
            return False
        if local_color is not None and live_piece.color != local_color:
            return False
        return True

    def _should_switch_focus_to(self, grid: list[list[Piece | None]],
                                live_at_clicked: Piece | None, current_turn: PieceColor,
                                local_color: PieceColor | None) -> bool:
        """
        Whether clicking another of your own pieces should pick that one up
        instead of trying to move the selected piece onto it. Both pieces have
        to be yours, which is what keeps a capture from being read as a switch

        :param grid: position clicks are read against, premoves projected on
        :param live_at_clicked: piece really standing there in the live position
        :param current_turn: side to move
        :param local_color: colour this client plays online, None when both
            sides are played on this machine
        :returns: True when the click should move the selection
        """
        if self.selected_square is None:
            return False
        if not self._is_real_move_eligible(live_at_clicked, current_turn, local_color):
            return False
        own_color = local_color if local_color is not None else current_turn
        selected_piece = grid[self.selected_square.row][self.selected_square.col]
        if selected_piece is None or selected_piece.color != own_color:
            return False
        if live_at_clicked is None or live_at_clicked.color != own_color:
            return False
        return True

    def _premove_chain_piece(self, spec_piece: Piece | None, live_piece: Piece | None,
                             current_turn: PieceColor,
                             local_color: PieceColor | None) -> Piece | None:
        """
        The piece a click is really aiming at once premoves have been queued:
        the one the projection says will be standing there, so a chain can
        carry on from a square whose piece has not moved yet. It only applies
        off your own turn, to your own colour, and never where one of your
        pieces is really standing already

        :param spec_piece: piece on that square in the projected position
        :param live_piece: piece really standing there now
        :param current_turn: side to move
        :param local_color: colour this client plays online, None when both
            sides are played on this machine
        :returns: the projected piece to carry the chain on with, or None when
            this is not a chaining click
        """
        if self.premove_color is None or spec_piece is None:
            return None
        if local_color is None or local_color != self.premove_color:
            return None
        if current_turn == local_color:
            return None
        if spec_piece.color != self.premove_color:
            return None
        if live_piece is not None and live_piece.color == self.premove_color:
            return None
        return spec_piece

    def _effective_grid(self) -> list[list[Piece | None]]:
        """
        The position clicks are read against: the live one, or the live one
        with the queued premoves projected onto it. Reading clicks against the
        projection is what lets a player keep planning several moves ahead

        :returns: an 8x8 grid of pieces, None where a square is empty
        """
        if not self.premoves:
            return self.match.state
        return speculative_board(self.match, self.premoves)

    def _resolve_chain_tip(self, square: Square) -> Square:
        """
        Follow the queued premoves from a square to wherever that piece ends up
        once they have all run, which is where any further premove for it has
        to start

        :param square: square to start following from
        :returns: the end of the chain, the square itself when nothing moves it
        """
        sq = square
        for pm in self.premoves:
            if pm.from_sq == sq:
                sq = pm.to_sq
        return sq

    def _try_select_for_premove(self, square: Square, piece: Piece) -> bool:
        """
        Pick a piece up to premove with. Online only your own pieces may be
        held, and reaching for a piece of the other colour throws the existing
        queue away rather than mixing two sides' premoves together

        :param square: square the piece is on
        :param piece: piece being picked up
        :returns: True when the piece was picked up
        """
        local_color = self._local_color
        if local_color is not None and piece.color != local_color:
            return False
        if self.premove_color is not None and self.premove_color != piece.color:
            self.clear_premoves()
        self.selected_square = square
        return True

    def _queue_premove(self, from_sq: Square, to_sq: Square, piece: Piece) -> bool:
        """
        Add one move to the premove queue. The only test is that the piece
        could be shaped to reach the target -- the position it will meet is not
        known yet -- so a premove may still turn out illegal and be thrown away
        when its turn comes round

        :param from_sq: square the premove starts from
        :param to_sq: square it aims at
        :param piece: piece being premoved, read from the projected position
        :returns: True when the premove was queued
        """
        if from_sq == to_sq:
            return False
        if not piece_can_pseudo_reach(piece, from_sq, to_sq):
            return False
        if self.premove_color is not None and self.premove_color != piece.color:
            self.clear_premoves()
        self.premoves.append(Premove(from_sq, to_sq, piece))
        self.premove_color = piece.color
        if self.on_premove_queued is not None:
            self.on_premove_queued(piece.type)
        return True

    def clear_premoves(self) -> None:
        """
        Throw the whole premove queue away, which a cancelling click, a new
        game and a premove that turned out illegal all do
        """
        self.premoves = []
        self.premove_color = None

    def try_apply_next_premove(self) -> bool:
        """
        Play the front of the premove queue now that it is that colour's turn,
        which the game screen attempts once the board has settled. A premove
        that trips the skill-check gate is taken off the queue and handed to
        the check instead of being played here, and one the position has made
        illegal takes the rest of the queue down with it

        :returns: True when a premove was played
        """
        if (not self.premoves
                or self.premove_color != self.match.current_turn()
                or self.pending_promotion_square is not None
                or self.is_animating()):
            return False
        pm = self.premoves[0]
        if self.skillcheck_gate is not None and self.skillcheck_gate(pm.from_sq, pm.to_sq):
            self._consume_premove()
            return False
        result = self.match.try_move(pm.from_sq, pm.to_sq)
        if not result.legal:
            self.clear_premoves()
            return False
        self._consume_premove()
        self._start_move_animation(pm.from_sq, pm.to_sq, result.promotion_required)
        return True

    def _consume_premove(self) -> None:
        """
        Drop the premove at the front of the queue, forgetting the queue's
        colour once the last one has gone
        """
        self.premoves.pop(0)
        if not self.premoves:
            self.premove_color = None

    def animate_remote_move(self, from_sq: Square, to_sq: Square) -> None:
        """
        Play the opponent's move on this board once the server has confirmed
        it, with exactly the choreography a local move gets

        :param from_sq: square their piece left
        :param to_sq: square it arrived on
        """
        self._start_move_animation(from_sq, to_sq, promotion_required=False)

    def _start_move_animation(self, from_sq: Square, to_sq: Square,
                              promotion_required: bool) -> None:
        """
        Choreograph a ply the engine has just accepted -- the one place a move
        becomes something to watch. Browsing snaps back to the live position
        here, so a landing move always returns the board to the present, and
        the marks are cleared with it. A capture is handed to the shootout
        choreography while a plain move simply slides, and a piece the player
        is still holding settles instead, so their own drag is never yanked out
        from under them

        :param from_sq: square the piece left
        :param to_sq: square it lands on
        :param promotion_required: whether the ply still needs a promotion
            piece, in which case the picker opens as the piece arrives
        """
        self.review_ply = None
        self._target_ply = None
        self.cancel_animations()
        self.effects.cut(pg.time.get_ticks())
        self.clear_all_annotations()
        entry = self.match.move_history[-1]
        moving_piece = entry.move.piece

        on_complete: Callable[[], None] = (
            (lambda: self._set_pending_promotion(to_sq))
            if promotion_required
            else self._fire_move_landed
        )

        own_drag = self.dragging_from is not None and from_sq == self.dragging_from
        if self.dragging_from is not None and not own_drag:
            self.drag.reanchor_for_remote(entry, from_sq, to_sq)

        if entry.move.captured is not None and self._capture_choreography(
                entry, from_sq, to_sq, moving_piece, on_complete, clear_drag=own_drag):
            return

        if own_drag:
            self.last_animation_completed_at_ms = pg.time.get_ticks()
            if entry.move.is_castle:
                self.drag.begin_settle(to_sq, None)
                self._start_castle_rook_animation(entry, from_sq, on_complete=on_complete)
            elif self.drag.is_active():
                self.drag.begin_settle(to_sq, on_complete)
            else:
                on_complete()
            return

        self.start_animation(from_sq, to_sq, moving_piece, on_complete=on_complete)

        if entry.move.is_castle:
            self._start_castle_rook_animation(entry, from_sq)

    @staticmethod
    def _castle_rook_squares(home_row: int, king_to_col: int) -> tuple[Square, Square]:
        """
        Where the rook starts and finishes in a castle, worked out from the
        king's destination so the rook can be animated alongside it

        :param home_row: back rank of the side castling
        :param king_to_col: column the king lands on, which says whether this
            is short or long castling
        :returns: the rook's from and to squares
        """
        if king_to_col == 6:
            return Square(home_row, 7), Square(home_row, 5)
        return Square(home_row, 0), Square(home_row, 3)

    def _start_castle_rook_animation(self, entry: HistoryEntry, king_from_sq: Square,
                                     on_complete: Callable[[], None] | None = None) -> None:
        """
        Slide the rook across as the other half of a castle, so both pieces are
        seen to move together

        :param entry: history entry for the castling ply
        :param king_from_sq: square the king left, which gives the back rank
        :param on_complete: called when the rook lands, used when the rook is
            the animation carrying the move's consequences
        """
        rook_from, rook_to = self._castle_rook_squares(
            king_from_sq.row, entry.move.to_sq.col)
        rook_piece = cast(Piece, self.match.piece_at(rook_to))
        self.start_animation(rook_from, rook_to, rook_piece, on_complete=on_complete)

    def start_undo_animation(self, move: Move) -> None:
        """
        Slide the last move back where it came from after a takeback, rook
        included when it was a castle. The engine has already been rewound, so
        this only replays the motion in reverse

        :param move: the move that has just been taken back
        """
        self.effects.clear_transients()
        moving_piece = self.match.piece_at(move.from_sq)
        if moving_piece is None:
            return
        self.start_animation(move.to_sq, move.from_sq, moving_piece)
        if move.is_castle:
            rook_home, rook_post = self._castle_rook_squares(
                move.from_sq.row, move.to_sq.col)
            rook_piece = cast(Piece, self.match.piece_at(rook_home))
            self.start_animation(rook_post, rook_home, rook_piece)

    def _set_pending_promotion(self, sq: Square) -> None:
        """
        Open the promotion picker now that the pawn has arrived -- unless the
        auto-queen setting is on, in which case it simply becomes a queen and
        the ply finishes without asking

        :param sq: square the promoting pawn now stands on
        """
        if self.auto_queen_provider():
            self._promote_landed(sq, PieceType.QUEEN)
            return
        self.pending_promotion_square = sq

    def _fire_move_landed(self) -> None:
        """
        Tell the screen a ply has finished landing, which is where the move
        sounds and the per-ply bookkeeping hang. A promotion that has not been
        completed yet is deliberately not reported, so a ply is announced
        exactly once
        """
        if self.move_landed_callback is None or not self.match.move_history:
            return
        entry = self.match.move_history[-1]
        if entry.position_key_added is None:
            return
        self.move_landed_callback(entry)

    def _capture_choreography(self, entry: HistoryEntry, from_sq: Square, to_sq: Square,
                              moving_piece: Piece, on_complete: Callable[[], None],
                              clear_drag: bool = True) -> bool:
        """
        Stage a capture as a shootout: the capturer draws, fires, the victim
        goes down, and only then does the piece advance onto the square. It
        needs both sprites and a real square size, and where it cannot have
        them it credits the kill and leaves the caller to animate the move
        plainly

        :param entry: history entry for the capturing ply
        :param from_sq: square the capturer shoots from
        :param to_sq: square it advances onto
        :param moving_piece: the capturing piece
        :param on_complete: called once the advance lands, carrying the move's
            consequences
        :param clear_drag: let go of a held piece first, done when the capture
            is the player's own drag
        :returns: True when the choreography took the move over, False when the
            caller has to animate it itself
        """
        captured = cast(Piece, entry.move.captured)
        color = moving_piece.color.value
        victim_sq = (Square(from_sq.row, to_sq.col)
                     if entry.move.is_en_passant else to_sq)
        attacker = self.piece_images_scaled.get((moving_piece.type, moving_piece.color))
        victim = self.piece_images_scaled.get((captured.type, captured.color))
        if attacker is None or victim is None or self.cell_size <= 0:
            self._on_capture_fire(entry, color, victim_sq, False)
            return False
        if clear_drag:
            self.drag.clear_drag_state()
        self.effects.capture(
            now_ms=pg.time.get_ticks(),
            attacker_type=moving_piece.type.value,
            attacker_surface=attacker, victim_surface=victim,
            from_sq=from_sq, victim_sq=victim_sq, to_sq=to_sq,
            cell_size=self.cell_size, power=self._capture_power(captured.type),
            occupied=self._occupied_squares(),
            on_fire=lambda advance_only: self._on_capture_fire(entry, color, victim_sq,
                                                               advance_only),
            on_slide=lambda: self.start_animation(from_sq, to_sq, moving_piece,
                                                  on_complete=on_complete),
        )
        return True

    def _occupied_squares(self) -> set[Square]:
        """
        Every square with a piece on it, handed to the shot effects so a stray
        pellet can wound a bystander on its way past

        :returns: the occupied squares of the live position
        """
        return {Square(r, c) for r, c in product(range(BOARD_SIZE), repeat=2)
                if self.match.piece_at(Square(r, c)) is not None}

    def _on_capture_fire(self, entry: HistoryEntry, color: str, victim_sq: Square,
                         advance_only: bool) -> None:
        """
        React to the trigger being pulled: the weapon sound fires and the kill
        goes on the shooter's streak. A capture that only advances the piece --
        the shot having already been taken during a skill check -- does neither

        :param entry: history entry for the capturing ply
        :param color: shooter's colour as its wire value, "white" or "black"
        :param victim_sq: square the piece being taken stands on, which for en
            passant is not the destination square
        :param advance_only: whether the shot was already fired elsewhere
        """
        if advance_only:
            return
        if self.shot_callback is not None:
            self.shot_callback(entry)
        self._credit_kill(color, victim_sq, entry.move.captured)

    def whack_kill_at(self, px: tuple[float, float] | None, victim_sq: Square | None,
                      color: str | None, victim_piece: Piece | None) -> None:
        """
        Register the kill a whack-a-mole check has just scored at a point on
        the board rather than on a square, since that check is aimed with the
        cursor. The impact plays where the shot actually landed and the kill
        counts towards the shooter's streak like any other

        :param px: point the shot landed on in window pixels, None when the
            check reported none
        :param victim_sq: square the victim stands on, None when unknown
        :param color: shooter's colour as its wire value, None when unknown
        :param victim_piece: piece that was taken, which picks the hit sound
        """
        if px is None or victim_sq is None or color is None or self.cell_size <= 0:
            return
        self.effects.impact_px(pg.time.get_ticks(), px, self.cell_size)
        self._credit_kill(color, victim_sq, victim_piece, px=px)

    def _credit_kill(self, color: str, victim_sq: Square, victim_piece: Piece | None,
                     px: tuple[float, float] | None = None) -> None:
        """
        Put a kill on the shooter's streak and let the screen announce whatever
        the effects decided it was worth -- a plain hit, first blood or a
        streak call

        :param color: shooter's colour as its wire value, "white" or "black"
        :param victim_sq: square the kill happened on
        :param victim_piece: piece that was taken, which picks the hit sound
        :param px: exact point of impact in window pixels, when the shot was
            aimed rather than fired at a whole square
        """
        key = self.effects.register_kill(color, victim_sq, self.cell_size,
                                         pg.time.get_ticks(), px=px)
        if self.announce_callback is not None and key is not None:
            self.announce_callback(key, victim_piece)

    def trigger_skillcheck_fail(self, from_sq: Square, to_sq: Square,
                                on_fire: Callable[[PieceType], None] | None = None) -> None:
        """
        Play the miss: the shot goes wide, the piece swears about it and the
        target survives. Nothing on the board changes hands -- that is the
        whole point of a missed check, the move gets locked rather than played

        :param from_sq: square the shooter stands on
        :param to_sq: square it was aiming at
        :param on_fire: called with the shooter's piece type at the frame the
            shot goes off, for the weapon sound
        """
        handed = self.effects.take_gun_handoff(from_sq)
        piece = self.match.piece_at(from_sq)
        if piece is None or self.cell_size <= 0:
            return
        now = pg.time.get_ticks()
        victim_sq = self.capture_victim_square(piece, from_sq, to_sq)
        if victim_sq is None:
            self._start_bump_animation(from_sq, to_sq, piece)
            self.effects.swear(now, from_sq, self.cell_size)
            return
        victim = self.match.piece_at(victim_sq)
        power = self._capture_power(victim.type) if victim is not None else "med"
        fire_cb = (lambda advance_only: on_fire(piece.type)) if on_fire is not None else None
        self.effects.miss(
            now_ms=now,
            attacker_type=piece.type.value,
            from_sq=from_sq, victim_sq=victim_sq,
            cell_size=self.cell_size, power=power,
            occupied=self._occupied_squares(), on_fire=fire_cb, predrawn=handed)
        self.effects.swear(now, from_sq, self.cell_size)

    def capture_victim_square(self, piece: Piece, from_sq: Square,
                              to_sq: Square) -> Square | None:
        """
        Which square the piece being taken actually stands on: the destination
        for an ordinary capture, the square beside it for en passant. It also
        doubles as the test for whether a move is a capture at all, which is
        what decides if a skill check is owed

        :param piece: piece making the move
        :param from_sq: square it starts on
        :param to_sq: square it is aimed at
        :returns: the victim's square, or None when the move takes nothing
        """
        if self.match.piece_at(to_sq) is not None:
            return to_sq
        if piece.type == PieceType.PAWN and from_sq.col != to_sq.col:
            return Square(from_sq.row, to_sq.col)
        return None

    def _start_bump_animation(self, from_sq: Square, to_sq: Square, piece: Piece) -> None:
        """
        Nudge a piece towards a square and back, the way a move that was
        refused reads -- it tried and did not get there

        :param from_sq: square the piece stays on
        :param to_sq: square it lunges towards
        :param piece: piece to draw
        """
        self.cancel_animations()
        self.start_animation(from_sq, to_sq, piece, bump=True)

    def restore_piece(self, square: Square) -> None:
        """
        Drop a piece back onto its square after it survived a missed shot,
        which is how a piece the check overlay had taken over returns to the
        board rather than blinking back into place

        :param square: square the surviving piece stands on
        """
        piece = self.match.piece_at(square)
        if piece is None or self.cell_size <= 0:
            return
        surface = self.piece_images_scaled.get((piece.type, piece.color))
        if surface is None:
            return
        self._restore_anims.append({"sq": square, "surf": surface,
                                    "start": pg.time.get_ticks(), "dur": RESTORE_MS})

    def _draw_restores(self, now: int) -> None:
        """
        Draw the pieces dropping back onto the board and let go of the ones
        that have finished landing

        :param now: pygame tick count in milliseconds
        """
        survivors = []
        for a in self._restore_anims:
            t = (now - a["start"]) / a["dur"]
            if t >= 1.0:
                continue
            survivors.append(a)
            self._blit_restore(a, *self._restore_state(t))
        self._restore_anims = survivors

    def _blit_restore(self, a: dict[str, Any], dy: float, alpha: int, angle: float) -> None:
        """
        Draw one falling piece at the height, fade and tilt the animation says
        it should have reached, pivoting on its base so it rocks like something
        that has just been set down

        :param a: the restore animation -- its square, sprite, start and length
        :param dy: vertical offset as a fraction of a square, negative is above
        :param alpha: opacity from 0 to 255
        :param angle: tilt in degrees, 0 while the piece is still falling
        """
        rect = self._cell_rect(a["sq"].row, a["sq"].col)
        img = a["surf"]
        top = rect.y + dy * self.cell_size
        if angle == 0.0:
            if alpha < 255:
                img = img.copy()
                img.set_alpha(alpha)
            self.window.blit(img, (rect.x, top))
            return
        base = (rect.x + img.get_width() / 2.0, top + img.get_height())
        rotated = pg.transform.rotozoom(img, angle, 1.0)
        if alpha < 255:
            rotated = rotated.copy()
            rotated.set_alpha(alpha)
        off = pg.math.Vector2(0.0, img.get_height() / 2.0).rotate(-angle)
        self.window.blit(rotated, rotated.get_rect(center=(base[0] - off.x, base[1] - off.y)))

    @staticmethod
    def _restore_state(t: float) -> tuple[float, int, float]:
        """
        How a piece dropping back onto the board should look at one moment of
        its fall: it drops in, fades up, then rocks itself still

        :param t: progress through the animation, 0 to 1
        :returns: the vertical offset as a fraction of a square, the opacity
            and the tilt in degrees
        """
        alpha = int(255 * smoothstep(min(t / RESTORE_FADE_PORTION, 1.0)))
        if t < RESTORE_FALL_PORTION:
            p = t / RESTORE_FALL_PORTION
            return -RESTORE_DROP_FRAC * (1.0 - p * p), alpha, 0.0
        q = (t - RESTORE_FALL_PORTION) / (1.0 - RESTORE_FALL_PORTION)
        envelope = math.exp(-RESTORE_SETTLE_DECAY * q)
        dy = -RESTORE_REBOUND_FRAC * envelope * math.sin(RESTORE_SETTLE_WAVES * 2.0 * math.pi * q)
        angle = RESTORE_ROCK_DEG * envelope * math.sin(RESTORE_ROCK_WAVES * 2.0 * math.pi * q)
        return dy, alpha, angle

    def show_surrender_flag(self, color: PieceColor) -> None:
        """
        Raise a white flag over the losing king, the board's own way of marking
        a resignation or a mate

        :param color: side that has given up
        """
        if self.cell_size <= 0:
            return
        king_sq = king_square(self.match.state, color)
        if king_sq is not None:
            self.effects.raise_flag(king_sq, self.cell_size, pg.time.get_ticks())

    def show_checkmate_takeover(self, winner_label: str) -> None:
        """
        Take the screen over to call a checkmate, with the shake that goes with
        it. The result menu waits for this to play out, so the celebration is
        never cut short

        :param winner_label: how the winner is named on the takeover card
        """
        now = pg.time.get_ticks()
        self.effects.start_takeover("CHECKMATE", winner_label, now)
        self.effects.trigger_shake(now, "hard")

    @staticmethod
    def _capture_power(victim_type: PieceType) -> str:
        """
        How heavy a capture should feel, which sets the screen shake and the
        weight of the impact: taking a queen or a rook hits hardest, a pawn
        least

        :param victim_type: piece being taken
        :returns: the power band, "hard", "med" or "soft"
        """
        if victim_type in (PieceType.QUEEN, PieceType.ROOK):
            return "hard"
        if victim_type == PieceType.PAWN:
            return "soft"
        return "med"

    def show_check_gun(self, entry: HistoryEntry) -> None:
        """
        Leave the checking piece holding its weapon on the enemy king, so where
        a check comes from can be seen at a glance. Nothing is drawn while the
        player is browsing an earlier position, since the check belongs to the
        live one

        :param entry: history entry for the ply that gave check
        """
        if self.cell_size <= 0 or self.review_ply is not None:
            return
        by_color = entry.move.piece.color
        king_color = opponent_of(by_color)
        king_sq = king_square(self.match.state, king_color)
        if king_sq is None:
            return
        checker = checking_square(self.match.state, king_sq, by_color)
        if checker is None:
            return
        self.effects.check(now_ms=pg.time.get_ticks(),
                           attacker_type=cast(Piece, self.match.piece_at(checker)).type.value,
                           king_sq=king_sq, from_sq=checker, cell_size=self.cell_size)

    def _try_select(self, square: Square) -> bool:
        """
        Pick a piece up for a real move, on exactly the terms every other click
        path asks about: it has to be there, it has to belong to the side to
        move, and online it has to be yours

        :param square: square that was clicked
        :returns: True when the piece was picked up
        """
        piece = self.match.piece_at(square)
        if not self._is_real_move_eligible(
                piece, self.match.current_turn(), self._local_color):
            return False
        self.selected_square = square
        return True

    def _draw_selection_highlight(self) -> None:
        """
        Ring the selected square, unless that piece is already being shown
        somewhere else -- held in a drag, or drawn at the end of a premove
        chain -- so the same piece is never marked twice
        """
        if self.selected_square is None:
            return
        if self.dragging_from is not None and self.selected_square == self.dragging_from:
            return
        if self.selected_square == self._active_chain_tip():
            return

        rect = self._cell_rect(self.selected_square.row, self.selected_square.col)
        self.window.blit(self._cell_overlay(Colors.selection_fill), rect.topleft)
        pg.draw.rect(self.window, Colors.accent, rect, 4)
