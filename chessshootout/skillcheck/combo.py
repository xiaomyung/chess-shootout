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
    """
    One Combo challenge: the fixed run of direction prompts a player has to
    hit in order before the deadline. Derived purely from a seed, so both
    sides show the same arrows and the judge can score every press
    """

    prompts: tuple
    deadline_ms: float

    @property
    def prompt_count(self) -> int:
        """
        Give how many prompts this combo has, which is the whole of its
        difficulty -- the odds of getting them all compound with the count

        :returns: number of prompts that have to be hit
        """
        return len(self.prompts)

    @classmethod
    def from_seed(cls, seed: str, value_diff: int = 0,
                  deadline_ms: float = SKILLCHECK_DEADLINE_MS,
                  captured_value: int = 0) -> "ComboChallenge":
        """
        Build one combo from its seed. The run grows with the piece being
        taken and is then cut back to what the deadline can honestly fit, so a
        fast time control shortens the combo rather than making it impossible

        :param seed: per-check seed, fresh random text that carries no trace
            of the room's selection secret
        :param value_diff: capturer value minus captured value; accepted for
            parity with the wheel and aim engines and deliberately inert here
        :param deadline_ms: milliseconds the combo may run for, normally
            SKILLCHECK_DEADLINE_MS or the smaller share a fast time control
            allows
        :param captured_value: material value of the piece being taken, which
            lengthens the run
        :returns: the challenge to render and adjudicate against
        """
        n_value = min(COMBO_PROMPT_COUNT_BASE + captured_value // COMBO_PROMPT_VALUE_DIVISOR,
                      COMBO_PROMPT_COUNT_MAX)
        n_deadline = int((deadline_ms - COMBO_INTRO_MS) / COMBO_MS_PER_PROMPT)
        n = max(COMBO_MIN_PROMPTS, min(n_value, n_deadline))
        floats = seeded_floats(f"combo:{seed}", COMBO_PROMPT_COUNT_MAX)[:n]
        span = len(COMBO_DIRECTIONS)
        prompts = tuple(COMBO_DIRECTIONS[int(f * span) % span] for f in floats)
        return cls(prompts=prompts, deadline_ms=deadline_ms)

    def expected(self, index: int) -> str | None:
        """
        Give the direction the player owes at this point in the run, which the
        view draws as the live arrow and the judge compares a press against

        :param index: how many prompts have already been hit
        :returns: the direction owed, or None once the run is finished or the
            index falls outside it
        """
        if index < 0 or index >= len(self.prompts):
            return None
        return self.prompts[index]

    def press_correct(self, index: int, direction: str | None) -> bool:
        """
        Judge one directional press: it counts only when it matches the prompt
        the player currently owes. This is the verdict for a combo input both
        locally and on the server

        :param index: how many prompts have already been hit
        :param direction: direction pressed, or None when the input did not
            resolve to one
        :returns: True when the press advances the combo
        """
        return direction is not None and direction == self.expected(index)

    def is_complete(self, progress: int) -> bool:
        """
        Tell whether the whole run has been hit, which is what wins the check
        and lands the move behind it

        :param progress: prompts hit so far
        :returns: True when nothing is left to press
        """
        return progress >= self.prompt_count

    def wrongs_exhausted(self, miss_count: int) -> bool:
        """
        Tell whether the player has spent all their wrong presses. Combo
        forgives a couple of slips before the check is lost, so one fumbled
        arrow does not immediately cost the capture

        :param miss_count: wrong presses made so far
        :returns: True when the wrong presses already made lose the check
        """
        return miss_count >= COMBO_MAX_WRONGS
