from datetime import date


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


def iter_move_pairs(history):
    for i in range(0, len(history), 2):
        white = history[i]
        black = history[i + 1] if i + 1 < len(history) else None
        yield i // 2 + 1, white, black


def generate_pgn(move_history, result, white_name="?", black_name="?",
                 time_control=None, termination=None):
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
        f'[White "{white_name}"]',
        f'[Black "{black_name}"]',
        f'[Result "{code}"]',
        f'[TimeControl "{tc_value}"]',
    ]
    if termination is not None:
        header.append(f'[Termination "{termination}"]')

    parts = []
    for number, white, black in iter_move_pairs(move_history):
        if black is not None:
            parts.append(f"{number}. {white.san} {black.san}")
        else:
            parts.append(f"{number}. {white.san}")

    body = " ".join(parts)
    if code != "*":
        body = f"{body} {code}" if body else code

    return "\n".join(header) + "\n\n" + body + "\n"
