from collections.abc import Callable

from chessshootout.paths import resource_path


_TABLE = None
_MAX_PLIES = 0


def _normalize(san: str) -> str:
    """
    Drop the check and mate markers from a move so dataset notation and
    engine-produced notation compare equal. Bb4 and Bb4+ are the same move as
    far as naming an opening goes

    :param san: one move in standard algebraic notation
    :returns: the same move without any trailing + or #
    """
    return san.rstrip("+#")


def _tokenize(pgn: str) -> list[str]:
    """
    Turn one dataset line's movetext into the plain move list the lookup table
    is keyed by, dropping move numbers and normalising each move

    :param pgn: movetext of a single opening line, e.g. 1. e4 e5 2. Nf3
    :returns: the moves in play order, check and mate markers removed
    """
    return [_normalize(token) for token in pgn.split() if not token.endswith(".")]


def preload() -> None:
    """
    Load the ECO opening dataset into the process-wide lookup table so opening
    names can be shown without touching disk again. The game and review screens
    both call it on entry, and every call after the first returns immediately
    """
    global _TABLE, _MAX_PLIES
    if _TABLE is not None:
        return
    table = {}
    max_plies = 0
    with open(resource_path("assets", "openings.tsv"), encoding="utf-8") as source:
        next(source, None)
        for line in source:
            parts = line.rstrip("\r\n").split("\t")
            if len(parts) != 3:
                continue
            eco, name, pgn = parts
            sans = _tokenize(pgn)
            if not sans:
                continue
            table[tuple(sans)] = (eco, name)
            max_plies = max(max_plies, len(sans))
    _TABLE = table
    _MAX_PLIES = max_plies


def lookup(sans: list[str]) -> tuple[str, str] | None:
    """
    Name the opening a game is in by matching the longest known prefix of its
    moves, which is what freezes the label on the deepest known line once play
    leaves the book. Nothing is ever found before preload() has run

    :param sans: the game's moves in play order, check markers optional
    :returns: the ECO code and opening name, or None when no prefix is known
    """
    if not _TABLE or not sans:
        return None
    norm = [_normalize(san) for san in sans]
    for length in range(min(len(norm), _MAX_PLIES), 0, -1):
        hit = _TABLE.get(tuple(norm[:length]))
        if hit is not None:
            return hit
    return None


class DebutTracker:
    """
    Remembers the opening line for the position a screen is currently showing,
    so the move panel can label it without re-running the lookup every frame.
    The game and review screens each own one
    """

    def __init__(self, sans_provider: Callable[[], list[str]]) -> None:
        """
        Bind the tracker to the moves it should name. They are read lazily on
        each miss, so the tracker follows whatever the screen is showing --
        the live game or the ply the player is browsing

        :param sans_provider: callable giving the moves in play order for the
            position on screen
        """
        self._sans_provider = sans_provider
        self._memo = None

    def reset(self) -> None:
        """
        Forget the remembered line so the next request looks the opening up
        again. Called when a new game starts or another PGN is loaded
        """
        self._memo = None

    def line(self, key: tuple[int, int | None]) -> tuple[str, str] | None:
        """
        Give the opening for the position on screen, doing the lookup again
        only when the key has changed. Callers pass whatever identifies that
        position, in practice the ply count paired with the reviewed ply

        :param key: identity of the position on screen; a new value forces a
            fresh lookup
        :returns: the ECO code and opening name, or None when out of book
        """
        if self._memo is None or self._memo[0] != key:
            self._memo = (key, lookup(self._sans_provider()))
        return self._memo[1]
