from typing import Any


def toggle_sound(app: Any) -> None:
    """
    Turn the game's sound on or off, behind the speaker button on the rail.
    This is the shared implementation both the game and the review screen call,
    so the button behaves identically wherever it appears -- neither screen may
    keep a copy of it

    :param app: the running app shell, whose sound manager holds the setting
    """
    sound_manager = app.sound_manager
    sound_manager.set_enabled(not sound_manager.enabled)


def set_signal_volume(app: Any, value: float) -> None:
    """
    Set the volume everything plays at, behind the volume control on the rail,
    and remember it for the next launch. The saving is deferred, so holding the
    control down writes once at the end rather than at every step. Shared by
    the game and review screens, which must not reimplement it

    :param app: the running app shell, owning the sound manager and settings
    :param value: wanted level, 0.0 silent through 1.0 full
    """
    app.sound_manager.set_master_volume(value)
    app.settings.defer_master_volume_write()
