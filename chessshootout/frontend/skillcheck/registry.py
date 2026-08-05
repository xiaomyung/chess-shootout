from dataclasses import dataclass

from chessshootout.frontend.skillcheck.aim_view import AimController, AIM_TIME_LIMIT_MS
from chessshootout.frontend.skillcheck.combo_view import ComboController
from chessshootout.frontend.skillcheck.mole_view import MoleController
from chessshootout.frontend.skillcheck.wheel_view import WheelController, WHEEL_TIME_LIMIT_MS
from chessshootout.skillcheck.aim import AimChallenge
from chessshootout.skillcheck.combo import ComboChallenge
from chessshootout.skillcheck.mole import MoleChallenge
from chessshootout.skillcheck.types import SkillCheckKind
from chessshootout.skillcheck.wheel import WheelChallenge, WHEEL_PERIOD_MS


@dataclass(frozen=True, kw_only=True)
class CheckSpec:
    seed: str
    cell_rect: object
    now_ms: int
    deadline_ms: float
    period_ms: float = WHEEL_PERIOD_MS
    value_diff: int = 0
    victim_surface: object = None
    board_rect: object = None
    geom: object = None
    from_sq: object = None
    victim_sq: object = None
    attacker_type: object = None
    shot_sound: object = None
    on_shot: object = None
    miss_count: int = 0
    passive: bool = False
    audio: object = None
    hole_squares: object = None
    captured_value: int = 0
    progress: int = 0
    attacker_surface: object = None
    on_hit_px: object = None
    mirror_targets: bool = False
    last_hit_pop: int = -1


def _build_wheel(spec):
    return WheelController(
        WheelChallenge.from_seed(spec.seed, period_ms=spec.period_ms),
        spec.cell_rect, spec.now_ms, min(spec.deadline_ms, WHEEL_TIME_LIMIT_MS),
        on_shot=spec.on_shot, passive=spec.passive, audio=spec.audio)


def _build_aim(spec):
    return AimController(
        AimChallenge.from_seed(spec.seed, spec.value_diff), spec.cell_rect, spec.now_ms,
        min(spec.deadline_ms, AIM_TIME_LIMIT_MS),
        victim_surface=spec.victim_surface, board_rect=spec.board_rect, geom=spec.geom,
        from_sq=spec.from_sq, victim_sq=spec.victim_sq, attacker_type=spec.attacker_type,
        shot_sound=spec.shot_sound, on_shot=spec.on_shot, miss_count=spec.miss_count,
        passive=spec.passive, audio=spec.audio)


def _build_whack(spec):
    return MoleController(
        MoleChallenge.from_seed(spec.seed, spec.value_diff, spec.deadline_ms,
                                spec.captured_value),
        spec.cell_rect, spec.now_ms, spec.deadline_ms,
        hole_squares=spec.hole_squares, victim_surface=spec.victim_surface, geom=spec.geom,
        from_sq=spec.from_sq, shot_sound=spec.shot_sound, on_shot=spec.on_shot,
        miss_count=spec.miss_count, progress=spec.progress,
        passive=spec.passive, audio=spec.audio,
        on_hit_px=spec.on_hit_px, mirror_targets=spec.mirror_targets,
        last_hit_pop=spec.last_hit_pop)


def _build_combo(spec):
    return ComboController(
        ComboChallenge.from_seed(spec.seed, spec.value_diff, spec.deadline_ms,
                                 spec.captured_value),
        spec.cell_rect, spec.now_ms, spec.deadline_ms,
        board_rect=spec.board_rect, geom=spec.geom, victim_surface=spec.victim_surface,
        attacker_surface=spec.attacker_surface, from_sq=spec.from_sq,
        victim_sq=spec.victim_sq, on_shot=spec.on_shot, miss_count=spec.miss_count,
        progress=spec.progress, passive=spec.passive, audio=spec.audio)


_BUILDERS = {
    SkillCheckKind.WHEEL: _build_wheel,
    SkillCheckKind.AIM: _build_aim,
    SkillCheckKind.WHACK: _build_whack,
    SkillCheckKind.COMBO: _build_combo,
}


def build_controller(kind, spec):
    builder = _BUILDERS.get(kind)
    return builder(spec) if builder is not None else None
