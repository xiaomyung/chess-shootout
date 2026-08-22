from typing import Any

import pygame as pg

from chessshootout.frontend.visual.cache import new_cache, memoized_surface
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import SQRT2, cut_rect_surface, supersample
from chessshootout.frontend.visual.fonts import get_font


_RAIL_CACHE = new_cache()


DEFAULT_PADDING = 12
MODAL_CUT = 12
MODAL_RAIL = 5
MODAL_MAX_WIDTH = 440
BUTTON_VPAD = 16

INTENT_RAIL: dict[str | None, str] = {
    "win": Colors.win,
    "loss": Colors.loss,
    "draw": Colors.text_dim,
}


class BaseModal:
    """
    The shell every modal in the game is built on: the cut-corner panel with a
    coloured rail across its top that gives confirms, the online cards and the
    result menu one shared look. Subclasses draw their contents inside it and
    never rebuild the shell for themselves
    """

    def __init__(self, window: pg.Surface) -> None:
        """
        Create a modal that starts out hidden, bound to the window it paints
        on. Modals live for the whole run and are shown and hidden again
        rather than rebuilt per use

        :param window: the app window surface this modal draws onto
        """
        self.window = window
        self.rect = pg.Rect(0, 0, 0, 0)
        self.padding = DEFAULT_PADDING
        self.visible = False

    def set_rect(self, rect: pg.Rect) -> None:
        """
        Place the modal, which the shell does from its layout pass at startup,
        on every window resize and on every screen switch. Whatever a subclass
        scales off the size is rebuilt through _on_rect_changed

        :param rect: area the modal may use, in window pixels
        """
        self.rect = pg.Rect(rect)
        self._on_rect_changed()

    def _on_rect_changed(self) -> None:
        """
        React to a new size; this is where subclasses rebuild fonts and any
        geometry measured off the modal. The base modal has nothing to rebuild
        """
        pass

    def font(self, factor: int, min_size: int = 12, bold: bool = True) -> pg.font.Font:
        """
        Pick a font sized off the modal's own height, so text grows with the
        window instead of being pinned to pixels. It serves the simpler modals
        that keep no font cache of their own

        :param factor: divisor applied to the modal height; larger means
            smaller text
        :param min_size: floor in points, so text stays readable in a small
            window
        :param bold: True for the bold cut of the face
        :returns: font at the computed size
        """
        size = max(int(self.rect.height / factor), min_size)
        return get_font(size, bold=bold)

    def show(self, *args: Any, **kwargs: Any) -> None:
        """
        Put the modal on screen. The signature is open because subclasses
        override it with their own required arguments -- a question, a
        callback, a starting folder -- and each fills its state in before
        calling up to here with nothing

        :param args: ignored here; the arguments a subclass declares instead
        :param kwargs: ignored here; the keyword arguments a subclass declares
        """
        self.visible = True

    def hide(self) -> None:
        """
        Take the modal off screen. Subclasses override to drop their callbacks
        as well, so a late click cannot fire into a game that has moved on
        """
        self.visible = False

    def is_visible(self) -> bool:
        """
        Say whether the modal is on screen, which is what decides that it
        blocks input, owns Esc and gets drawn over the screen behind it

        :returns: True while the modal is showing
        """
        return self.visible

    def draw(self) -> None:
        """
        Paint the modal, called every frame by the shell for the global modals
        and by the active screen for the ones it owns. A base modal draws
        nothing at all
        """
        pass

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Take a left click that landed while this modal was the topmost visible
        one. The shell stops at that modal, so the click never reaches the
        screen behind it whatever the answer here

        :param pos: click position in window pixels
        :returns: True when the modal acted on the click
        """
        return False

    def content_rect(self, rect: pg.Rect | None = None) -> pg.Rect:
        """
        Give the area inside the shell that contents may use, with the rail
        and the padding already taken off. Every modal lays its text and
        buttons out inside this rect

        :param rect: panel to measure, or None for the modal's whole rect
        :returns: usable content area in window pixels
        """
        r = rect if rect is not None else self.rect
        return pg.Rect(
            r.x + self.padding,
            r.y + MODAL_RAIL + self.padding,
            r.width - 2 * self.padding,
            r.height - MODAL_RAIL - 2 * self.padding,
        )

    def draw_shell(self, intent: str | None = None, rect: pg.Rect | None = None) -> None:
        """
        Draw the cut-corner panel and its rail. This is the one place the
        modal shell is built, so no modal draws a panel of its own; the rail
        takes its colour from the intent, which is how a loss reads red and a
        win reads green

        :param intent: win, loss or draw to colour the rail, None for the
            standard accent
        :param rect: panel to draw, or None to fill the modal's whole rect
        """
        r = rect if rect is not None else self.rect
        if r.width <= 0 or r.height <= 0:
            return
        panel = cut_rect_surface(r.size, MODAL_CUT, Colors.surface_raised,
                                 border=Colors.border_strong, border_width=1,
                                 corners=("tr", "bl"))
        self.window.blit(panel, r.topleft)
        self.window.blit(self._rail_surface(intent, r.width), r.topleft)

    def _rail_surface(self, intent: str | None, width: int) -> pg.Surface:
        """
        Build, and from then on reuse, the coloured rail along the top edge of
        the shell, mitred to follow the panel's cut corner. Rails are cached
        per colour and width because they are blitted every frame

        :param intent: win, loss or draw; anything else means the accent colour
        :param width: panel width in pixels the rail has to span
        :returns: rail surface to blit at the panel's top-left corner
        """
        color = INTENT_RAIL.get(intent, Colors.accent)

        def build() -> pg.Surface:
            """
            Render the rail for this colour and width, called only when the
            cache has nothing for them yet

            :returns: freshly drawn rail surface
            """
            def render(surf: pg.Surface, k: int) -> None:
                """
                Draw the rail polygon at supersampled scale, mitring the
                top-right corner so the rail follows the panel's cut

                :param surf: oversized surface being drawn into
                :param k: supersample factor every size must be multiplied by
                """
                w, h = surf.get_size()
                cutk = MODAL_CUT * k
                railk = MODAL_RAIL * k
                diag = railk * SQRT2
                pg.draw.polygon(surf, pg.Color(color),
                                [(0, 0), (w - cutk, 0), (w, cutk), (w, cutk + diag),
                                 (w - cutk + railk * (1.0 - SQRT2), railk),
                                 (0, railk)])
            return supersample((width, MODAL_CUT + MODAL_RAIL * 2), render)
        return memoized_surface(_RAIL_CACHE, (intent, width, str(color)), build)
