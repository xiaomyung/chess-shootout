from backend.pieces import opponent_of
from domain.capture_summary import (
    PIECE_VALUES, captured_by, material_advantage,
)


def _ko_count(history, color):
    return len(captured_by(history, color))


def _checks_given(history):
    return sum(1 for e in history if e.gives_check or e.gives_checkmate)


def _full_moves(history):
    return (len(history) + 1) // 2


def _best_streak(history):
    run_color = None
    run_len = 0
    run_start = None
    best_len = 0
    best_start = None
    for i, entry in enumerate(history):
        if entry.move.captured is None:
            run_color, run_len, run_start = None, 0, None
            continue
        color = entry.move.piece.color
        if color == run_color:
            run_len += 1
        else:
            run_color, run_len, run_start = color, 1, i
        if run_len > best_len:
            best_len, best_start = run_len, run_start
    return best_len, best_start


def _biggest_capture(history):
    best_value = 0
    best_index = None
    for i, entry in enumerate(history):
        cap = entry.move.captured
        if cap is None:
            continue
        value = PIECE_VALUES.get(cap.type, 0)
        if value > best_value:
            best_value, best_index = value, i
    return best_index


def _play_of_the_game(history):
    best_len, best_start = _best_streak(history)
    if best_len >= 2 and best_start is not None:
        return f"{history[best_start].san} kicked off a {best_len}-KO streak"
    index = _biggest_capture(history)
    if index is not None:
        return f"{history[index].san} drew first blood"
    return None


def compute_result_stats(history, clock, subject_color):
    opponent = opponent_of(subject_color)
    best_len, _ = _best_streak(history)
    clock_left = None
    if clock is not None:
        clock_left = clock.remaining(subject_color)
    return {
        "kos": (_ko_count(history, subject_color), _ko_count(history, opponent)),
        "streak": best_len,
        "checks": _checks_given(history),
        "moves": _full_moves(history),
        "clock_left": clock_left,
        "material": material_advantage(history, subject_color),
        "play_of_the_game": _play_of_the_game(history),
    }
