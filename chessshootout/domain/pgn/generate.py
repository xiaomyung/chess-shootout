from collections.abc import Iterator
from datetime import date

from chessshootout.backend.utils import HistoryEntry
from chessshootout.skillcheck.types import KIND_LABEL, SkillCheckOutcome


RESULT_CODES = {
    "white_wins": "1-0",
    "black_wins": "0-1",
    "white_wins_on_time": "1-0",
    "black_wins_on_time": "0-1",
    "white_wins_by_resignation": "1-0",
    "black_wins_by_resignation": "0-1",
    "white_wins_by_abandonment": "1-0",
    "black_wins_by_abandonment": "0-1",
    "draw_stalemate": "1/2-1/2",
    "draw_repetition": "1/2-1/2",
    "draw_fifty_move": "1/2-1/2",
    "draw_insufficient_material": "1/2-1/2",
    "draw_agreement": "1/2-1/2",
}

TIMEOUT_RESULTS = {"white_wins_on_time", "black_wins_on_time"}

TAG_UNSAFE_CHARS = '"\\[]'
COMMENT_UNSAFE_CHARS = "{}[]\\"
COMMENT_MAX_CHARS = 256


def tag_value(raw: object) -> str:
    """
    Make one value safe to write into a PGN header, dropping the quotes,
    brackets, backslashes and unprintable characters that would break the tag
    or smuggle a second tag into the file. Player nicknames, match ids and
    termination text all pass through here

    :param raw: value destined for a header, stringified as it comes
    :returns: the value with every unsafe character removed
    """
    return "".join(c for c in str(raw) if c not in TAG_UNSAFE_CHARS and c.isprintable())


def comment_value(raw: object) -> str:
    """
    Make one value safe to write inside a movetext comment, dropping the braces
    and brackets that would close the comment early and capping how long it can
    get. Skill-check notes are the only comments the game writes

    :param raw: comment text, stringified as it comes
    :returns: the sanitised comment, no longer than COMMENT_MAX_CHARS
    """
    kept = "".join(
        c for c in str(raw) if c not in COMMENT_UNSAFE_CHARS and c.isprintable())
    return kept[:COMMENT_MAX_CHARS]


def iter_move_pairs(
        history: list[HistoryEntry],
) -> Iterator[tuple[int, HistoryEntry, HistoryEntry | None]]:
    """
    Walk a game one numbered move at a time, White's ply beside Black's reply.
    That is the shape both the PGN body and the on-screen move list are laid
    out in, so both are built from this

    :param history: plies in play order
    :returns: for each move, its number, White's entry and Black's entry, the
        latter None when the game ended on White's ply
    """
    for i in range(0, len(history), 2):
        white = history[i]
        black = history[i + 1] if i + 1 < len(history) else None
        yield i // 2 + 1, white, black


def format_annotations(log: list[SkillCheckOutcome]) -> dict[int, str]:
    """
    Turn the game's resolved skill checks into the note saved beside each move,
    one line per ply naming every check with a hit or miss mark and, for a
    miss, the move it locked. This is what lets a saved game be reviewed with
    its shootout history intact

    :param log: resolved skill checks in play order
    :returns: ply number to its note text; plies with no check are absent
    """
    by_ply = {}
    for outcome in log:
        by_ply.setdefault(outcome.ply, []).append(outcome)
    annotations = {}
    for ply, outcomes in by_ply.items():
        tokens = []
        for outcome in outcomes:
            label = KIND_LABEL.get(outcome.kind, outcome.kind)
            if outcome.won:
                tokens.append(f"{label} ✓")
            elif outcome.san:
                tokens.append(f"{label} ✗ {outcome.san}")
            else:
                tokens.append(f"{label} ✗")
        annotations[ply] = " · ".join(tokens)
    return annotations


def _with_annotation(san: str, annotations: dict[int, str], ply: int) -> str:
    """
    Hang a ply's skill-check note off its move as a brace comment, leaving the
    move bare when that ply has nothing to report

    :param san: the move as it was recorded at move time, never recomputed
    :param annotations: ply number to note text
    :param ply: 1-based ply this move is
    :returns: the move, followed by its comment when it has one
    """
    raw = annotations.get(ply)
    note = comment_value(raw) if raw else ""
    return f"{san} {{{note}}}" if note else san


def generate_pgn(move_history: list[HistoryEntry], result: str | None,
                 white_name: str = "?", black_name: str = "?",
                 time_control: tuple[float, float] | None = None,
                 termination: str | None = None, match_id: str | None = None,
                 annotations: dict[int, str] | None = None) -> str:
    """
    Write a game out as PGN text, the form every saved game is kept in and
    every reviewed game is read back from. Autosave calls it again and again
    while a game runs, so a game with no result yet is written with an open
    result of * and finished later

    :param move_history: plies in play order; each move's notation is taken
        from the entry itself and never worked out again
    :param result: result code for the finished game, None while it is live
    :param white_name: name to put in the White header
    :param black_name: name to put in the Black header
    :param time_control: initial seconds and increment seconds, None untimed
    :param termination: text for the Termination header; a game lost on time
        fills this in for itself when None is passed
    :param match_id: id tying the games of one online series together
    :param annotations: ply number to skill-check note, saved as comments
    :returns: the complete PGN document, headers then movetext
    """
    annotations = annotations or {}
    code = RESULT_CODES.get(result, "*")
    if time_control is None:
        tc_value = "-"
    else:
        initial, incr = time_control
        tc_value = f"{int(initial)}+{int(incr)}"

    if termination is None and result in TIMEOUT_RESULTS:
        termination = "Time forfeit"

    header = [
        '[Event "Casual Game"]',
        '[Site "?"]',
        f'[Date "{date.today().strftime("%Y.%m.%d")}"]',
        '[Round "?"]',
        f'[White "{tag_value(white_name)}"]',
        f'[Black "{tag_value(black_name)}"]',
        f'[Result "{code}"]',
        f'[TimeControl "{tc_value}"]',
    ]
    if match_id is not None:
        header.append(f'[CSMatchId "{tag_value(match_id)}"]')
    if termination is not None:
        header.append(f'[Termination "{tag_value(termination)}"]')

    parts = []
    for idx, (number, white, black) in enumerate(iter_move_pairs(move_history)):
        white_str = _with_annotation(white.san, annotations, idx * 2 + 1)
        if black is not None:
            black_str = _with_annotation(black.san, annotations, idx * 2 + 2)
            parts.append(f"{number}. {white_str} {black_str}")
        else:
            parts.append(f"{number}. {white_str}")
    body = " ".join(parts)
    if code != "*":
        body = f"{body} {code}" if body else code

    return "\n".join(header) + "\n\n" + body + "\n"
