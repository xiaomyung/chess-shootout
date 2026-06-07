from chessshootout.frontend.skillcheck.wheel_view import WheelController, WHEEL_TIME_LIMIT_MS
from chessshootout.skillcheck.types import SkillCheckKind
from chessshootout.skillcheck.wheel import WheelChallenge


def build_controller(kind, *, seed, cell_rect, now_ms, deadline_ms):
    if kind == SkillCheckKind.WHEEL:
        return WheelController(
            WheelChallenge.from_seed(seed), cell_rect, now_ms,
            min(deadline_ms, WHEEL_TIME_LIMIT_MS))
    return None
