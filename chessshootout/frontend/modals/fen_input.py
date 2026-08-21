from collections.abc import Callable

import pygame as pg

from chessshootout.frontend.modals.base import BaseModal, BUTTON_VPAD
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.text_input import TextInput
from chessshootout.frontend.visual.widgets import draw_button_row, fit_text_to_rect
from chessshootout.frontend.visual.fonts import get_font


FEN_INPUT_MAX_CHARS = 100


class FenInputModal(BaseModal):
    """
    The box where a player pastes a FEN to start a game from a set-up
    position, drawn in the shared modal shell. The menu screen owns it rather
    than the shell, so it is layered after the global modals for Esc and for
    clicks
    """

    def __init__(self, window: pg.Surface) -> None:
        """
        Build the FEN box once with its text field and starting fonts; the
        fonts are resized as soon as the shell hands it a rect

        :param window: the app window surface this modal draws onto
        """
        super().__init__(window)
        self.on_submit = None
        self.error = ""
        self.button_rects = {}
        self.text_input = TextInput(window, max_chars=FEN_INPUT_MAX_CHARS,
                                    placeholder="paste FEN…")
        self.title_font = get_font(20, bold=True)
        self.error_font = get_font(14, bold=False)
        self.button_font = get_font(14, bold=True)

    def _on_rect_changed(self) -> None:
        """
        Resize the title, error and button fonts off the box's own height, so
        the whole thing scales with the window
        """
        self.title_font = self.font(factor=8, min_size=18, bold=True)
        self.error_font = self.font(factor=14, min_size=12, bold=False)
        self.button_font = self.font(factor=14, min_size=12, bold=True)

    def show(self, on_submit: Callable[[str], bool]) -> None:
        """
        Open the box with an empty, focused field and no complaint showing

        :param on_submit: run with the typed FEN; answering False marks the
            position invalid and leaves the box open to be corrected
        """
        super().show()
        self.on_submit = on_submit
        self.error = ""
        self.text_input.text = ""
        self.text_input.focused = True

    def hide(self) -> None:
        """
        Close the box and forget the submit callback, so a late press cannot
        start a game the player had already backed out of
        """
        super().hide()
        self.on_submit = None
        self.text_input.focused = False
        self.button_rects = {}

    def set_error(self, msg: str) -> None:
        """
        Show a short complaint under the field, which is how a rejected FEN is
        explained without throwing away what the player typed

        :param msg: message to show, empty to clear it
        """
        self.error = msg

    def draw(self) -> None:
        """
        Paint the box: shell, title, the FEN field, any complaint under it and
        the Start and Cancel buttons. Drawing is also what fixes the button
        rects clicks are tested against
        """
        if not self.visible or self.rect.width <= 0:
            return
        self.draw_shell()
        content = self.content_rect()
        pad = self.padding
        title_surf = fit_text_to_rect(
            self.title_font.render("Start from FEN", True, Colors.text),
            pg.Rect(0, 0, content.width, self.title_font.get_height() + 6),
        )
        self.window.blit(
            title_surf, (content.centerx - title_surf.get_width() / 2, content.y))

        button_h = self.button_font.get_height() + BUTTON_VPAD
        button_row = pg.Rect(content.x, content.bottom - button_h, content.width, button_h)

        input_h = max(int(self.rect.height * 0.20), 32)
        input_rect = pg.Rect(
            content.x, content.y + title_surf.get_height() + pad, content.width, input_h)
        self.text_input.set_rect(input_rect)
        self.text_input.draw()

        if self.error:
            error_rect = pg.Rect(
                input_rect.x, input_rect.bottom + pad // 2,
                input_rect.width, button_row.y - input_rect.bottom - pad,
            )
            error_surf = fit_text_to_rect(
                self.error_font.render(self.error, True, Colors.accent),
                error_rect,
            )
            self.window.blit(error_surf, (error_rect.x, error_rect.y))

        self.button_rects = draw_button_row(
            self.window, button_row,
            [("Start", "start"), ("Cancel", "cancel")],
            self.button_font, pad, primary_keys={"start"}, cut=True,
        )

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Route a click to the field, to Start or to Cancel; a click anywhere
        else in the box simply drops keyboard focus from the field

        :param pos: click position in window pixels
        :returns: True whenever the box is open
        """
        if not self.visible:
            return False
        if self.text_input.rect.collidepoint(pos):
            self.text_input.focused = True
            return True
        for key, br in self.button_rects.items():
            if br.collidepoint(pos):
                if key == "start":
                    self._submit()
                else:
                    self.hide()
                return True
        self.text_input.focused = False
        return True

    def handle_key(self, event: pg.event.Event) -> bool:
        """
        Feed typing to the FEN field, with Enter submitting exactly as the
        Start button does

        :param event: pygame KEYDOWN event
        :returns: True when the key was used
        """
        if not self.visible:
            return False
        if event.key == pg.K_RETURN:
            self._submit()
            return True
        return self.text_input.handle_key(event)

    def _submit(self) -> None:
        """
        Hand the typed FEN over to be started, complaining in place when the
        field is empty or the position is rejected. A position that is
        accepted leaves the box for the caller to close
        """
        text = self.text_input.text.strip()
        if not text:
            self.set_error("FEN is empty")
            return
        if self.on_submit is None:
            return
        if not self.on_submit(text):
            self.set_error("Invalid FEN")
