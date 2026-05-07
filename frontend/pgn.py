from datetime import date


RESULT_CODES = {
    "white_wins": "1-0",
    "black_wins": "0-1",
    "draw_stalemate": "1/2-1/2",
    "draw_repetition": "1/2-1/2",
    "draw_fifty_move": "1/2-1/2",
    "draw_insufficient_material": "1/2-1/2",
    "draw_agreement": "1/2-1/2",
}


def iter_move_pairs(history):
    for i in range(0, len(history), 2):
        white = history[i]
        black = history[i + 1] if i + 1 < len(history) else None
        yield i // 2 + 1, white, black


def generate_pgn(move_history, result):
    code = RESULT_CODES.get(result, "*")
    header = [
        '[Event "Casual Game"]',
        '[Site "?"]',
        f'[Date "{date.today().strftime("%Y.%m.%d")}"]',
        '[Round "?"]',
        '[White "?"]',
        '[Black "?"]',
        f'[Result "{code}"]',
    ]

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
