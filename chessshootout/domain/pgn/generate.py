from datetime import date

from chessshootout.skillcheck.types import KIND_LABEL


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


def tag_value(raw):
    return "".join(c for c in str(raw) if c not in TAG_UNSAFE_CHARS and c.isprintable())


def comment_value(raw):
    kept = "".join(
        c for c in str(raw) if c not in COMMENT_UNSAFE_CHARS and c.isprintable())
    return kept[:COMMENT_MAX_CHARS]


def iter_move_pairs(history):
    for i in range(0, len(history), 2):
        white = history[i]
        black = history[i + 1] if i + 1 < len(history) else None
        yield i // 2 + 1, white, black


def format_annotations(log):
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


def _with_annotation(san, annotations, ply):
    raw = annotations.get(ply)
    note = comment_value(raw) if raw else ""
    return f"{san} {{{note}}}" if note else san


def generate_pgn(move_history, result, white_name="?", black_name="?",
                 time_control=None, termination=None, match_id=None,
                 annotations=None):
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
