from chessshootout.paths import resource_path


_TABLE = None
_MAX_PLIES = 0


def _normalize(san):
    return san.rstrip("+#")


def _tokenize(pgn):
    return [_normalize(token) for token in pgn.split() if not token.endswith(".")]


def preload():
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


def lookup(sans):
    if not _TABLE or not sans:
        return None
    norm = [_normalize(san) for san in sans]
    for length in range(min(len(norm), _MAX_PLIES), 0, -1):
        hit = _TABLE.get(tuple(norm[:length]))
        if hit is not None:
            return hit
    return None


class DebutTracker:
    def __init__(self, sans_provider):
        self._sans_provider = sans_provider
        self._memo = None

    def reset(self):
        self._memo = None

    def line(self, key):
        if self._memo is None or self._memo[0] != key:
            self._memo = (key, lookup(self._sans_provider()))
        return self._memo[1]
