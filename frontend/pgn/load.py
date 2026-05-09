import re
from dataclasses import dataclass, field


@dataclass
class ParsedPGN:
    headers: dict = field(default_factory=dict)
    moves: list = field(default_factory=list)
    result: str = "*"


_TAG_RE = re.compile(r'\[(\w+)\s+"([^"]*)"\]')
_COMMENT_RE = re.compile(r"\{[^}]*\}")
_VARIATION_RE = re.compile(r"\([^()]*\)")
_RESULT_RE = re.compile(r"(1-0|0-1|1/2-1/2|\*)\s*$")
_MOVE_NUMBER_PREFIX = re.compile(r"^\d+\.+")
_BARE_NUMBER_RE = re.compile(r"^\d+\.+$")


def parse_pgn(text):
    headers = {}
    for m in _TAG_RE.finditer(text):
        headers[m.group(1)] = m.group(2)

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
