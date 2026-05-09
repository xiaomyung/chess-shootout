import hashlib
import os
import re
import uuid
from pathlib import Path

from dotenv import load_dotenv

_KEY_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


_DEFAULT_SERVER_ADDR = "localhost:8000"
_DEFAULT_MASTER_VOLUME = 0.70

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

_uuid_override = None
_nickname_override = None


def load():
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH, override=False)


def set_overrides(*, client_uuid=None, nickname=None):
    global _uuid_override, _nickname_override
    if client_uuid is not None:
        _uuid_override = _coerce_to_uuid4(client_uuid)
    if nickname is not None:
        _nickname_override = nickname


def _coerce_to_uuid4(value):
    try:
        parsed = uuid.UUID(value)
        if parsed.version == 4:
            return str(parsed)
    except ValueError:
        pass
    digest = hashlib.sha256(f"chess-debug-alias:{value}".encode()).hexdigest()[:32]
    digest = digest[:12] + "4" + digest[13:16] + "8" + digest[17:32]
    return f"{digest[0:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


def get_server_addr():
    return os.environ.get("CHESS_SERVER_ADDR") or _DEFAULT_SERVER_ADDR


def get_nickname():
    if _nickname_override:
        return _nickname_override
    return os.environ.get("CHESS_NICKNAME") or ""


def get_or_create_client_uuid():
    if _uuid_override:
        return _uuid_override
    existing = os.environ.get("CHESS_CLIENT_UUID")
    if existing:
        return existing
    fresh = str(uuid.uuid4())
    os.environ["CHESS_CLIENT_UUID"] = fresh
    _persist("CHESS_CLIENT_UUID", fresh)
    return fresh


def get_last_mode():
    return os.environ.get("CHESS_LAST_MODE") or ""


def set_last_mode(mode):
    os.environ["CHESS_LAST_MODE"] = mode
    _persist("CHESS_LAST_MODE", mode)


def get_master_volume():
    raw = os.environ.get("CHESS_MASTER_VOLUME")
    if not raw:
        return _DEFAULT_MASTER_VOLUME
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_MASTER_VOLUME
    return max(0.0, min(1.0, value))


def set_master_volume(value):
    clamped = max(0.0, min(1.0, float(value)))
    os.environ["CHESS_MASTER_VOLUME"] = f"{clamped:.3f}"
    _persist("CHESS_MASTER_VOLUME", f"{clamped:.3f}")


def _persist(key, value):
    existing = _ENV_PATH.read_text() if _ENV_PATH.exists() else ""
    out_lines = []
    replaced = False
    for line in existing.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue
        match = _KEY_LINE_RE.match(stripped)
        if match is None:
            continue
        if match.group(1) == key:
            out_lines.append(f"{key}={value}")
            replaced = True
        else:
            out_lines.append(line)
    if not replaced:
        out_lines.append(f"{key}={value}")
    body = "\n".join(out_lines) + "\n"
    tmp_path = _ENV_PATH.with_suffix(_ENV_PATH.suffix + f".tmp.{os.getpid()}")
    tmp_path.write_text(body)
    os.replace(tmp_path, _ENV_PATH)
