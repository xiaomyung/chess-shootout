import glob
import os
import re
from dataclasses import dataclass, field
from datetime import datetime

from chessshootout.skillcheck.types import KIND_LABEL


@dataclass
class ParsedPGN:
    headers: dict = field(default_factory=dict)
    moves: list = field(default_factory=list)
    result: str = "*"
    move_comments: list = field(default_factory=list)


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
    match_id: str = None
    white_captures: int = 0
    black_captures: int = 0
    reason: str = ""
    category: str = "Casual"


_TAG_RE = re.compile(r'\[(\w+)\s+"([^"]*)"\]')
_RESULT_TOKEN_RE = re.compile(r"^(1-0|0-1|1/2-1/2|\*)$")
_MOVE_NUMBER_PREFIX = re.compile(r"^\d+\.+")
_BARE_NUMBER_RE = re.compile(r"^\d+\.+$")
_NOTE_TOKEN_RE = re.compile(r"^(Wheel|Steady-Aim)\s+(✓|✗)(?:\s+(\S+))?$")
_KIND_BY_LABEL = {label: kind for kind, label in KIND_LABEL.items()}
_FILENAME_TS_RE = re.compile(r"(\d{8})-(\d{6})")
_CSMATCHID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_TYPE_LABELS = {
    "online": "Online",
    "bot": "Bot",
    "local": "Local",
    "game": "Local",
}

PGN_WHITE_WIN = "1-0"
PGN_BLACK_WIN = "0-1"
PGN_DRAW = "1/2-1/2"
PGN_UNFINISHED = "*"

MINUTE = 60
HOUR = 3600
DAY = 86400
WEEK = 604800


def parse_pgn_headers(text):
    headers = {}
    for m in _TAG_RE.finditer(text):
        headers[m.group(1)] = m.group(2)
    return headers


def extract_csmatchid(headers):
    raw = headers.get("CSMatchId", "")
    if raw and _CSMATCHID_RE.match(raw):
        return raw
    return None


def termination_reason(result_code, termination, last_san):
    if last_san and last_san.endswith("#"):
        return "Checkmate"
    if termination == "Time forfeit":
        return "Flagged"
    if result_code in (PGN_WHITE_WIN, PGN_BLACK_WIN):
        return "Resigned"
    if result_code == PGN_DRAW:
        return "Draw"
    return "Unfinished"


def time_category(time_control_text):
    if not time_control_text or "+" not in time_control_text:
        return "Casual"
    try:
        minutes = int(time_control_text.split("+")[0])
    except ValueError:
        return "Casual"
    if minutes < 3:
        return "Bullet"
    if minutes < 10:
        return "Blitz"
    return "Rapid"


def format_relative_time(timestamp, now):
    delta = max(now - timestamp, 0)
    if delta < MINUTE:
        return "just now"
    if delta < HOUR:
        return f"{int(delta // MINUTE)}m ago"
    if delta < DAY:
        return f"{int(delta // HOUR)}h ago"
    if delta < 2 * DAY:
        return "Yesterday"
    if delta < WEEK:
        return datetime.fromtimestamp(timestamp).strftime("%a")
    return datetime.fromtimestamp(timestamp).strftime("%Y.%m.%d")


def _split_body(body):
    tokens = []
    comments = []
    depth = 0
    cur = ""
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch == "(":
            if cur:
                tokens.append(cur)
                comments.append("")
                cur = ""
            depth += 1
            i += 1
            continue
        if ch == ")":
            if depth > 0:
                depth -= 1
            i += 1
            continue
        if depth > 0:
            i += 1
            continue
        if ch == "{":
            if cur:
                tokens.append(cur)
                comments.append("")
                cur = ""
            end = body.find("}", i)
            if end == -1:
                note = body[i + 1:].strip()
                i = n
            else:
                note = body[i + 1:end].strip()
                i = end + 1
            if tokens:
                comments[-1] = note
            continue
        if ch.isspace():
            if cur:
                tokens.append(cur)
                comments.append("")
                cur = ""
            i += 1
            continue
        cur += ch
        i += 1
    if cur:
        tokens.append(cur)
        comments.append("")
    return tokens, comments


def parse_pgn(text):
    headers = parse_pgn_headers(text)

    body_match = list(_TAG_RE.finditer(text))
    body_start = body_match[-1].end() if body_match else 0
    body = text[body_start:]

    tokens, comments = _split_body(body)

    result = PGN_UNFINISHED
    moves = []
    move_comments = []
    for token, comment in zip(tokens, comments):
        if _RESULT_TOKEN_RE.match(token):
            result = token
            continue
        if _BARE_NUMBER_RE.match(token):
            continue
        token = _MOVE_NUMBER_PREFIX.sub("", token)
        if token:
            moves.append(token)
            move_comments.append(comment)

    return ParsedPGN(headers=headers, moves=moves, result=result,
                     move_comments=move_comments)


def parse_comment(text):
    events = []
    for part in text.split(" · "):
        match = _NOTE_TOKEN_RE.match(part.strip())
        if match is None:
            continue
        kind = _KIND_BY_LABEL.get(match.group(1))
        if kind is None:
            continue
        events.append((kind, match.group(2) == "✓", match.group(3) or ""))
    return events


def load_pgn_into_backend(backend, text):
    parsed = parse_pgn(text)
    backend.new_game()
    for san in parsed.moves:
        move_result = backend.apply_san(san)
        if not move_result.legal:
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


def latest_pgn_in_dir(directory):
    files = glob.glob(os.path.join(directory, "*.pgn"))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def parse_time_control(value):
    if not value or value == "-":
        return None
    try:
        initial, incr = value.split("+")
        return int(initial), int(incr)
    except ValueError:
        return None


NO_CLOCK_LABEL = "No clock"


def format_time_control(tc):
    if tc is None:
        return None
    initial, incr = tc
    return f"{int(initial // 60)}+{int(incr)}"


def summarize_pgn_file(path, text, mtime, filename=None):
    if filename is None:
        filename = os.path.basename(path)
    parsed = parse_pgn(text)
    headers = parsed.headers
    time_str, sort_key = _format_time_from_filename(filename, mtime)
    type_label = _TYPE_LABELS.get(filename.split("-", 1)[0], "—")
    parsed_tc = parse_time_control(headers.get("TimeControl", "-"))
    time_control = format_time_control(parsed_tc) or NO_CLOCK_LABEL
    last_san = parsed.moves[-1] if parsed.moves else ""
    return PgnSummary(
        path=path,
        time=time_str,
        type=type_label,
        time_control=time_control,
        white=headers.get("White", "?"),
        black=headers.get("Black", "?"),
        result_code=headers.get("Result", PGN_UNFINISHED),
        sort_key=sort_key,
        match_id=extract_csmatchid(headers),
        white_captures=sum(1 for move in parsed.moves[0::2] if "x" in move),
        black_captures=sum(1 for move in parsed.moves[1::2] if "x" in move),
        reason=termination_reason(headers.get("Result", PGN_UNFINISHED),
                                  headers.get("Termination"), last_san),
        category=time_category(time_control),
    )


_SPECTATOR_SYMBOLS = {PGN_WHITE_WIN: "W", PGN_BLACK_WIN: "L"}


def result_mark(result_code, white, black, nickname):
    if nickname and nickname == white:
        won, lost = PGN_WHITE_WIN, PGN_BLACK_WIN
    elif nickname and nickname == black:
        won, lost = PGN_BLACK_WIN, PGN_WHITE_WIN
    else:
        return _SPECTATOR_SYMBOLS.get(result_code, "="), "neutral"
    if result_code == won:
        return "+", "win"
    if result_code == lost:
        return "-", "loss"
    return "=", "neutral"


def scan_pgn_summaries(directory, pattern):
    if not os.path.isdir(directory):
        return []
    suffix = pattern.lstrip("*")
    summaries = []
    for name in os.listdir(directory):
        if not name.endswith(suffix):
            continue
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            mtime = os.path.getmtime(path)
        except (OSError, UnicodeDecodeError):
            continue
        summaries.append(summarize_pgn_file(path, text, mtime, filename=name))
    summaries.sort(
        key=lambda s: (s.sort_key, os.path.basename(s.path)), reverse=True,
    )
    return summaries


def group_by_csmatchid(summaries):
    order = []
    groups = {}
    for summary in summaries:
        key = summary.match_id or f"__solo__{summary.path}"
        if key not in groups:
            groups[key] = []
            order.append((key, summary.match_id))
        groups[key].append(summary)
    return [(match_id, groups[key]) for key, match_id in order]
