from chessshootout.frontend.skillcheck.aim_view import AimController, AIM_TIME_LIMIT_MS
from chessshootout.frontend.skillcheck.combo_view import ComboController, COMBO_TIME_LIMIT_MS
from chessshootout.frontend.skillcheck.wheel_view import WheelController, WHEEL_TIME_LIMIT_MS
from chessshootout.skillcheck.aim import AimChallenge
from chessshootout.skillcheck.combo import ComboChallenge
from chessshootout.skillcheck.mole import MoleChallenge
from chessshootout.skillcheck.types import SkillCheckKind
from chessshootout.skillcheck.wheel import (
    WheelChallenge, WHEEL_PERIOD_MS, SKILLCHECK_DEADLINE_MS)


def build_controller(kind, *, seed, cell_rect, now_ms, deadline_ms, period_ms=WHEEL_PERIOD_MS,
                     value_diff=0, victim_surface=None, board_rect=None, geom=None,
                     from_sq=None, victim_sq=None, attacker_type=None, shot_sound=None,
                     on_shot=None, miss_count=0, passive=False, audio=None,
                     hole_squares=None, px_to_board=None, captured_value=0, progress=0,
                     attacker_surface=None):
    if kind == SkillCheckKind.WHEEL:
        return WheelController(
            WheelChallenge.from_seed(seed, period_ms=period_ms), cell_rect, now_ms,
            min(deadline_ms, WHEEL_TIME_LIMIT_MS), on_shot=on_shot, passive=passive, audio=audio)
    if kind == SkillCheckKind.AIM:
        return AimController(
            AimChallenge.from_seed(seed, value_diff), cell_rect, now_ms,
            min(deadline_ms, AIM_TIME_LIMIT_MS),
            victim_surface=victim_surface, board_rect=board_rect, geom=geom,
            from_sq=from_sq, victim_sq=victim_sq, attacker_type=attacker_type,
            shot_sound=shot_sound, on_shot=on_shot, miss_count=miss_count, passive=passive,
            audio=audio)
    if kind == SkillCheckKind.WHACK:
        from chessshootout.frontend.skillcheck.mole_view import MoleController
        clamped = min(deadline_ms, SKILLCHECK_DEADLINE_MS)
        return MoleController(
            MoleChallenge.from_seed(seed, value_diff, clamped, captured_value),
            cell_rect, now_ms, clamped,
            hole_squares=hole_squares, px_to_board=px_to_board, victim_surface=victim_surface,
            board_rect=board_rect, geom=geom, from_sq=from_sq, victim_sq=victim_sq,
            attacker_type=attacker_type, shot_sound=shot_sound, on_shot=on_shot,
            miss_count=miss_count, progress=progress, passive=passive, audio=audio)
    if kind == SkillCheckKind.COMBO:
        clamped = min(deadline_ms, COMBO_TIME_LIMIT_MS)
        return ComboController(
            ComboChallenge.from_seed(seed, value_diff, clamped, captured_value),
            cell_rect, now_ms, clamped,
            board_rect=board_rect, geom=geom, victim_surface=victim_surface,
            attacker_surface=attacker_surface, from_sq=from_sq, victim_sq=victim_sq,
            on_shot=on_shot, miss_count=miss_count, progress=progress, passive=passive,
            audio=audio)
    return None
