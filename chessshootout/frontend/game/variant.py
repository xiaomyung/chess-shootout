from chessshootout.domain.match import BOT, ONLINE, SINGLE_SCREEN


class Variant:
    """
    The three kinds of game the game screen can host. Plain string constants
    rather than an enum: the chosen one is stored on the screen, reported in
    the crash-log debug state, and compared against by every online-only branch
    """

    LOCAL = "local"
    BOT = "bot"
    ONLINE = "online"


MATCH_MODE_BY_VARIANT = {
    Variant.LOCAL: SINGLE_SCREEN,
    Variant.BOT: BOT,
    Variant.ONLINE: ONLINE,
}
