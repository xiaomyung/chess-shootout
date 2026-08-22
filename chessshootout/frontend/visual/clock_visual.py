LOW_TIME_FRACTION = 0.10


def format_clock(seconds: float | None) -> str:
    """
    Turn a player's remaining time into the text their clock shows. Under
    thirty seconds it switches to tenths, which is the cue that the flag is
    close; an untimed game has no number at all and shows the infinity mark

    :param seconds: time left on that clock, or None for an untimed game
    :returns: clock text such as 3:07, 0:09.4, or the infinity mark
    """
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


def format_countdown(seconds: float) -> str:
    """
    Turn a countdown into the text a waiting player reads -- the reconnect
    timer, the queue elapsed time, the abort and idle-resign windows. It never
    shows tenths and never goes below zero, so an expired window reads 0:00

    :param seconds: whole or fractional seconds left, negatives read as zero
    :returns: countdown text in minutes and seconds, such as 0:45
    """
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}"
