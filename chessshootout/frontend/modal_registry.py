from dataclasses import dataclass


@dataclass
class ModalSpec:
    obj: object
    esc_dismiss: bool = True
    on_dismiss: object = None

    def __post_init__(self):
        if self.on_dismiss is None:
            self.on_dismiss = self.obj.hide

    @property
    def scrollable(self):
        return hasattr(self.obj, "scroll")

    @property
    def handles_keys(self):
        return hasattr(self.obj, "handle_key")


def dismiss_topmost(specs):
    for spec in specs:
        if spec.esc_dismiss and spec.obj.is_visible():
            spec.on_dismiss()
            return True
    return False
