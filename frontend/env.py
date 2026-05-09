import os
import uuid
from pathlib import Path

from dotenv import load_dotenv, set_key


_DEFAULT_SERVER_ADDR = "localhost:8000"

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
        _uuid_override = client_uuid
    if nickname is not None:
        _nickname_override = nickname


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


def _persist(key, value):
    _ENV_PATH.touch(exist_ok=True)
    set_key(str(_ENV_PATH), key, value)
