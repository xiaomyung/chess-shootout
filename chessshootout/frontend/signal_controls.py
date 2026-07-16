def toggle_sound(app):
    sound_manager = app.sound_manager
    sound_manager.set_enabled(not sound_manager.enabled)


def set_signal_volume(app, value):
    app.sound_manager.set_master_volume(value)
    app.settings.defer_master_volume_write()
