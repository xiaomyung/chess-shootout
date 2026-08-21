import hashlib

from chessshootout.backend.utils import Square


def seeded_floats(payload: str, n: int) -> tuple[float, ...]:
    """
    Turn a seed string into a reproducible run of floats in [0, 1), the only
    randomness any skill check uses. Server and client end up with identical
    challenges because both hash the same payload instead of drawing from a
    local generator

    :param payload: seed text, namespaced by its caller (wheel:, mole:,
        place:, ...) so two uses of one seed never share numbers
    :param n: how many floats are wanted; past four, further sha256 blocks are
        chained rather than reusing exhausted digest bytes
    :returns: n floats in [0, 1), the same on every machine and every run
    """
    buffer = b""
    block = 0
    while len(buffer) < n * 8:
        text = payload if block == 0 else f"{payload}#{block}"
        buffer += hashlib.sha256(text.encode("utf-8")).digest()
        block += 1
    return tuple(int.from_bytes(buffer[i * 8:i * 8 + 8], "big") / 2.0 ** 64
                 for i in range(n))


def ply_roll(seed: str, key: str) -> float:
    """
    Draw the single roll that decides whether one specific move fires a skill
    check and which kind. The same seed and key always give the same roll,
    which is what lets the selector stay hidden and still be reproducible

    :param seed: the game's selection seed -- online this is the room secret
        the server never puts on the wire
    :param key: per-move key from move_roll_key, keeping every candidate move
        on its own independent draw
    :returns: one float in [0, 1) to compare against the weights table
    """
    return seeded_floats(f"{seed}:{key}", 1)[0]


def move_roll_key(ply_index: int, from_sq: Square, to_sq: Square) -> str:
    """
    Build the key one move's skill-check roll is drawn against, so every
    (ply, from, to) candidate gets an independent draw. Retrying the same move
    at the same point in the game therefore cannot reroll it

    :param ply_index: plies already played, so the same move later in the game
        draws afresh
    :param from_sq: square the piece would leave
    :param to_sq: square it would land on
    :returns: stable key text to hand to ply_roll
    """
    return f"{ply_index}:{from_sq.row}{from_sq.col}:{to_sq.row}{to_sq.col}"
