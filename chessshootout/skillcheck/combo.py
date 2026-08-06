from dataclasses import dataclass

from chessshootout.skillcheck.rng import seeded_floats
from chessshootout.skillcheck.wheel import SKILLCHECK_DEADLINE_MS

COMBO_DIRECTIONS = ("up", "down", "left", "right")
COMBO_PROMPT_COUNT_BASE = 5
COMBO_PROMPT_COUNT_MAX = 7
COMBO_PROMPT_VALUE_DIVISOR = 3
COMBO_MIN_PROMPTS = 3
COMBO_INTRO_MS = 300.0
COMBO_MS_PER_PROMPT = 650.0
COMBO_WRONG_LOCKOUT_MS = 200.0
COMBO_MAX_WRONGS = 3
COMBO_MIN_INTER_PRESS_MS = 80.0
COMBO_SERVER_MIN_INTER_PRESS_MS = 50.0


@dataclass(frozen=True)
class ComboChallenge:
    prompts: tuple
    deadline_ms: float

    @property
    def prompt_count(self):
        return len(self.prompts)

    @classmethod
    def from_seed(cls, seed, value_diff=0, deadline_ms=SKILLCHECK_DEADLINE_MS, captured_value=0):
        n_value = min(COMBO_PROMPT_COUNT_BASE + captured_value // COMBO_PROMPT_VALUE_DIVISOR,
                      COMBO_PROMPT_COUNT_MAX)
        n_deadline = int((deadline_ms - COMBO_INTRO_MS) / COMBO_MS_PER_PROMPT)
        n = max(COMBO_MIN_PROMPTS, min(n_value, n_deadline))
        floats = seeded_floats(f"combo:{seed}", COMBO_PROMPT_COUNT_MAX)[:n]
        span = len(COMBO_DIRECTIONS)
        prompts = tuple(COMBO_DIRECTIONS[int(f * span) % span] for f in floats)
        return cls(prompts=prompts, deadline_ms=deadline_ms)

    def expected(self, index):
        if index < 0 or index >= len(self.prompts):
            return None
        return self.prompts[index]

    def press_correct(self, index, direction):
        return direction is not None and direction == self.expected(index)

    def is_complete(self, progress):
        return progress >= self.prompt_count

    def wrongs_exhausted(self, miss_count):
        return miss_count >= COMBO_MAX_WRONGS
