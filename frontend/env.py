import hashlib
import os
import re
import uuid
from pathlib import Path

from dotenv import load_dotenv

import paths

_KEY_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


_DEFAULT_SERVER_ADDR = "localhost:8000"
_DEFAULT_MASTER_VOLUME = 0.70
_EFFECT_INTENSITIES = ("subtle", "balanced", "full")
_DEFAULT_EFFECT_INTENSITY = "full"
_THEMES = ("dark",)
_DEFAULT_THEME = "dark"
_DEFAULT_TIME_CONTROL = "10"
_DEFAULT_INCREMENT = "5"
TIME_CONTROL_VALUES = ("1", "3", "5", "10", "15", "∞")
INCREMENT_VALUES = ("0", "2", "5", "10", "15")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

_uuid_override = None
_nickname_override = None


def init_paths():
    global _ENV_PATH
    _ENV_PATH = paths.get_config_dir() / ".env"


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


def set_server_addr(value):
    value = (value or "").strip()
    if not value:
        return
    os.environ["CHESS_SERVER_ADDR"] = value
    _persist("CHESS_SERVER_ADDR", value)


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


def get_data_dir_override():
    return os.environ.get("CHESS_DATA_DIR") or ""


def set_data_dir(path):
    if path:
        os.environ["CHESS_DATA_DIR"] = path
        _persist("CHESS_DATA_DIR", path)
    else:
        os.environ.pop("CHESS_DATA_DIR", None)
        _persist_delete("CHESS_DATA_DIR")


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


def get_reduce_motion():
    return os.environ.get("CHESS_REDUCE_MOTION") == "1"


def set_reduce_motion(value):
    serialized = "1" if value else "0"
    os.environ["CHESS_REDUCE_MOTION"] = serialized
    _persist("CHESS_REDUCE_MOTION", serialized)


def get_effect_intensity():
    value = os.environ.get("CHESS_EFFECT_INTENSITY")
    if value in _EFFECT_INTENSITIES:
        return value
    return _DEFAULT_EFFECT_INTENSITY


def set_effect_intensity(value):
    if value not in _EFFECT_INTENSITIES:
        value = _DEFAULT_EFFECT_INTENSITY
    os.environ["CHESS_EFFECT_INTENSITY"] = value
    _persist("CHESS_EFFECT_INTENSITY", value)


def get_default_time_control():
    value = os.environ.get("CHESS_DEFAULT_TC") or _DEFAULT_TIME_CONTROL
    return value if value in TIME_CONTROL_VALUES else _DEFAULT_TIME_CONTROL


def set_default_time_control(value):
    if value not in TIME_CONTROL_VALUES:
        value = _DEFAULT_TIME_CONTROL
    os.environ["CHESS_DEFAULT_TC"] = value
    _persist("CHESS_DEFAULT_TC", value)


def get_default_increment():
    value = os.environ.get("CHESS_DEFAULT_INCREMENT") or _DEFAULT_INCREMENT
    return value if value in INCREMENT_VALUES else _DEFAULT_INCREMENT


def set_default_increment(value):
    if value not in INCREMENT_VALUES:
        value = _DEFAULT_INCREMENT
    os.environ["CHESS_DEFAULT_INCREMENT"] = value
    _persist("CHESS_DEFAULT_INCREMENT", value)


def default_time_minutes():
    value = get_default_time_control()
    return None if value == "∞" else int(value)


def default_increment_seconds():
    return int(get_default_increment())


def get_theme():
    value = os.environ.get("CHESS_THEME")
    if value in _THEMES:
        return value
    return _DEFAULT_THEME


def set_theme(value):
    if value not in _THEMES:
        value = _DEFAULT_THEME
    os.environ["CHESS_THEME"] = value
    _persist("CHESS_THEME", value)


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
    _atomic_write(body)


def _persist_delete(key):
    if not _ENV_PATH.exists():
        return
    out_lines = []
    for line in _ENV_PATH.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue
        match = _KEY_LINE_RE.match(stripped)
        if match is not None and match.group(1) == key:
            continue
        out_lines.append(line)
    _atomic_write(("\n".join(out_lines) + "\n") if out_lines else "")


def _atomic_write(body):
    _ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _ENV_PATH.with_suffix(_ENV_PATH.suffix + f".tmp.{os.getpid()}")
    tmp_path.write_text(body)
    os.replace(tmp_path, _ENV_PATH)
