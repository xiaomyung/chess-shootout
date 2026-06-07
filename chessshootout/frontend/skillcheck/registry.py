from chessshootout.frontend.skillcheck.wheel_view import WheelController
from chessshootout.skillcheck.types import SkillCheckKind
from chessshootout.skillcheck.wheel import WheelChallenge


def build_controller(kind, *, seed, cell_rect, now_ms, deadline_ms):
    if kind == SkillCheckKind.WHEEL:
        return WheelController(
            WheelChallenge.from_seed(seed), cell_rect, now_ms, deadline_ms)
    return None
