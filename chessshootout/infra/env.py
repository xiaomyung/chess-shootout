import hashlib
import logging
import os
import re
import time
import uuid

from dotenv import load_dotenv

from chessshootout import paths
from chessshootout.infra import countries

log = logging.getLogger("chess.env")

_KEY_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
_ATOMIC_WRITE_RETRIES = 5
_ATOMIC_WRITE_BACKOFF_S = 0.03


_DEV_SERVER_ADDR = "localhost:8000"
_PROD_SERVER_ADDR = "server.chess-shootout.com"
_DEFAULT_NEWS_URL = "https://xiaomyung.github.io/chess-shootout/news.json"
_DEFAULT_MASTER_VOLUME = 0.70
_DEFAULT_MENU_VOLUME = 0.10
_DEFAULT_TIME_CONTROL = "10"
_DEFAULT_INCREMENT = "5"
_NICKNAME_MAX_LEN = 20
TIME_CONTROL_VALUES = ("1", "3", "5", "10", "15", "30", "∞")
INCREMENT_VALUES = ("0", "2", "5", "10", "15")
_FOCUS_SHOW_VALUES = ("nothing", "line", "strips")
_DEFAULT_FOCUS_SHOW = "line"
_LAUNCH_MODE_VALUES = ("windowed", "maximized", "fullscreen")
_DEFAULT_LAUNCH_MODE = "windowed"

_ENV_PATH = paths.get_config_dir() / ".env"

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
        _nickname_override = sanitize_nickname(nickname)


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


def _default_server_addr():
    return _PROD_SERVER_ADDR if paths.is_frozen() else _DEV_SERVER_ADDR


def get_server_addr():
    return os.environ.get("CHESS_SERVER_ADDR") or _default_server_addr()


def set_server_addr(value):
    value = (value or "").strip()
    if not value:
        return
    os.environ["CHESS_SERVER_ADDR"] = value
    _persist("CHESS_SERVER_ADDR", value)


def get_news_url():
    return os.environ.get("CHESS_NEWS_URL") or _DEFAULT_NEWS_URL


def get_country():
    return countries.normalize(os.environ.get("CHESS_COUNTRY") or "")


def set_country(code):
    normalized = countries.normalize(code)
    if normalized:
        os.environ["CHESS_COUNTRY"] = normalized
        _persist("CHESS_COUNTRY", normalized)
    else:
        os.environ.pop("CHESS_COUNTRY", None)
        _persist_delete("CHESS_COUNTRY")


def sanitize_nickname(raw):
    kept = "".join(c for c in (raw or "") if c.isascii() and c.isprintable() and c != "#")
    return re.sub(r"\s+", " ", kept)[:_NICKNAME_MAX_LEN].strip()


def _has_disallowed_nickname_chars(raw):
    raw = raw or ""
    return not (raw.isascii() and raw.isprintable())


def normalize_stored_nickname():
    raw = os.environ.get("CHESS_NICKNAME") or ""
    if not _has_disallowed_nickname_chars(raw):
        return False
    clean = sanitize_nickname(raw)
    os.environ["CHESS_NICKNAME"] = clean
    _persist("CHESS_NICKNAME", clean)
    return True


def get_nickname():
    if _nickname_override:
        return _nickname_override
    return sanitize_nickname(os.environ.get("CHESS_NICKNAME"))


def set_nickname(value):
    value = sanitize_nickname(value)
    if not value:
        return
    os.environ["CHESS_NICKNAME"] = value
    _persist("CHESS_NICKNAME", value)


def get_or_create_client_uuid():
    if _uuid_override:
        return _uuid_override
    existing = os.environ.get("CHESS_CLIENT_UUID")
    if existing:
        coerced = _coerce_to_uuid4(existing)
        if coerced != existing:
            os.environ["CHESS_CLIENT_UUID"] = coerced
            _persist("CHESS_CLIENT_UUID", coerced)
        return coerced
    fresh = str(uuid.uuid4())
    os.environ["CHESS_CLIENT_UUID"] = fresh
    _persist("CHESS_CLIENT_UUID", fresh)
    return fresh


def get_last_mode():
    return os.environ.get("CHESS_LAST_MODE") or ""


def set_last_mode(mode):
    os.environ["CHESS_LAST_MODE"] = mode
    _persist("CHESS_LAST_MODE", mode)


def set_data_dir(path):
    if path:
        os.environ["CHESS_DATA_DIR"] = path
        _persist("CHESS_DATA_DIR", path)
    else:
        os.environ.pop("CHESS_DATA_DIR", None)
        _persist_delete("CHESS_DATA_DIR")


def _get_volume(key, default):
    raw = os.environ.get(key)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(0.0, min(1.0, value))


def _set_volume(key, value):
    clamped = max(0.0, min(1.0, float(value)))
    os.environ[key] = f"{clamped:.3f}"
    _persist(key, f"{clamped:.3f}")


def get_master_volume():
    return _get_volume("CHESS_MASTER_VOLUME", _DEFAULT_MASTER_VOLUME)


def set_master_volume(value):
    _set_volume("CHESS_MASTER_VOLUME", value)


def get_menu_volume():
    return _get_volume("CHESS_MENU_VOLUME", _DEFAULT_MENU_VOLUME)


def set_menu_volume(value):
    _set_volume("CHESS_MENU_VOLUME", value)


def _get_bool(key, default):
    raw = os.environ.get(key)
    if not raw:
        return default
    return raw == "1"


def _set_bool(key, value):
    flag = "1" if value else "0"
    os.environ[key] = flag
    _persist(key, flag)


def get_show_fps():
    return _get_bool("CHESS_SHOW_FPS", True)


def set_show_fps(value):
    _set_bool("CHESS_SHOW_FPS", value)


def get_show_ping():
    return _get_bool("CHESS_SHOW_PING", True)


def set_show_ping(value):
    _set_bool("CHESS_SHOW_PING", value)


def get_show_frame_stats():
    return _get_bool("CHESS_SHOW_FRAME_STATS", False)


def set_show_frame_stats(value):
    _set_bool("CHESS_SHOW_FRAME_STATS", value)


def get_show_1pct_low():
    return _get_bool("CHESS_SHOW_1PCT_LOW", False)


def set_show_1pct_low(value):
    _set_bool("CHESS_SHOW_1PCT_LOW", value)


def get_show_frametime():
    return _get_bool("CHESS_SHOW_FRAMETIME", False)


def set_show_frametime(value):
    _set_bool("CHESS_SHOW_FRAMETIME", value)


def get_profile_hint_shown():
    return _get_bool("CHESS_PROFILE_HINT_SHOWN", False)


def set_profile_hint_shown():
    _set_bool("CHESS_PROFILE_HINT_SHOWN", True)


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


def get_focus_show():
    value = os.environ.get("CHESS_FOCUS_SHOW")
    if value in _FOCUS_SHOW_VALUES:
        return value
    return _DEFAULT_FOCUS_SHOW


def set_focus_show(value):
    if value not in _FOCUS_SHOW_VALUES:
        value = _DEFAULT_FOCUS_SHOW
    os.environ["CHESS_FOCUS_SHOW"] = value
    _persist("CHESS_FOCUS_SHOW", value)


def get_launch_mode():
    value = os.environ.get("CHESS_LAUNCH_MODE")
    if value in _LAUNCH_MODE_VALUES:
        return value
    return _DEFAULT_LAUNCH_MODE


def set_launch_mode(value):
    if value not in _LAUNCH_MODE_VALUES:
        value = _DEFAULT_LAUNCH_MODE
    os.environ["CHESS_LAUNCH_MODE"] = value
    _persist("CHESS_LAUNCH_MODE", value)


def _persist(key, value):
    existing = _ENV_PATH.read_text(encoding="utf-8") if _ENV_PATH.exists() else ""
    out_lines = []
    replaced = False
    for line in existing.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue
        match = _KEY_LINE_RE.match(stripped)
        if match is not None and match.group(1) == key:
            out_lines.append(f"{key}={value}")
            replaced = True
        else:
            out_lines.append(line)
    if not replaced:
        out_lines.append(f"{key}={value}")
    body = "\n".join(out_lines) + "\n"
    _atomic_write(body)
    log.info("setting persisted key=%s", key)


def _persist_delete(key):
    if not _ENV_PATH.exists():
        return
    out_lines = []
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue
        match = _KEY_LINE_RE.match(stripped)
        if match is not None and match.group(1) == key:
            continue
        out_lines.append(line)
    _atomic_write(("\n".join(out_lines) + "\n") if out_lines else "")
    log.info("setting persisted key=%s (deleted)", key)


def _atomic_write(body):
    _ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _ENV_PATH.with_suffix(_ENV_PATH.suffix + f".tmp.{os.getpid()}")
    tmp_path.write_text(body, encoding="utf-8")
    for attempt in range(_ATOMIC_WRITE_RETRIES):
        try:
            os.replace(tmp_path, _ENV_PATH)
            return
        except PermissionError:
            if attempt < _ATOMIC_WRITE_RETRIES - 1:
                time.sleep(_ATOMIC_WRITE_BACKOFF_S)
    log.warning("could not persist %s (file locked); this write was dropped", _ENV_PATH)
    try:
        tmp_path.unlink()
    except OSError:
        pass
