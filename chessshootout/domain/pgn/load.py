import os
import re
from dataclasses import dataclass, field
from datetime import datetime

from chessshootout.backend.backend import Backend
from chessshootout.domain.match import Match
from chessshootout.skillcheck.types import KIND_LABEL


@dataclass
class ParsedPGN:
    """
    One PGN file taken apart: its header tags, its moves in play order, the
    result token and the comment that trailed each move. The review screen and
    the history list both work from this instead of re-reading the text
    """

    headers: dict[str, str] = field(default_factory=dict)
    moves: list[str] = field(default_factory=list)
    result: str = "*"
    move_comments: list[str] = field(default_factory=list)


@dataclass
class PgnSummary:
    """
    The one-line description of a saved game that the history list draws: when
    it was played, what kind of game it was, the clock, both players and how it
    ended. Built once per file so scrolling the list never re-parses a game
    """

    path: str
    time: str
    type: str
    time_control: str
    white: str
    black: str
    result_code: str
    sort_key: float
    match_id: str | None = None
    white_captures: int = 0
    black_captures: int = 0
    reason: str = ""
    category: str = "Casual"


BULLET_MAX_MINUTES = 3
BLITZ_MAX_MINUTES = 10

_TAG_RE = re.compile(r'\[(\w+)\s+"([^"]*)"\]')
_RESULT_TOKEN_RE = re.compile(r"^(1-0|0-1|1/2-1/2|\*)$")
_MOVE_NUMBER_PREFIX = re.compile(r"^\d+\.+")
_BARE_NUMBER_RE = re.compile(r"^\d+\.+$")
_NOTE_LABELS = "|".join(re.escape(label) for label in KIND_LABEL.values())
_NOTE_TOKEN_RE = re.compile(rf"^({_NOTE_LABELS})\s+(✓|✗)(?:\s+(\S+))?$")
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


def parse_pgn_headers(text: str) -> dict[str, str]:
    """
    Pull the bracketed header tags out of a PGN file, the cheapest way to learn
    who played a game and how it ended without touching the moves

    :param text: contents of a PGN file
    :returns: tag name to tag value, later tags of a name winning
    """
    return {m.group(1): m.group(2) for m in _TAG_RE.finditer(text)}


def extract_csmatchid(headers: dict[str, str]) -> str | None:
    """
    Read the match id that ties the games of one online series together, so the
    history list can group a rematch chain under a single card. Anything that
    is not a well-formed id is treated as if the game carried none

    :param headers: header tags of a parsed game
    :returns: the match id, or None when the game has no usable one
    """
    raw = headers.get("CSMatchId", "")
    if raw and _CSMATCHID_RE.match(raw):
        return raw
    return None


def termination_reason(result_code: str, termination: str | None,
                       last_san: str) -> str:
    """
    Say in one word how a saved game finished -- checkmate, flagged, resigned,
    draw or unfinished -- for the line under a history card. It reads the real
    tags and the last move rather than guessing from the score alone

    :param result_code: PGN result token, e.g. 1-0 or 1/2-1/2
    :param termination: Termination header when the file carries one
    :param last_san: last move played, whose # marks a mate
    :returns: the short reason label to show
    """
    if last_san and last_san.endswith("#"):
        return "Checkmate"
    if termination == "Time forfeit":
        return "Flagged"
    if result_code in (PGN_WHITE_WIN, PGN_BLACK_WIN):
        return "Resigned"
    if result_code == PGN_DRAW:
        return "Draw"
    return "Unfinished"


def time_category_for_minutes(minutes: int) -> str:
    """
    Sort a clock into the speed bucket players name games by -- Bullet, Blitz
    or Rapid. It labels history cards and the wait screen while an online game
    is being found

    :param minutes: starting clock time per side, in minutes
    :returns: the bucket name
    """
    if minutes < BULLET_MAX_MINUTES:
        return "Bullet"
    if minutes < BLITZ_MAX_MINUTES:
        return "Blitz"
    return "Rapid"


def time_category(time_control_text: str | None) -> str:
    """
    Sort a game into its speed bucket from the clock as it is written on a
    history card, e.g. 5+3. A game whose clock cannot be read is filed as
    Casual rather than guessed at

    :param time_control_text: clock as minutes+increment, or empty when the
        game had no clock
    :returns: the bucket name, Casual when there is no readable clock
    """
    if not time_control_text or "+" not in time_control_text:
        return "Casual"
    try:
        minutes = int(time_control_text.split("+")[0])
    except ValueError:
        return "Casual"
    return time_category_for_minutes(minutes)


def format_relative_time(timestamp: float, now: float) -> str:
    """
    Phrase when a game was played the way the history and recent-games lists
    say it: just now, minutes, hours, Yesterday, a weekday name, then a plain
    date. A timestamp in the future simply reads as just now

    :param timestamp: when the game was played, epoch seconds
    :param now: the current time, epoch seconds
    :returns: the phrase to print on the card
    """
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


def _split_body(body: str) -> tuple[list[str], list[str]]:
    """
    Split PGN movetext into its tokens and the comment that followed each one,
    skipping side lines in parentheses entirely. Comments carry the skill-check
    history, so each one has to stay attached to the move it belongs to

    :param body: movetext, everything after the last header tag
    :returns: the tokens and, aligned position by position with them, each
        token's trailing comment or an empty string
    """
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


def parse_pgn(text: str) -> ParsedPGN:
    """
    Read a whole PGN file into headers, moves, result and per-move comments --
    the entry point the review screen and the history list both start from.
    Move numbers and the result token are filtered out, leaving only moves

    :param text: contents of a PGN file
    :returns: the file taken apart, with moves and comments aligned
    """
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


def parse_comment(text: str) -> list[tuple[str, bool, str]]:
    """
    Read the skill checks recorded in one move comment back out, so a reviewed
    game shows the same hits and misses it was saved with. Anything in the
    comment that is not a skill-check note is ignored

    :param text: comment saved beside one move
    :returns: one entry per check as the check kind, whether it was won, and
        the move it locked on a miss (empty on a win)
    """
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


def load_pgn_into_backend(backend: Backend | Match, text: str) -> tuple[ParsedPGN, bool]:
    """
    Rebuild a saved game inside an engine by starting a new game and replaying
    its moves, which is how the review screen opens a PGN. Replay stops at the
    first move the engine refuses and says so, rather than leaving a
    half-loaded position looking complete

    :param backend: engine or Match wrapper to replay into; it is reset first
    :param text: contents of a PGN file
    :returns: the parsed file and whether every move replayed legally
    """
    parsed = parse_pgn(text)
    backend.new_game()
    for san in parsed.moves:
        move_result = backend.apply_san(san)
        if not move_result.legal:
            return parsed, False
    return parsed, True


def _format_time_from_filename(filename: str, mtime: float) -> tuple[str, float]:
    """
    Date a saved game from the timestamp built into its filename, falling back
    to the file's own modification time. The name is preferred because copying
    a game about changes the file time but not when the game was played

    :param filename: basename of the PGN file
    :param mtime: file modification time, epoch seconds
    :returns: the timestamp to print and the epoch seconds to sort by
    """
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


def parse_time_control(value: str | None) -> tuple[int, int] | None:
    """
    Read the PGN TimeControl tag into its two numbers, the starting time and
    the increment. An untimed or unreadable tag gives nothing back rather than
    a made-up clock

    :param value: TimeControl tag value, e.g. 300+3, or - when untimed
    :returns: initial seconds and increment seconds, or None when there is no
        readable clock
    """
    if not value or value == "-":
        return None
    try:
        initial, incr = value.split("+")
        return int(initial), int(incr)
    except ValueError:
        return None


NO_CLOCK_LABEL = "No clock"


def format_time_control(tc: tuple[float, float] | None) -> str | None:
    """
    Phrase a time control the way players say it, minutes plus increment
    seconds -- 5+3. The game, review and history screens all label clocks with
    this, which is why it lives beside the PGN reader rather than in the UI

    :param tc: initial seconds and increment seconds, None when untimed
    :returns: the label, or None when the game has no clock
    """
    if tc is None:
        return None
    initial, incr = tc
    return f"{int(initial // 60)}+{int(incr)}"


def summarize_pgn_file(path: str, text: str, mtime: float,
                       filename: str | None = None) -> PgnSummary:
    """
    Boil one saved game down to the row the history list draws: when it was
    played, what kind of game it was, the clock, both players, the result and
    how it ended. Everything is read from the file itself -- the kind of game
    from its name, the rest from its tags and moves

    :param path: full path of the PGN file, kept so the game can be opened
    :param text: contents of the file
    :param mtime: file modification time, epoch seconds
    :param filename: basename to read the kind and timestamp from; taken from
        the path when not given
    :returns: the summary row for this game
    """
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


def result_mark(result_code: str, white: str, black: str,
                nickname: str | None) -> tuple[str, str]:
    """
    Mark a saved game from the reading player's point of view: a win, a loss or
    a draw when they played in it, and a neutral W or L when the game is
    somebody else's. This drives the badge and its colour on every history card

    :param result_code: PGN result token, e.g. 1-0
    :param white: name in the White header
    :param black: name in the Black header
    :param nickname: the local player's name; matching neither side means the
        game is shown neutrally
    :returns: the symbol to draw and its outcome class, one of win, loss or
        neutral
    """
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


def scan_pgn_summaries(directory: str, pattern: str) -> list[PgnSummary]:
    """
    Summarise every saved game in a folder, newest first, which is what fills
    the history sub-view and the recent-games card. A file that cannot be read
    is skipped so one bad game never costs the player their whole list

    :param directory: folder to scan; a folder that is not there yields
        nothing
    :param pattern: filename glob whose suffix is matched, e.g. *.pgn
    :returns: the summaries, newest first
    """
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


def group_by_csmatchid(
        summaries: list[PgnSummary],
) -> list[tuple[str | None, list[PgnSummary]]]:
    """
    Gather the games of one online series under their shared match id so a
    rematch chain shows as a single card. Games without a match id stay on
    their own, and the order the caller supplied is kept

    :param summaries: game summaries, already in the order they will be shown
    :returns: each group as its match id and its games, the id being None for
        a game that stands alone
    """
    order: list[tuple[str, str | None]] = []
    groups: dict[str, list[PgnSummary]] = {}
    for summary in summaries:
        key = summary.match_id or f"__solo__{summary.path}"
        if key not in groups:
            groups[key] = []
            order.append((key, summary.match_id))
        groups[key].append(summary)
    return [(match_id, groups[key]) for key, match_id in order]
