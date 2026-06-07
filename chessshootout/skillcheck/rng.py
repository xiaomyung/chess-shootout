import hashlib


def ply_roll(seed, ply_index):
    payload = f"{seed}:{ply_index}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big") / 2.0 ** 64
