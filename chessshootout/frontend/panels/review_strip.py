import pygame as pg

from chessshootout.backend.pieces import PieceColor, PieceType
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.fonts import get_font, DISPLAY
from chessshootout.frontend.visual.widgets import (
    StripAvatar, strip_frame_metrics, draw_captured_row,
)


class ReviewStrip:
    """
    One player's slim band above or below the board on the review screen:
    avatar, name, the pieces that player took and their material lead. A saved
    game has no clock, no opponent to connect to and nothing counting down, so
    this is the in-game strip with all of the live state left out
    """

    def __init__(self, window: pg.Surface) -> None:
        """
        Build an empty strip with placeholder fonts. The review screen makes
        two of these when it is created and reuses them for every PGN it
        opens, so every field here is overwritten before anything is drawn

        :param window: the app window this strip paints into
        """
        self.window = window
        self.rect = pg.Rect(0, 0, 0, 0)
        self.name = ""
        self.player_color = PieceColor.WHITE
        self.captured: list[PieceType] = []
        self.advantage = 0
        self.captured_color: PieceColor | None = None
        self.icons: dict[tuple[PieceType, PieceColor], pg.Surface] = {}
        self.name_font = get_font(14, bold=True)
        self.advantage_font = get_font(12, bold=True)
        self.letter_font = get_font(18, family=DISPLAY)
        self._avatar = StripAvatar()

    def set_rect(self, rect: pg.Rect, scale: float = 1.0) -> None:
        """
        Place the strip and rebuild every font against its new height, which is
        how the whole band scales with the window. The avatar's cached tile is
        dropped here, so nothing sized for the old height survives a resize

        :param rect: the strip's area in window pixels
        :param scale: the layout's global scale factor, taken so both strip
            flavours share one call shape; this strip sizes itself from the
            height alone
        """
        self.rect = pg.Rect(rect)
        h = rect.height
        ih = max(int(h * 0.68), 1)
        self.name_font = get_font(max(int(ih * 0.42), 11), bold=True)
        self.advantage_font = get_font(max(int(ih * 0.26), 8), bold=True)
        self.letter_font = get_font(max(int(ih * 0.5), 11), family=DISPLAY)
        self._avatar.reset()

    def set_piece_icons(self, icons: dict[tuple[PieceType, PieceColor], pg.Surface]) -> None:
        """
        Adopt the captured-piece artwork the board scaled for this strip's
        height, used to draw the row of pieces a player has taken

        :param icons: piece type and colour to its scaled sprite
        """
        self.icons = icons

    def set_state(self, name: str, player_color: PieceColor,
                  captured: list[PieceType] | None = None, advantage: int = 0,
                  captured_color: PieceColor | None = None) -> None:
        """
        Take this frame's whole picture of one player from the review screen,
        which rebuilds it from the ply currently being browsed. Every field is
        replaced outright, so the strip never holds an opinion of its own

        :param name: display name, read from the PGN's White or Black tag
        :param player_color: side this strip belongs to
        :param captured: pieces this player had taken by the browsed ply,
            strongest first
        :param advantage: material lead in pawn units; only a positive number
            shows a badge
        :param captured_color: colour of the taken pieces, which picks their
            artwork
        """
        self.name = name
        self.player_color = player_color
        self.captured = captured or []
        self.advantage = advantage
        self.captured_color = captured_color

    def draw(self) -> None:
        """
        Paint the whole strip for this frame: the panel, the avatar, then the
        name and captured row beside it, and the outline last. A strip with no
        room yet -- before the first layout -- draws nothing
        """
        h = self.rect.height
        if h <= 0 or self.rect.width <= 0:
            return
        pad, radius, av_size, gap = strip_frame_metrics(h)
        pg.draw.rect(self.window, Colors.surface, self.rect, border_radius=radius)

        avatar_rect = pg.Rect(self.rect.x + pad, self.rect.y + pad, av_size, av_size)
        self._avatar.draw(self.window, avatar_rect, self.name, self.letter_font)

        self._draw_name_and_captures(avatar_rect.right + gap, av_size)

        pg.draw.rect(self.window, Colors.border, self.rect, width=1, border_radius=radius)

    def _draw_name_and_captures(self, x: int, ih: int) -> None:
        """
        Stack the player's name over their captured pieces in the space to the
        right of the avatar. A name too long for that space is cut off rather
        than allowed to run past the strip's edge

        :param x: left edge of the area, just right of the avatar
        :param ih: inner height of the strip in pixels, which sizes the
            captured icons
        """
        top_y = self.rect.y + max(int(self.rect.height * 0.18), 4)
        name_surf = self.name_font.render(self.name, True, Colors.text)
        max_name_w = max(self.rect.right - x - 8, 1)
        if name_surf.get_width() > max_name_w:
            name_surf = name_surf.subsurface(pg.Rect(0, 0, max_name_w, name_surf.get_height()))
        self.window.blit(name_surf, (x, top_y))
        bottom_cy = self.rect.bottom - max(int(self.rect.height * 0.22), 8)
        self._draw_captured(x, bottom_cy, ih)

    def _draw_captured(self, x: int, cy: int, ih: int) -> None:
        """
        Draw the overlapping row of pieces this player has taken and, when they
        are ahead on material, the +N badge that closes it off. Being level or
        behind shows no badge, so only a lead is ever advertised

        :param x: left edge of the row in window pixels
        :param cy: vertical centre of the row
        :param ih: inner height of the strip, which sizes the icons
        """
        right_bound = self.rect.right - 8
        last_right = draw_captured_row(
            self.window, self.icons, self.captured, self.captured_color, x, cy, right_bound, ih)
        if self.advantage > 0:
            self._draw_advantage_pill(last_right + max(int(ih * 0.18), 5), cy, right_bound)

    def _draw_advantage_pill(self, x: int, cy: int, right_bound: int) -> None:
        """
        Draw the amber +N chip that states how far ahead on material this
        player is, in pawn units. A chip that would cross the right bound is
        dropped instead of spilling out of the strip

        :param x: left edge of the chip in window pixels
        :param cy: vertical centre of the row it belongs to
        :param right_bound: hard right edge the chip must stay inside
        """
        text = self.advantage_font.render(f"+{self.advantage}", True, Colors.on_accent)
        pad_x, pad_y = 6, 3
        w = text.get_width() + 2 * pad_x
        h = text.get_height() + 2 * pad_y
        if x + w > right_bound:
            return
        rect = pg.Rect(x, round(cy - h / 2), w, h)
        pg.draw.rect(self.window, Colors.amber, rect, border_radius=h // 2)
        self.window.blit(text, (rect.centerx - text.get_width() / 2,
                                rect.centery - text.get_height() / 2))
