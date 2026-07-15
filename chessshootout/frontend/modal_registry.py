from dataclasses import dataclass


@dataclass
class ModalSpec:
    modal: object
    esc_dismiss: bool = True
    on_dismiss: object = None

    def __post_init__(self):
        if self.on_dismiss is None:
            self.on_dismiss = self.modal.hide

    @property
    def scrollable(self):
        return hasattr(self.modal, "scroll")

    @property
    def handles_keys(self):
        return hasattr(self.modal, "handle_key")


def dismiss_topmost(specs):
    for spec in specs:
        if spec.esc_dismiss and spec.modal.is_visible():
            spec.on_dismiss()
            return True
    return False
