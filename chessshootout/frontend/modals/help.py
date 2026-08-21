import pygame as pg

from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.modals.base import BaseModal, BUTTON_VPAD
from chessshootout.frontend.visual.scroll_view import ScrollHost, ScrollView
from chessshootout.frontend.visual.widgets import draw_button_row, fit_text_to_rect
from chessshootout.frontend.visual.fonts import get_font, get_mono_font


HOTKEYS = [
    ("?", "Open this help"),
    ("F", "Flip board"),
    ("H", "Focus mode (hide panels)"),
    ("F11", "Toggle fullscreen"),
    ("Z", "Undo move (Ctrl+Z also works; online: takeback request)"),
    ("G", "Give 15 seconds (hold the +15 cap to ramp)"),
    ("A / S / C", "Collapse or expand rail sections"),
    ("R", "Resign"),
    ("D", "Offer draw"),
    ("Q  R  B  N", "Promotion picker (when shown)"),
    ("Space / Click", "Fire the active skill-check (wheel / aim / whack)"),
    ("Arrows / WASD", "Combo check input, or click the on-screen pad"),
    ("Left / Right", "Step through moves (also during live games)"),
    ("Home", "Jump to first move (also during live games)"),
    ("End", "Return to live play"),
    ("Esc", "Back · close modal · resign · quit"),
]

ROW_FONT_SIZE = 15
TITLE_FONT_SIZE = 22
BUTTON_FONT_SIZE = 14
ROW_PAD_Y = 10
MIN_WIDTH = 320
MIN_HEIGHT = 280


class HelpModal(BaseModal, ScrollHost):
    """
    The scrolling hotkey card that both the game and the review screen open
    with ?, drawn in the shared modal shell. Each screen shows it with its own
    list of rows, so one widget serves both; the master list is HOTKEYS in
    this module, which has to stay in step with the hotkey table in the README
    whenever a control is added, renamed or dropped
    """

    def __init__(self, window: pg.Surface) -> None:
        """
        Build the help card once at startup with no rows in it, ready for
        whichever screen shows it first

        :param window: the app window surface this modal draws onto
        """
        super().__init__(window)
        self.button_rects = {}
        self.rows = []
        self._scroll_px = 0.0
        self._content_px = 0
        self._line_h = 1
        self._rows_rect = pg.Rect(0, 0, 0, 0)
        self.scroll = ScrollView(
            lambda: self._scroll_px,
            self._store_scroll,
            lambda: (self._rows_rect, self._content_px),
            wheel_step_px=lambda: self._line_h,
        )

    def set_rect(self, rect: pg.Rect) -> None:
        """
        Place the card, keeping it inside the window and above a minimum size,
        so the hotkey list stays readable however small the window gets

        :param rect: area the shell would like the card to take, in window
            pixels
        """
        win_w, win_h = self.window.get_size()
        margin = 16
        cx = rect.centerx
        cy = rect.centery
        w = min(max(rect.width, MIN_WIDTH), max(win_w - margin, MIN_WIDTH))
        h = min(max(rect.height, MIN_HEIGHT), max(win_h - margin, MIN_HEIGHT))
        x = max(margin // 2, min(cx - w // 2, win_w - w - margin // 2))
        y = max(margin // 2, min(cy - h // 2, win_h - h - margin // 2))
        self.rect = pg.Rect(x, y, w, h)
        self._on_rect_changed()

    def _on_rect_changed(self) -> None:
        """
        Rebuild the title, row, key and button fonts. Help text is sized in
        fixed points rather than off the card, so the rows read the same at
        every window size
        """
        self.title_font = get_font(TITLE_FONT_SIZE, bold=True)
        self.row_font = get_font(ROW_FONT_SIZE, bold=False)
        self.key_font = get_mono_font(ROW_FONT_SIZE)
        self.button_font = get_font(BUTTON_FONT_SIZE, bold=True)

    def show(self, rows: list[tuple[str, str]]) -> None:
        """
        Open the card on one screen's hotkey list, scrolled back to the top.
        The rows come from HOTKEYS in this module, which the README's hotkey
        table mirrors -- change one and the other has to change with it

        :param rows: (keys, description) pairs to list, in the order shown
        """
        super().show()
        self.rows = rows
        self._scroll_px = 0.0
        self.scroll.cancel()

    def hide(self) -> None:
        """
        Close the card and stop any scroll still gliding
        """
        super().hide()
        self.button_rects = {}
        self.scroll.cancel()

    def draw(self) -> None:
        """
        Paint the card: shell, title, the scrolling hotkey rows and the Close
        button. Drawing is also what fixes the rects clicks are tested against
        """
        if not self.visible or self.rect.width <= 0:
            return
        self.scroll.tick()
        self.draw_shell()
        content = self.content_rect()
        pad = self.padding
        title_surf = fit_text_to_rect(
            self.title_font.render("Hotkeys", True, Colors.text),
            pg.Rect(0, 0, content.width, self.title_font.get_height() + 8),
        )
        self.window.blit(
            title_surf, (content.centerx - title_surf.get_width() / 2, content.y))

        button_h = self.button_font.get_height() + BUTTON_VPAD
        button_row = pg.Rect(content.x, content.bottom - button_h, content.width, button_h)

        rows_top = content.y + title_surf.get_height() + pad
        rows_bottom = button_row.y - pad
        self._rows_rect = pg.Rect(
            content.x, rows_top, content.width, max(rows_bottom - rows_top, 1))
        self._draw_rows(self._rows_rect)

        self.button_rects = draw_button_row(
            self.window, button_row, [("Close", "close")],
            self.button_font, pad, primary_keys={"close"}, cut=True,
        )

    def _draw_rows(self, rows_rect: pg.Rect) -> None:
        """
        Draw the slice of the hotkey list that is on screen, keys in the left
        column and what they do in the right, clipped to the rows area with a
        thin line between rows

        :param rows_rect: area the rows may fill, in window pixels
        """
        self._line_h = self.row_font.get_height() + ROW_PAD_Y
        line_h = self._line_h
        self._content_px = len(self.rows) * line_h
        max_px = max(0, self._content_px - rows_rect.height)
        self._scroll_px = max(0.0, min(self._scroll_px, max_px))
        first, sub, n_draw = self.scroll.row_window(rows_rect, line_h)

        prev_clip = self.window.get_clip()
        self.window.set_clip(rows_rect)
        try:
            inner_w = rows_rect.width
            key_col_w = int(inner_w * 0.35)
            desc_col_w = inner_w - key_col_w - self.padding
            shown = self.rows[first:first + n_draw]
            y0 = rows_rect.y - sub
            for i, (key, desc) in enumerate(shown):
                row_y = y0 + i * line_h
                key_rect = pg.Rect(rows_rect.x, row_y, key_col_w, line_h)
                desc_rect = pg.Rect(
                    rows_rect.x + key_col_w + self.padding, row_y,
                    desc_col_w, line_h,
                )
                key_surf = fit_text_to_rect(
                    self.key_font.render(key, True, Colors.amber_hi), key_rect,
                )
                desc_surf = fit_text_to_rect(
                    self.row_font.render(desc, True, Colors.text_dim), desc_rect,
                )
                self.window.blit(
                    key_surf,
                    (key_rect.x, key_rect.centery - key_surf.get_height() // 2),
                )
                self.window.blit(
                    desc_surf,
                    (desc_rect.x, desc_rect.centery - desc_surf.get_height() // 2),
                )
                if i < len(shown) - 1:
                    sep_y = row_y + line_h - 1
                    pg.draw.line(
                        self.window, Colors.border,
                        (rows_rect.x, sep_y), (rows_rect.right, sep_y), 1,
                    )
        finally:
            self.window.set_clip(prev_clip)
        self.scroll.draw_thumb(self.window)

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Close the card when the Close button is clicked; a click anywhere else
        does nothing, leaving the card up

        :param pos: click position in window pixels
        :returns: True when the button took the click
        """
        if not self.visible:
            return False
        for key, br in self.button_rects.items():
            if br.collidepoint(pos):
                self.hide()
                return True
        return False

    def handle_key(self, event: pg.event.Event) -> bool:
        """
        Close the card on any key at all: it is a read-only reference, so the
        player pressing something means they are finished reading it

        :param event: pygame KEYDOWN event
        :returns: True while the card was open, meaning the key was used
        """
        if not self.visible:
            return False
        self.hide()
        return True
