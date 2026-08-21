from dataclasses import dataclass


@dataclass
class ModalSpec:
    """
    One modal registered with the app, pairing the modal widget with how Esc
    should treat it. The shell keeps a global list of these and each screen
    adds its own; the merged order is what decides Esc, clicks and drawing
    """

    modal: object
    esc_dismiss: bool = True
    on_dismiss: object = None

    def __post_init__(self) -> None:
        """
        Default the dismiss action to simply hiding the modal, so only the
        modals that need extra cleanup on the way out -- cancelling
        matchmaking, dropping back to the play view -- have to supply one
        """
        if self.on_dismiss is None:
            self.on_dismiss = self.modal.hide

    @property
    def scrollable(self) -> bool:
        """
        Say whether this modal scrolls its own content, which is how the app
        decides that a visible modal, not the screen behind it, owns the wheel

        :returns: True when the modal exposes a scroll helper
        """
        return hasattr(self.modal, "scroll")

    @property
    def handles_keys(self) -> bool:
        """
        Say whether this modal wants key presses. A visible modal always eats
        the key either way; only one that answers True is given a chance to
        act on it

        :returns: True when the modal accepts key events
        """
        return hasattr(self.modal, "handle_key")


def dismiss_topmost(specs: list[ModalSpec]) -> bool:
    """
    Close the frontmost visible modal that Esc is allowed to close, which is
    the first step of the app's Esc handling. Modals flagged as not
    Esc-dismissable (match found, reconnecting) are stepped over rather than
    stopping the search

    :param specs: modal specs in topmost-first order, global ones first
    :returns: True when a modal was dismissed
    """
    for spec in specs:
        if spec.esc_dismiss and spec.modal.is_visible():
            spec.on_dismiss()
            return True
    return False
