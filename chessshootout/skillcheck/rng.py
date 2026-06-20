import hashlib


def ply_roll(seed, key):
    payload = f"{seed}:{key}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big") / 2.0 ** 64


def move_roll_key(ply_index, from_sq, to_sq):
    return f"{ply_index}:{from_sq.row}{from_sq.col}:{to_sq.row}{to_sq.col}"
