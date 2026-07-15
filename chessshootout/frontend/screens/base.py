import pathlib
from dataclasses import dataclass, field


PLAIN_PAYLOAD_TYPES = (str, int, float, bool, type(None), pathlib.Path)


@dataclass
class Nav:
    name: str
    payload: dict = field(default_factory=dict)


def assert_plain_payload(payload):
    _assert_plain(payload, "payload")


def _assert_plain(value, path):
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

    name = ""
    uses_battle_backdrop = False

    def __init__(self, app):
        self.app = app

    def enter(self, **payload):
        pass

    def exit(self):
        for spec in self.modals():
            spec.modal.hide()

    def update(self, now):
        return None

    def draw(self):
        pass

    def relayout(self, size):
        pass

    def on_resize(self):
        pass

    def handle_click(self, pos):
        return False

    def handle_key(self, event):
        return False

    def handle_press(self, pos):
        return False

    def handle_motion(self, pos):
        return False

    def handle_release(self, pos):
        return False

    def handle_right_press(self, pos):
        return False

    def handle_right_release(self, pos):
        return False

    def swallows_input(self):
        return False

    def forward_swallowed_event(self, event):
        pass

    def active_scrollable(self):
        return None

    def escape(self):
        return False

    def modals(self):
        return []

    def scrollables(self):
        return []

    def dirty_rects(self):
        return None

    def caption(self):
        return ""

    def debug_state(self):
        return {}

    def on_app_exit(self):
        pass
