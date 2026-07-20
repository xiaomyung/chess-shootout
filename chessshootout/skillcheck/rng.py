import hashlib


def seeded_floats(payload, n):
    buffer = b""
    block = 0
    while len(buffer) < n * 8:
        text = payload if block == 0 else f"{payload}#{block}"
        buffer += hashlib.sha256(text.encode("utf-8")).digest()
        block += 1
    return tuple(int.from_bytes(buffer[i * 8:i * 8 + 8], "big") / 2.0 ** 64
                 for i in range(n))


def ply_roll(seed, key):
    return seeded_floats(f"{seed}:{key}", 1)[0]


def move_roll_key(ply_index, from_sq, to_sq):
    return f"{ply_index}:{from_sq.row}{from_sq.col}:{to_sq.row}{to_sq.col}"
