LOW_TIME_FRACTION = 0.10


def format_clock(seconds):
    if seconds is None:
        return "∞"
    if seconds < 0:
        seconds = 0
    if seconds < 30:
        total_tenths = int(seconds * 10)
        minutes, rem = divmod(total_tenths, 600)
        secs, tenths = divmod(rem, 10)
        return f"{minutes}:{secs:02d}.{tenths}"
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}"


def format_countdown(seconds):
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}"
