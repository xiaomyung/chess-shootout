import pathlib
from dataclasses import dataclass, field
from typing import Any

import pygame as pg

from chessshootout.frontend.modal_registry import ModalSpec


PLAIN_PAYLOAD_TYPES = (str, int, float, bool, type(None), pathlib.Path)


@dataclass
class Nav:
    """
    A request to change screens, produced by a screen instead of it switching
    the app itself. The shell runs the intent once the current frame's input
    dispatch is finished, which keeps a screen from vanishing mid-event
    """

    name: str
    payload: dict[str, Any] = field(default_factory=dict)


def assert_plain_payload(payload: dict[str, Any]) -> None:
    """
    Guard the screen boundary: what one screen hands another must be plain
    data, never a live object, so screens cannot end up sharing state behind
    the shell's back. The shell checks every navigation payload with this

    :param payload: keyword payload a Nav carries into the target screen
    """
    _assert_plain(payload, "payload")


def _assert_plain(value: Any, path: str) -> None:
    """
    Walk one payload value and reject anything that is not plain data,
    recursing through dicts, lists and tuples. Dict keys must be strings,
    since the payload is splatted into the target screen as keyword arguments

    :param value: payload fragment being inspected
    :param path: readable trail to this value, used in the rejection message
    """
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"{path} has non-str key {key!r} ({type(key).__name__})")
            _assert_plain(item, f"{path}[{key!r}]")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_plain(item, f"{path}[{index}]")
        return
    if isinstance(value, PLAIN_PAYLOAD_TYPES):
        return
    raise TypeError(f"{path} has non-plain value {value!r} ({type(value).__name__})")


class Screen:
    """
    The contract every full-window screen (menu, game, review) implements. The
    shell owns one long-lived instance of each, keeps exactly one of them
    active, and drives it only through the hooks below; every hook here is a
    harmless default so a screen overrides just what it uses
    """

    name = ""
    uses_battle_backdrop = False

    def __init__(self, app: Any) -> None:
        """
        Bind the screen to the app shell that hosts it. Screens are built once
        at startup and reused for the whole run, never rebuilt per navigation

        :param app: the Frontend shell, this screen's only route to shared
            services such as the window, sound, toasts and the coordinator
        """
        self.app = app

    def enter(self, **payload: Any) -> None:
        """
        Take over the window, called by the shell straight after the previous
        screen exited. Entry always starts from a clean baseline, so entering
        the same screen twice in a row (rematch, review reload) is well defined

        :param payload: plain-data payload carried by the navigation intent
        """
        pass

    def exit(self) -> None:
        """
        Hand back the window and cancel everything screen-local -- timers,
        drags, overlays, modals -- so nothing from this visit leaks into the
        next screen. Overrides must call this base version, which hides the
        modals the screen owns
        """
        for spec in self.modals():
            spec.modal.hide()

    def update(self, now: int) -> Nav | None:
        """
        Advance the screen's state by one frame before it is drawn; this is
        where clocks tick and animations step. Returning a navigation intent
        asks the shell to switch screens once the frame is dispatched

        :param now: pygame tick count in milliseconds since pygame init
        :returns: navigation intent to run after this frame, or None to stay
        """
        return None

    def draw(self) -> None:
        """
        Paint the screen onto the app window. Called every frame after update
        and before the shell draws banners, modals and toasts over the top
        """
        pass

    def relayout(self, size: tuple[int, int]) -> None:
        """
        Recompute every rect this screen owns for a new window size. The shell
        calls it at startup, on a window resize and on every screen switch,
        including for the screens that are not currently showing

        :param size: window width and height in pixels
        """
        pass

    def on_resize(self) -> None:
        """
        React to the window surface itself being replaced, which happens just
        before the relayout pass. It is the hook for state a brand new surface
        invalidates outright, such as an in-flight transition
        """
        pass

    def handle_click(self, pos: tuple[int, int]) -> bool | Nav:
        """
        Handle a left click that the window chrome and the modals did not
        already take. Returning a navigation intent moves to another screen
        instead of consuming the click in place

        :param pos: click position in window pixels
        :returns: True when the click was consumed, or a navigation intent
        """
        return False

    def handle_key(self, event: pg.event.Event) -> bool | Nav:
        """
        Handle a key press the shell did not claim; Esc and F11 never reach
        here. Returning a navigation intent lets a hotkey leave the screen

        :param event: pygame KEYDOWN event, key code and unicode both readable
        :returns: True when the key was consumed, or a navigation intent
        """
        return False

    def handle_press(self, pos: tuple[int, int]) -> bool:
        """
        Begin a left-button press below the window chrome, which is where
        picking a piece up starts. Only reaches the screen when no modal is
        blocking input

        :param pos: press position in window pixels
        :returns: True when the screen took the press
        """
        return False

    def handle_motion(self, pos: tuple[int, int]) -> bool:
        """
        Follow the cursor, both while a left drag is in flight and while
        merely hovering, which drives drag physics and hover highlighting

        :param pos: cursor position in window pixels
        :returns: True when the screen took the motion
        """
        return False

    def handle_release(self, pos: tuple[int, int]) -> bool:
        """
        Finish a left drag, the moment a dragged piece is dropped on a square

        :param pos: release position in window pixels
        :returns: True when the screen took the release
        """
        return False

    def handle_right_press(self, pos: tuple[int, int]) -> bool:
        """
        Start a right-button gesture, which on a board begins a highlight or
        an arrow annotation. Answering False lets the shell play the ordinary
        UI click sound instead

        :param pos: press position in window pixels
        :returns: True when the screen took the press
        """
        return False

    def handle_right_release(self, pos: tuple[int, int]) -> bool:
        """
        End a right-button gesture and commit whatever annotation it drew

        :param pos: release position in window pixels
        :returns: True when the screen took the release
        """
        return False

    def swallows_input(self) -> bool:
        """
        Say whether the screen is grabbing all raw input right now, as it does
        while a skill check is live. While this is true the shell stops normal
        routing and forwards events to forward_swallowed_event instead

        :returns: True while every event should be forwarded raw
        """
        return False

    def forward_swallowed_event(self, event: pg.event.Event) -> None:
        """
        Receive a raw event while swallows_input is true, so the screen's
        overlay can read keys and clicks that normal routing never sees

        :param event: pygame event, keyboard or mouse
        """
        pass

    def active_scrollable(self) -> Any:
        """
        Name the widget that should receive wheel and drag scrolling at this
        moment. A visible modal outranks the screen, so this is consulted only
        when no modal is on top

        :returns: the scrollable widget, or None when nothing here scrolls
        """
        return None

    def escape(self) -> bool | Nav:
        """
        Handle Esc as a context Back or Cancel; Esc never closes the window
        from here. Return a navigation intent to step back to another screen,
        or True to say the screen dealt with it in place

        :returns: True when handled here, False when not, or a nav intent
        """
        return False

    def modals(self) -> list[ModalSpec]:
        """
        List the modals this screen owns. The shell merges them after the
        global ones and uses the merged order for Esc dismissal, click routing
        and draw order, so nothing else hand-orders modals

        :returns: this screen's modal specs, topmost first, empty when none
        """
        return []

    def scrollables(self) -> list[Any]:
        """
        List every scrollable widget on this screen, active or not, so the
        shell can cancel all scrolling at once when the window is resized

        :returns: the scrollable widgets this screen owns
        """
        return []

    def dirty_rects(self) -> list[pg.Rect] | None:
        """
        Report which regions changed this frame so the shell can present just
        those instead of the whole window. Returning None means redraw everything, which
        is the safe answer whenever the screen is not sure

        :returns: rects to present, or None to force a full present
        """
        return None

    def caption(self) -> str:
        """
        Give the window title text for this screen, applied on every screen
        switch. An empty string keeps the default app title

        :returns: caption text, or empty to keep the default title
        """
        return ""

    def debug_state(self) -> dict[str, Any]:
        """
        Summarise the screen for the crash log, which snapshots it when an
        unhandled exception reaches the entry point. Keep the values small,
        plain and free of anything secret

        :returns: readable key/value summary of this screen's state
        """
        return {}

    def on_app_exit(self) -> None:
        """
        Flush anything that has to survive quitting, such as an unsaved game
        or pending settings. Every screen gets this call at shutdown, active
        or not, and before the online connection is torn down
        """
        pass
