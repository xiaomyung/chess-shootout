"""Seeded float derivation. seeded_floats chains sha256 blocks so callers can
draw more than four words: block 0 is sha256 of the raw payload (bit-identical
to the pre-chaining single-digest version for n<=4), block k>=1 is sha256 of
f"{payload}#{k}". The single-block regime used to silently return 0.0 for any
index >= 4 because int.from_bytes(b"") == 0; the wheel/aim/placement geometry
literals pinned below prove the low words did not move when chaining landed.
"""

from chessshootout.skillcheck.rng import seeded_floats

PAYLOADS = ["wheel:abc", "aim:xyz", "place:seed1", "room-abc:0", "seed", ""]


def test_low_words_are_bit_identical_to_single_digest():
    # These literals were captured from the pre-chaining implementation.
    assert seeded_floats("wheel:abc", 2) == (
        0.43691674630224536, 0.9062383360293562)
    assert seeded_floats("aim:xyz", 3) == (
        0.9116342352817408, 0.7551008647351231, 0.4254983937140359)
    assert seeded_floats("place:seed1", 2) == (
        0.24133711176389191, 0.3402871637071208)
    assert seeded_floats("room-abc:0", 4) == (
        0.8921599225429983, 0.5401460135284949,
        0.6944921849759444, 0.49966147332704475)


def test_shorter_n_is_a_prefix_of_longer_n():
    for payload in PAYLOADS:
        long = seeded_floats(payload, 16)
        for n in range(17):
            assert seeded_floats(payload, n) == long[:n]


def test_high_words_are_nonzero_unit_floats():
    for payload in PAYLOADS:
        values = seeded_floats(payload, 16)
        assert len(values) == 16
        for value in values:
            assert 0.0 <= value < 1.0
            assert value != 0.0


def test_all_sixteen_words_are_distinct():
    for payload in PAYLOADS:
        values = seeded_floats(payload, 16)
        assert len(set(values)) == 16


def test_is_deterministic_for_payload_and_n():
    for payload in PAYLOADS:
        for n in (1, 4, 5, 7, 16):
            results = {seeded_floats(payload, n) for _ in range(3)}
            assert len(results) == 1


def test_distinct_payloads_diverge():
    for n in (1, 5, 16):
        outputs = [seeded_floats(payload, n) for payload in PAYLOADS]
        assert len(set(outputs)) == len(PAYLOADS)


def test_zero_words_is_empty_tuple():
    assert seeded_floats("anything", 0) == ()
