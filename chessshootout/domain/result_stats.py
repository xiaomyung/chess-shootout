from typing import Any

from chessshootout.backend.clock import Clock
from chessshootout.backend.pieces import PIECE_VALUES, PieceColor, opponent_of
from chessshootout.backend.utils import HistoryEntry
from chessshootout.domain.capture_summary import captured_by, material_advantage


def _ko_count(history: list[HistoryEntry], color: PieceColor) -> int:
    """
    Count the pieces one side shot down over the game -- the KO tally the
    result screen shows for each player. One KO is one captured piece

    :param history: plies of the finished game in play order
    :param color: the capturing side
    :returns: how many pieces that side took
    """
    return len(captured_by(history, color))


def _checks_given(history: list[HistoryEntry]) -> int:
    """
    Count the checks delivered in the game, mates included, for the checks line
    of the result stats. Every checking ply in the history counts, whichever
    side played it

    :param history: plies of the finished game in play order
    :returns: how many plies gave check or checkmate
    """
    return sum(1 for e in history if e.gives_check or e.gives_checkmate)


def _full_moves(history: list[HistoryEntry]) -> int:
    """
    Convert a ply count into the move number players speak in, where one move
    is White's ply plus Black's reply. A game that stops after White's ply
    still counts that move as played

    :param history: plies of the finished game in play order
    :returns: how many full moves the game lasted
    """
    return (len(history) + 1) // 2


def _best_streak(history: list[HistoryEntry]) -> tuple[int, int | None]:
    """
    Find the longest run of captures one side made back to back, the streak the
    result screen brags about. A quiet move or a capture by the other side ends
    the run

    :param history: plies of the finished game in play order
    :returns: length of the best run and the index of the ply that opened it,
        the index being None when nothing was ever captured
    """
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


def _biggest_capture(history: list[HistoryEntry]) -> int | None:
    """
    Point at the ply that took the most valuable piece, the fallback highlight
    for a game where nobody strung captures together. The earliest ply wins a
    tie, so the first big hit is the one remembered

    :param history: plies of the finished game in play order
    :returns: index of that ply, or None when no piece was ever taken
    """
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


def _play_of_the_game(history: list[HistoryEntry]) -> str | None:
    """
    Write the play-of-the-game line for the result screen, preferring the move
    that opened the longest KO streak and falling back to the first big
    capture. A game with nothing worth showing gets no line at all

    :param history: plies of the finished game in play order
    :returns: the highlight line, or None when the game had no highlight
    """
    best_len, best_start = _best_streak(history)
    if best_len >= 2 and best_start is not None:
        return f"{history[best_start].san} kicked off a {best_len}-KO streak"
    index = _biggest_capture(history)
    if index is not None:
        return f"{history[index].san} drew first blood"
    return None


def compute_result_stats(history: list[HistoryEntry], clock: Clock | None,
                         subject_color: PieceColor) -> dict[str, Any]:
    """
    Build the whole block of numbers the result screen shows when a game ends:
    KOs for each side, the best capture streak, checks, moves played, time
    left, material lead and the play of the game. The subject is the side the
    figures are told from, normally the local player

    :param history: plies of the finished game in play order
    :param clock: game clock, read for the time-left figure; None when untimed
    :param subject_color: side the stats are presented for
    :returns: stat name to value, ready for the result screen to draw
    """
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
