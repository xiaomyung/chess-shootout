import os
import re
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ParsedPGN:
    headers: dict = field(default_factory=dict)
    moves: list = field(default_factory=list)
    result: str = "*"


@dataclass
class PgnSummary:
    path: str
    time: str
    type: str
    time_control: str
    white: str
    black: str
    result_code: str
    sort_key: float


_TAG_RE = re.compile(r'\[(\w+)\s+"([^"]*)"\]')
_COMMENT_RE = re.compile(r"\{[^}]*\}")
_VARIATION_RE = re.compile(r"\([^()]*\)")
_RESULT_RE = re.compile(r"(1-0|0-1|1/2-1/2|\*)\s*$")
_MOVE_NUMBER_PREFIX = re.compile(r"^\d+\.+")
_BARE_NUMBER_RE = re.compile(r"^\d+\.+$")
_FILENAME_TS_RE = re.compile(r"(\d{8})-(\d{6})")

_TYPE_LABELS = {
    "online": "Online",
    "bot": "Bot",
    "local": "Local",
    "game": "Local",
}


def parse_pgn_headers(text):
    headers = {}
    for m in _TAG_RE.finditer(text):
        headers[m.group(1)] = m.group(2)
    return headers


def parse_pgn(text):
    headers = parse_pgn_headers(text)

    body_match = list(_TAG_RE.finditer(text))
    body_start = body_match[-1].end() if body_match else 0
    body = text[body_start:]

    body = _COMMENT_RE.sub(" ", body)

    while True:
        new_body = _VARIATION_RE.sub(" ", body)
        if new_body == body:
            break
        body = new_body

    result = "*"
    result_match = _RESULT_RE.search(body)
    if result_match:
        result = result_match.group(1)
        body = body[: result_match.start()]

    moves = []
    for token in body.split():
        if _BARE_NUMBER_RE.match(token):
            continue
        token = _MOVE_NUMBER_PREFIX.sub("", token)
        if token:
            moves.append(token)

    return ParsedPGN(headers=headers, moves=moves, result=result)


def load_pgn_into_backend(backend, text):
    parsed = parse_pgn(text)
    backend.new_game()
    for san in parsed.moves:
        result = backend.apply_san(san)
        if not result.legal:
            return parsed, False
    return parsed, True


def _format_time_from_filename(filename, mtime):
    match = _FILENAME_TS_RE.search(filename)
    if match:
        try:
            dt = datetime.strptime(
                f"{match.group(1)}-{match.group(2)}", "%Y%m%d-%H%M%S",
            )
            return dt.strftime("%Y.%m.%d %H:%M:%S"), dt.timestamp()
        except ValueError:
            pass
    return datetime.fromtimestamp(mtime).strftime("%Y.%m.%d %H:%M:%S"), mtime


def _format_time_control(value):
    if not value or value == "-":
        return "No clock"
    try:
        initial, incr = value.split("+")
        return f"{int(initial) // 60}+{int(incr)}"
    except ValueError:
        return "No clock"


def summarize_pgn_file(path, text, mtime, filename=None):
    if filename is None:
        filename = os.path.basename(path)
    headers = parse_pgn_headers(text)
    time_str, sort_key = _format_time_from_filename(filename, mtime)
    type_label = _TYPE_LABELS.get(filename.split("-", 1)[0], "—")
    return PgnSummary(
        path=path,
        time=time_str,
        type=type_label,
        time_control=_format_time_control(headers.get("TimeControl", "-")),
        white=headers.get("White", "?"),
        black=headers.get("Black", "?"),
        result_code=headers.get("Result", "*"),
        sort_key=sort_key,
    )
