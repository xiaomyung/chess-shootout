import logging
from typing import Any

import pygame as pg

from chessshootout.infra import env
from chessshootout.infra.open_external import open_with_default_app
from chessshootout.frontend.layout import compute_layout
from chessshootout.frontend.menu.layout import compute_menu_layout
from chessshootout.frontend.menu.rail import MenuRail
from chessshootout.frontend.menu.rail_cards import CardStack
from chessshootout.frontend.menu.shell import build_views
from chessshootout.frontend.modal_registry import ModalSpec
from chessshootout.frontend.modals.fen_input import FenInputModal
from chessshootout.frontend.screens.base import Screen
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.tween import Tween, out_cubic
from chessshootout.frontend.window_chrome import WindowChrome


log = logging.getLogger("chess.frontend")

MENU_RISE_MS = 520
MENU_RISE_PX = 20
VIEW_RISE_MS = 280
VIEW_RISE_PX = 10
RAIL_SLIDE_MS = 200


class MenuScreen(Screen):
    """
    Everything the player sees outside a game: the nav rail down the left, one
    sub-view at a time beside it -- Play, Profile, Options, History and the
    stubs -- and the card stack on the right. It is a host, not a menu of its
    own: it owns the rail, the transitions and the sub-view registry, and
    forwards every event to whichever sub-view is showing
    """

    name = "menu"
    uses_battle_backdrop = True

    def __init__(self, app: Any) -> None:
        """
        Build the screen once at startup with every sub-view already
        constructed, so switching between them costs nothing later. Rects are
        not known yet -- the shell lays the screen out before it is shown

        :param app: the Frontend shell, this screen's route to the window,
            sound, the settings controller and the online coordinator
        """
        super().__init__(app)
        self.fen_input_modal = FenInputModal(app.window)
        self.views = build_views(app)
        self.rail = MenuRail({"open_url": open_with_default_app})
        self.card_stack = CardStack(app)
        self.card_stack.refresh()
        self._active_view = "play"
        self._menu_layout = None
        self._transition_kind = "none"
        self._transition_duration = 0
        self._transition_tween = None
        self._scratch = None
        self._rail_slide_mode = "none"
        self._rail_slide_tween = None
        self._rail_slide_snapshot = None
        self._rail_slide_origin = None
        self._rail_scratch = None

    @property
    def play_view(self) -> Any:
        """
        The Play sub-view, the hero panel with the mode chips, the time and
        side pickers and the start button. Reached through this one property
        so the facade below never digs into the sub-view registry by key

        :returns: the Play sub-view instance
        """
        return self.views["play"]

    def show_play_view(self) -> None:
        """
        Bring the Play panel back after it was hidden, which the online
        coordinator does whenever a search or a session ends without a game
        """
        self.play_view.show()

    def hide_play_view(self) -> None:
        """
        Hide the Play panel while a game is starting or a search is running,
        so the menu behind a waiting card is not still offering to start
        another match
        """
        self.play_view.hide()

    def play_view_visible(self) -> bool:
        """
        Whether the Play panel is currently on offer, which is how the online
        coordinator tells a menu that is idle from one busy with a search

        :returns: True while the Play panel is showing
        """
        return self.play_view.is_visible()

    def set_reconnect_available(self, available: bool) -> None:
        """
        Show or hide the Reconnect banner on the Play panel, driven by the
        coordinator's probe for a game the player left behind

        :param available: True when there is a game waiting to be rejoined
        """
        self.play_view.set_reconnect_available(available)

    def apply_default_time_settings(self) -> None:
        """
        Pull the default time control and increment from the stored settings
        into the Play panel, so a change made in Options shows on the pickers
        as soon as the player leaves that screen
        """
        self.play_view.apply_default_time_settings()

    def apply_resume_config(self, resume: dict[str, Any]) -> None:
        """
        Dress the Play panel to match the game being rejoined -- online, the
        same time control, the same side -- and restore the nickname that game
        was played under, so a rematch from here carries on as the same player

        :param resume: the server's summary of the game waiting to be resumed
        """
        color = resume["your_color"]
        env.set_nickname(resume["white_name"] if color == "white" else resume["black_name"])
        self.play_view.apply_resume_config(resume)

    def enter(self, **payload: Any) -> None:
        """
        Take over the window and rise into place, called by the shell after
        the previous screen exited. The payload may name which sub-view to
        open; without one the menu comes back to whichever was last showing

        :param payload: navigation payload, optionally carrying the name of
            the sub-view to open
        """
        self._activate(payload.get("view") or self._active_view)
        self._begin_transition("screen", MENU_RISE_MS)

    def _begin_transition(self, kind: str, duration_ms: int) -> None:
        """
        Arm the fade-and-rise the menu plays when it appears. The tween itself
        is built on the first frame that draws it, so the animation starts
        from that frame's clock rather than from whenever this was armed

        :param kind: "screen" for entering the menu, "view" for a sub-view
            swap, which differ only in how far they rise
        :param duration_ms: how long the rise should take, in milliseconds
        """
        self._transition_kind = kind
        self._transition_duration = duration_ms
        self._transition_tween = None

    def _activate(self, name: str) -> None:
        """
        Make one sub-view the showing one and move the rail's marker onto its
        row. Entering Play also rebuilds the right-hand cards, so the recent
        games and the news are fresh every time the player lands there

        :param name: registry name of the sub-view to show
        """
        self._active_view = name
        self.views[name].enter()
        self.rail.set_active(name, pg.time.get_ticks())
        if name == "play":
            self.card_stack.refresh()

    def exit(self) -> None:
        """
        Hand the window back and cancel everything this visit set going: the
        showing sub-view, the rise, the rail slide and the scratch surfaces
        they drew on, so none of it bleeds into the next screen
        """
        super().exit()
        self.views[self._active_view].exit()
        self._transition_kind = "none"
        self._transition_tween = None
        self._scratch = None
        self._end_rail_slide()
        self._rail_scratch = None

    def relayout(self, size: tuple[int, int]) -> None:
        """
        Recompute every rect the menu owns for a new window size: the rail,
        the card stack, each sub-view and the FEN card. Only Play reserves the
        right-hand column, so the space a sub-view gets depends on which one
        is showing. A rail slide in flight is dropped, since it was animating
        between rects that no longer exist

        :param size: window width and height in pixels
        """
        right_rail = self._active_view == "play"
        self._menu_layout = compute_menu_layout(
            size[0], size[1], WindowChrome.HEIGHT, right_rail=right_rail)
        self.rail.set_rect(self._menu_layout.rail_rect, self._menu_layout.scale)
        self.rail.set_active(self._active_view, pg.time.get_ticks())
        self.card_stack.set_rect(self._menu_layout.right_rail_rect, self._menu_layout.scale)
        for view in self.views.values():
            view.relayout(self._menu_layout)
        r = compute_layout(
            size[0], size[1], mode=self.name, focus_mode=False,
            focus_show=env.get_focus_show(), board_size=self.app.game.board.SIZE)
        self.fen_input_modal.set_rect(r.flex_rect)
        self._end_rail_slide()

    def update(self, now: int) -> None:
        """
        Step the showing sub-view one frame and keep the backdrop out of the
        way: the pieces skirmishing behind the menu are told which rects they
        must not wander into. A news feed that finished downloading since the
        last frame rebuilds the cards here

        :param now: pygame tick count in milliseconds since pygame init
        """
        self.views[self._active_view].update(now)
        if (self._active_view == "play"
                and self.app.news_client.generation() != self.card_stack.news_generation()):
            self.card_stack.refresh()
        layout = self._menu_layout
        rects = [layout.rail_rect, layout.right_rail_full_rect]
        rects += self.views[self._active_view].avoid_rects()
        self.app.menu_battle.set_avoid_rects(rects)

    def draw(self) -> None:
        """
        Paint the menu: the rail, the showing sub-view and, on Play, the card
        column. With no transition running it all goes straight to the window;
        during one the content is drawn to a scratch surface instead so it can
        be faded and lifted as a single piece, and the sliding rail column is
        laid over the top either way
        """
        window = self.app.window
        now = pg.time.get_ticks()
        include_rail = self._rail_slide_mode != "in"
        if self._transition_kind == "none":
            self._draw_rail(window, now)
            self._draw_content(window, now, include_rail)
            self._draw_rail_slide(window, now)
            return
        if self._transition_tween is None:
            self._transition_tween = Tween(
                0.0, 1.0, self._transition_duration, now, ease=out_cubic)
        if self._transition_tween.done(now):
            self._transition_kind = "none"
            self._transition_tween = None
            self._draw_rail(window, now)
            self._draw_content(window, now, include_rail)
            self._draw_rail_slide(window, now)
            return
        t = self._transition_tween.value(now)
        scratch = self._ensure_scratch("_scratch")
        scratch.fill((0, 0, 0, 0))
        if self._transition_kind == "screen":
            self._draw_rail(scratch, now)
            self._draw_content(scratch, now, include_rail)
            offset = int((1.0 - t) * MENU_RISE_PX)
        else:
            self._draw_rail(window, now)
            self._draw_content(scratch, now, include_rail)
            offset = int((1.0 - t) * VIEW_RISE_PX)
        scratch.set_alpha(int(255 * t))
        window.blit(scratch, (0, offset))
        self._draw_rail_slide(window, now)

    def _draw_rail(self, surface: pg.Surface, now: int) -> None:
        """
        Draw the nav rail down the left edge, including its animated marker

        :param surface: surface to draw on, the window or a scratch surface
        :param now: pygame tick count in milliseconds since pygame init
        """
        self.rail.draw(surface, now)

    def _draw_content(self, surface: pg.Surface, now: int,
                      include_rail: bool = True) -> None:
        """
        Draw the showing sub-view and, on Play, the panel and cards down the
        right. The right column is skipped while it is sliding in, because the
        slide draws that column itself at its own offset

        :param surface: surface to draw on, the window or a scratch surface
        :param now: pygame tick count in milliseconds since pygame init
        :param include_rail: False while the right column is animating in, so
            it is not painted twice in two places
        """
        self.views[self._active_view].draw(surface, self._menu_layout)
        if include_rail and self._active_view == "play":
            self._draw_right_rail_panel(surface)
            self.card_stack.draw(surface, now)

    def _draw_rail_slide(self, window: pg.Surface, now: int) -> None:
        """
        Animate the right-hand card column off the window when the player
        leaves Play and back on when they return. On the way out a snapshot
        taken before the swap is slid away, since the cards no longer have a
        place in the layout; on the way in the live column is slid in

        :param window: the app window to draw over
        :param now: pygame tick count in milliseconds since pygame init
        """
        if self._rail_slide_mode == "none":
            return
        if self._rail_slide_tween is None:
            self._rail_slide_tween = Tween(0.0, 1.0, RAIL_SLIDE_MS, now, ease=out_cubic)
        t = self._rail_slide_tween.value(now)
        if self._rail_slide_mode == "out":
            origin = self._rail_slide_origin
            x = int(origin.x + t * (window.get_width() - origin.x))
            window.blit(self._rail_slide_snapshot, (x, origin.y))
        else:
            panel = self._menu_layout.right_rail_full_rect
            if panel.width > 0:
                dx = int((1.0 - t) * (window.get_width() - panel.x))
                scratch = self._ensure_scratch("_rail_scratch")
                scratch.fill((0, 0, 0, 0))
                self._draw_right_rail_panel(scratch)
                self.card_stack.draw(scratch, now)
                window.blit(scratch.subsurface(panel), (panel.x + dx, panel.y))
        if self._rail_slide_tween.done(now):
            self._end_rail_slide()

    def _capture_rail_column(self, now: int) -> tuple[pg.Surface | None, pg.Rect | None]:
        """
        Photograph the right-hand card column just before leaving Play, so the
        slide-out has something to move once the layout has given that space
        to the incoming sub-view

        :param now: pygame tick count in milliseconds since pygame init
        :returns: the snapshot and the rect it was taken from, both None when
            the column has no width in this window
        """
        panel = self._menu_layout.right_rail_full_rect
        if panel.width <= 0:
            return None, None
        temp = pg.Surface(self.app.window.get_size(), pg.SRCALPHA)
        self._draw_right_rail_panel(temp)
        self.card_stack.draw(temp, now)
        return temp.subsurface(panel).copy(), pg.Rect(panel)

    def _arm_rail_slide(self, previous: str, name: str, snapshot: pg.Surface | None,
                        origin: pg.Rect | None) -> None:
        """
        Decide whether a sub-view swap should slide the card column, which
        only happens on the two swaps that gain or lose it -- leaving Play and
        coming back to it. Every other swap leaves the column alone

        :param previous: sub-view being left
        :param name: sub-view being opened
        :param snapshot: photograph of the column taken before the swap,
            needed only for the slide out
        :param origin: rect the snapshot was taken from, where the slide out
            starts
        """
        if previous == "play" and name != "play":
            if snapshot is None:
                return
            self._rail_slide_mode = "out"
            self._rail_slide_snapshot = snapshot
            self._rail_slide_origin = origin
            self._rail_slide_tween = None
        elif previous != "play" and name == "play":
            self._rail_slide_mode = "in"
            self._rail_slide_snapshot = None
            self._rail_slide_origin = None
            self._rail_slide_tween = None

    def _end_rail_slide(self) -> None:
        """
        Finish the card column's slide and drop the snapshot it was moving,
        whether it ran to the end or was cut short by a resize or a screen
        change
        """
        self._rail_slide_mode = "none"
        self._rail_slide_tween = None
        self._rail_slide_snapshot = None
        self._rail_slide_origin = None

    def _ensure_scratch(self, attr: str) -> pg.Surface:
        """
        Hand back a window-sized transparent surface for an animation to draw
        on, reusing the one already there unless the window has changed size.
        Keeping them saves allocating a full-window surface every frame a
        transition runs

        :param attr: name of the attribute this surface is cached on, which
            is what keeps the two animations from sharing one surface
        :returns: a transparent surface the size of the current window
        """
        size = self.app.window.get_size()
        current = getattr(self, attr)
        if current is None or current.get_size() != size:
            current = pg.Surface(size, pg.SRCALPHA)
            setattr(self, attr, current)
        return current

    def _draw_right_rail_panel(self, window: pg.Surface) -> None:
        """
        Fill the backing panel the right-hand cards sit on, with a divider
        down its left edge. Drawn under the cards so the backdrop skirmish
        does not show through them

        :param window: surface to draw on, the window or a scratch surface
        """
        panel = self._menu_layout.right_rail_full_rect
        if panel.width <= 0:
            return
        pg.draw.rect(window, pg.Color(Colors.surface), panel)
        pg.draw.line(window, pg.Color(Colors.border), (panel.left, panel.top),
                     (panel.left, panel.bottom - 1))

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Route a left click through the menu's layers: a rail row switches
        sub-view, the rail footer opens its links, the cards answer next on
        Play, and anything left over goes to the showing sub-view

        :param pos: click position in window pixels
        :returns: True when some part of the menu took the click
        """
        row = self.rail.hit_test(pos)
        if row is not None:
            self.app.input_router.suppress_click_sound()
            if row != self._active_view:
                self.app.sound_manager.play_rail_click()
            self.goto_view(row)
            return True
        if self.rail.handle_footer_click(pos):
            return True
        if self._active_view == "play" and self.card_stack.handle_click(pos):
            return True
        return self.views[self._active_view].handle_click(pos)

    def handle_key(self, event: pg.event.Event) -> bool:
        """
        Hand a key press to the showing sub-view, which is where typing into
        the nickname and server fields ends up. Esc and F11 never arrive here

        :param event: pygame KEYDOWN event, key code and unicode both readable
        :returns: True when the sub-view took the key
        """
        return self.views[self._active_view].handle_key(event)

    def handle_press(self, pos: tuple[int, int]) -> bool:
        """
        Hand a left-button press to the showing sub-view, where it begins a
        drag on a control such as the time picker's drum

        :param pos: press position in window pixels
        :returns: True when the sub-view took the press
        """
        return self.views[self._active_view].handle_press(pos)

    def handle_motion(self, pos: tuple[int, int]) -> bool:
        """
        Hand cursor movement to the showing sub-view, which drives both hover
        highlighting and any drag it started

        :param pos: cursor position in window pixels
        :returns: True when the sub-view took the motion
        """
        return self.views[self._active_view].handle_motion(pos)

    def handle_release(self, pos: tuple[int, int]) -> bool:
        """
        Hand a left-button release to the showing sub-view, ending whatever
        drag it had running

        :param pos: release position in window pixels
        :returns: True when the sub-view took the release
        """
        return self.views[self._active_view].handle_release(pos)

    def active_scrollable(self) -> Any:
        """
        Name what the wheel should move on the menu right now. Off Play the
        sub-view decides; on Play an open picker wins, then an expanded news
        item, then the card stack itself, so the wheel always lands on the
        innermost thing that actually has somewhere to scroll

        :returns: the scrollable widget, or None when nothing here scrolls
        """
        if self._active_view != "play":
            return self.views[self._active_view].active_scrollable()
        picker = self.views["play"].active_scrollable()
        if picker is not None:
            return picker
        news_box = self.card_stack.news_box
        if news_box.is_visible() and news_box.scroll.scrollable():
            return news_box
        if self.card_stack.scroll.scrollable():
            return self.card_stack
        return None

    def scrollables(self) -> list[Any]:
        """
        List every scrollable the menu owns, across all of its sub-views and
        not just the showing one, so the shell can cancel all scrolling at
        once when the window is resized

        :returns: the scrollable widgets this screen owns
        """
        result = [self.card_stack, self.card_stack.news_box]
        for view in self.views.values():
            result.extend(view.scrollables())
        return result

    def escape(self) -> bool:
        """
        Step back one level. A sub-view with a popover open closes that first,
        any other sub-view returns to Play, and only from Play itself does Esc
        raise the quit confirmation -- the single place in the whole app where
        the player can close the window

        :returns: True always, since the menu deals with Esc at every level
        """
        if self.views[self._active_view].escape():
            return True
        if self._active_view != "play":
            self.goto_view("play")
            return True
        self.app.confirm_modal.show(
            "Leaving so soon?", on_yes=self._quit_app,
            yes_label="See ya!", no_label="Cancel")
        return True

    def goto_view(self, name: str) -> None:
        """
        Swap the menu to another sub-view, the single path every rail row and
        shortcut goes through. The old view is exited, the new one entered and
        laid out, and both animations -- the rise and the card column's slide
        -- are armed from here. Asking for the sub-view already showing does
        nothing

        :param name: registry name of the sub-view to open
        """
        if name == self._active_view:
            return
        previous = self._active_view
        snapshot, origin = None, None
        if previous == "play" and name != "play":
            snapshot, origin = self._capture_rail_column(pg.time.get_ticks())
        self.views[previous].exit()
        log.info("menu view %s -> %s", previous, name)
        self._active_view = name
        self.views[name].enter()
        self.rail.set_active(name, pg.time.get_ticks())
        if name == "play":
            self.card_stack.refresh()
        self.app._compute_layout()
        self._begin_transition("view", VIEW_RISE_MS)
        self._arm_rail_slide(previous, name, snapshot, origin)

    def goto_history(self) -> None:
        """
        Open the History sub-view, the shortcut behind the recent-games card's
        view-all link
        """
        self.goto_view("history")

    def _quit_app(self) -> None:
        """
        Actually close the game, once the player has confirmed they meant to.
        This is the only place in the app that stops the frame loop by choice
        """
        self.app.running = False

    def modals(self) -> list[ModalSpec]:
        """
        The menu's own modal, the card for pasting a FEN to start from. The
        shell merges it behind its global ones and uses that merged order for
        Esc, for clicks and for drawing

        :returns: this screen's modal specs, topmost first
        """
        return [ModalSpec(self.fen_input_modal)]

    def on_app_exit(self) -> None:
        """
        Flush the settings on the way out, so a value still being typed in
        Options is saved even when the player quits straight from that screen
        """
        self.app.settings.commit_options_exit()
