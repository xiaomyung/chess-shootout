from chessshootout.domain.match import BOT, ONLINE, SINGLE_SCREEN


class Variant:
    LOCAL = "local"
    BOT = "bot"
    ONLINE = "online"


MATCH_MODE_BY_VARIANT = {
    Variant.LOCAL: SINGLE_SCREEN,
    Variant.BOT: BOT,
    Variant.ONLINE: ONLINE,
}
