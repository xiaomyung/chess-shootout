from collections.abc import Callable, Sequence
from dataclasses import dataclass

import pygame as pg

from chessshootout.backend.utils import Square
from chessshootout.frontend.audio.sound_manager import SoundManager
from chessshootout.frontend.skillcheck.aim_view import AimController, AIM_TIME_LIMIT_MS
from chessshootout.frontend.skillcheck.combo_view import ComboController
from chessshootout.frontend.skillcheck.controller import SkillCheckController
from chessshootout.frontend.skillcheck.mole_view import MoleController
from chessshootout.frontend.skillcheck.wheel_view import WheelController, WHEEL_TIME_LIMIT_MS
from chessshootout.skillcheck.aim import AimChallenge
from chessshootout.skillcheck.combo import ComboChallenge
from chessshootout.skillcheck.mole import MoleChallenge
from chessshootout.skillcheck.types import SkillCheckKind
from chessshootout.skillcheck.wheel import WheelChallenge, WHEEL_PERIOD_MS


@dataclass(frozen=True, kw_only=True)
class CheckSpec:
    """
    Everything any skill check might need to be built, gathered into one frozen
    bundle by the game screen's session -- deliberately the union of all four
    kinds' arguments rather than a bundle per kind. Together with the builder
    table below and build_controller, this dataclass is THE single place a new
    kind is wired into the frontend: a field here if it needs one, a builder
    there, and nothing else changes
    """

    seed: str
    cell_rect: pg.Rect
    now_ms: int
    deadline_ms: float
    period_ms: float = WHEEL_PERIOD_MS
    value_diff: int = 0
    victim_surface: pg.Surface | None = None
    board_rect: pg.Rect | None = None
    geom: Callable[[Square | str], tuple[float, float]] | None = None
    from_sq: Square | None = None
    victim_sq: Square | None = None
    attacker_type: str | None = None
    shot_sound: Callable[[], None] | None = None
    on_shot: Callable[..., None] | None = None
    miss_count: int = 0
    passive: bool = False
    audio: SoundManager | None = None
    hole_squares: Sequence[tuple[int, int]] | None = None
    captured_value: int = 0
    progress: int = 0
    attacker_surface: pg.Surface | None = None
    on_hit_px: Callable[[tuple[float, float], bool], None] | None = None
    mirror_targets: bool = False
    last_hit_pop: int = -1
    adjudicated_flipped: bool | None = None


def _build_wheel(spec: CheckSpec) -> WheelController:
    """
    Build the tap-the-arc dial, the kind promotions always fire. The whole
    wheel comes from the seed, so the server judging the tap and both screens
    drawing it hold the same dial, and the deadline is capped at the wheel's
    own time limit however long the caller allows

    :param spec: the build bundle; the wheel reads the seed, the square's rect,
        the clock, the deadline, the needle period and the online hooks
    :returns: the controller to hand to the overlay
    """
    return WheelController(
        WheelChallenge.from_seed(spec.seed, period_ms=spec.period_ms),
        spec.cell_rect, spec.now_ms, min(spec.deadline_ms, WHEEL_TIME_LIMIT_MS),
        on_shot=spec.on_shot, passive=spec.passive, audio=spec.audio)


def _build_aim(spec: CheckSpec) -> AimController:
    """
    Build the steady-aim check, where a crosshair sweeps a figure-8 over a
    shrinking victim and every miss escalates. It is the kind that needs the
    most of the board: the victim's sprite to shrink, the board rect to dim
    and the square resolver so the attacker's dry-fire is staged from its own
    square

    :param spec: the build bundle; aim reads the seed, the material difference,
        the geometry and sprites, the shot sound and the online hooks
    :returns: the controller to hand to the overlay
    """
    return AimController(
        AimChallenge.from_seed(spec.seed, spec.value_diff), spec.cell_rect, spec.now_ms,
        min(spec.deadline_ms, AIM_TIME_LIMIT_MS),
        victim_surface=spec.victim_surface, board_rect=spec.board_rect, geom=spec.geom,
        from_sq=spec.from_sq, victim_sq=spec.victim_sq, attacker_type=spec.attacker_type,
        shot_sound=spec.shot_sound, on_shot=spec.on_shot, miss_count=spec.miss_count,
        passive=spec.passive, audio=spec.audio)


def _build_whack(spec: CheckSpec) -> MoleController:
    """
    Build the whack-a-mole check, the positional kind: the victim pops out of
    holes dug across real board squares and has to be shot a quota of times.
    The hole squares are re-derived from the seed by the session rather than
    taken off the wire, so what the player shoots at is what the server judges

    :param spec: the build bundle; whack reads the seed, the captured piece's
        value for its quota, the hole squares, the board geometry, the hit hook
        and the mirror flags that keep a spectated shot on the right end of the
        board
    :returns: the controller to hand to the overlay
    """
    return MoleController(
        MoleChallenge.from_seed(spec.seed, spec.value_diff, spec.deadline_ms,
                                spec.captured_value),
        spec.cell_rect, spec.now_ms, spec.deadline_ms,
        hole_squares=spec.hole_squares, victim_surface=spec.victim_surface, geom=spec.geom,
        from_sq=spec.from_sq, shot_sound=spec.shot_sound, on_shot=spec.on_shot,
        miss_count=spec.miss_count, progress=spec.progress,
        passive=spec.passive, audio=spec.audio,
        on_hit_px=spec.on_hit_px, mirror_targets=spec.mirror_targets,
        last_hit_pop=spec.last_hit_pop, adjudicated_flipped=spec.adjudicated_flipped)


def _build_combo(spec: CheckSpec) -> ComboController:
    """
    Build the combo check, where directional prompts have to be answered in
    order and too many wrong answers lose the capture. Both fighters are drawn
    inside it, so it is the one kind that also wants the attacker's sprite

    :param spec: the build bundle; combo reads the seed, the material
        difference, the captured value for its prompt count, both sprites, the
        board geometry and the online hooks
    :returns: the controller to hand to the overlay
    """
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


def build_controller(kind: SkillCheckKind, spec: CheckSpec) -> SkillCheckController | None:
    """
    Turn a kind into the view that plays it -- the single call the game screen
    makes to put any skill check on screen, and with the builder table above
    the one place a new kind is wired in. A kind with no builder, such as NONE,
    simply gets nothing back, and the caller reads that as no check to show

    :param kind: which mini-game to build, chosen locally or by the server
    :param spec: the build bundle every kind is assembled from
    :returns: the controller for that kind, or None when nothing builds it
    """
    builder = _BUILDERS.get(kind)
    return builder(spec) if builder is not None else None
