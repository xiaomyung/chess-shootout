"""The Combo directional string (a fixed sequence of up/down/left/right prompts,
hit each in order before the deadline). The whole sequence is derived
deterministically from a seed so server and client agree on the prompts, while
the length grows with the captured piece's value and shrinks to fit whatever
per-move deadline the time control allows. Difficulty is exactly the count:
independent per-input odds compound as prob**count.
"""

from chessshootout.skillcheck import combo, wheel
from chessshootout.skillcheck.combo import ComboChallenge
from tests.helpers import read_source_without_docstrings


def test_from_seed_is_deterministic():
    a = ComboChallenge.from_seed("room-1:5")
    b = ComboChallenge.from_seed("room-1:5")
    assert a == b
    assert a.prompts == b.prompts


def test_distinct_seeds_vary_prompt_tuples():
    tuples = {ComboChallenge.from_seed(f"s:{i}").prompts for i in range(20)}
    assert len(tuples) >= 10


def test_value_diff_is_accepted_but_inert():
    # value_diff exists for signature parity with the wheel/aim engines; it must
    # not perturb the challenge (no speculative difficulty branch hides behind it).
    base = ComboChallenge.from_seed("vd", value_diff=0)
    assert ComboChallenge.from_seed("vd", value_diff=8) == base
    assert ComboChallenge.from_seed("vd", value_diff=-8) == base


def test_prompts_are_all_known_directions():
    for i in range(50):
        ch = ComboChallenge.from_seed(f"dir:{i}")
        for direction in ch.prompts:
            assert direction in combo.COMBO_DIRECTIONS


def test_every_direction_is_reachable_across_seeds():
    seen = set()
    for i in range(50):
        seen.update(ComboChallenge.from_seed(f"reach:{i}").prompts)
    assert seen == set(combo.COMBO_DIRECTIONS)
    assert len(seen) == 4


def test_prompt_count_scales_with_captured_value_at_full_deadline():
    # 5 + captured_value // 3, clamped to [3, 7], at the full 5000 ms deadline.
    cases = {0: 5, 1: 5, 3: 6, 5: 6, 9: 7}
    for captured, count in cases.items():
        ch = ComboChallenge.from_seed("v", deadline_ms=5000.0, captured_value=captured)
        assert ch.prompt_count == count


def test_short_deadline_floors_to_min_prompts_regardless_of_captured_value():
    # (2000 - 300) / 650 = 2.6 -> 2, lifted back to the COMBO_MIN_PROMPTS floor of 3;
    # the value-driven ceiling can never raise it above what the deadline allows.
    for captured in (0, 1, 3, 9, 100):
        ch = ComboChallenge.from_seed("v", deadline_ms=2000.0, captured_value=captured)
        assert ch.prompt_count == combo.COMBO_MIN_PROMPTS == 3


def test_deadline_3000_yields_four_prompts():
    # (3000 - 300) / 650 = 4.15 -> int() = 4, below the value ceiling of 5.
    ch = ComboChallenge.from_seed("v", deadline_ms=3000.0, captured_value=0)
    assert ch.prompt_count == 4


def test_min_prompts_floor_holds_at_tiny_deadline():
    # (1000 - 300) / 650 = 1.08 -> 1; the floor still guarantees COMBO_MIN_PROMPTS.
    ch = ComboChallenge.from_seed("v", deadline_ms=1000.0, captured_value=9)
    assert ch.prompt_count == combo.COMBO_MIN_PROMPTS


def test_short_deadline_prompts_are_a_prefix_of_the_long_deadline():
    # The full 7-word draw is sliced to n, so a shorter deadline is always a
    # prefix of a longer one for the same seed (stable under deadline changes).
    for i in range(20):
        seed = f"prefix:{i}"
        short = ComboChallenge.from_seed(seed, deadline_ms=2000.0).prompts
        long = ComboChallenge.from_seed(seed, deadline_ms=5000.0).prompts
        assert len(short) < len(long)
        assert long[:len(short)] == short


def test_expected_returns_prompt_or_none_out_of_range():
    ch = ComboChallenge.from_seed("v", deadline_ms=5000.0, captured_value=0)
    assert ch.expected(0) == ch.prompts[0]
    assert ch.expected(ch.prompt_count - 1) == ch.prompts[-1]
    assert ch.expected(-1) is None
    assert ch.expected(ch.prompt_count) is None
    assert ch.expected(999) is None


def test_press_correct_is_none_safe_and_direction_sensitive():
    ch = ComboChallenge(prompts=("up", "left"), deadline_ms=5000.0)
    assert ch.press_correct(0, "up") is True
    assert ch.press_correct(1, "left") is True
    assert ch.press_correct(0, "down") is False
    assert ch.press_correct(0, None) is False
    assert ch.press_correct(2, "up") is False
    assert ch.press_correct(-1, "up") is False


def test_is_complete_boundaries():
    ch = ComboChallenge.from_seed("v", deadline_ms=5000.0, captured_value=0)
    n = ch.prompt_count
    assert ch.is_complete(0) is False
    assert ch.is_complete(n - 1) is False
    assert ch.is_complete(n) is True
    assert ch.is_complete(n + 1) is True


def test_wrongs_exhausted_boundaries():
    ch = ComboChallenge.from_seed("v", deadline_ms=5000.0, captured_value=0)
    assert combo.COMBO_MAX_WRONGS == 3
    assert ch.wrongs_exhausted(0) is False
    assert ch.wrongs_exhausted(2) is False
    assert ch.wrongs_exhausted(3) is True
    assert ch.wrongs_exhausted(4) is True


def test_deadline_ms_is_single_sourced_from_wheel():
    # No 5000 literal may live in combo.py; the deadline is imported, not restated.
    assert "5000" not in read_source_without_docstrings(combo.__file__)
    assert combo.SKILLCHECK_DEADLINE_MS is wheel.SKILLCHECK_DEADLINE_MS


def test_the_prompt_count_is_the_only_lever_on_the_compounding_difficulty():
    # Whole-combo pass = per_input ** prompt_count when the inputs are independent,
    # so the count is the ONLY thing the challenge contributes to the difficulty
    # curve -- and the count is all this can honestly pin. (The old second
    # assertion re-derived per_input ** count and compared it to a hardcoded
    # power of 0.95: arithmetic over a constant, which cannot fail once the count
    # above is asserted.) No easing pass-band is asserted anywhere.
    for deadline, captured, count in [(5000.0, 0, 5), (5000.0, 3, 6), (5000.0, 9, 7)]:
        ch = ComboChallenge.from_seed("compound", deadline_ms=deadline, captured_value=captured)
        assert ch.prompt_count == count
