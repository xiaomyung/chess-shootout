import hashlib
import logging
import os
import re
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

from chessshootout import paths
from chessshootout.infra import countries

log = logging.getLogger("chess.env")

_KEY_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_ATOMIC_WRITE_RETRIES = 5
_ATOMIC_WRITE_BACKOFF_S = 0.03
_LINE_BREAK_CHARS = ("\r", "\n")


_DEV_SERVER_ADDR = "localhost:8000"
_PROD_SERVER_ADDR = "server.chess-shootout.com"
SERVER_MODE_OFFICIAL = "official"
SERVER_MODE_CUSTOM = "custom"
_SERVER_MODE_VALUES = (SERVER_MODE_OFFICIAL, SERVER_MODE_CUSTOM)
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
_TRUTHY_VALUES = ("1", "true", "on")

_ENV_PATH = paths.get_config_dir() / ".env"

_uuid_override = None
_nickname_override = None


def init_paths() -> None:
    """
    Point this module at the settings file for the build that is running, which
    a portable copy keeps beside the exe and an installed one keeps per user.
    The entry point calls it before anything is loaded, because the path is
    first computed at import time, before the build kind is settled
    """
    global _ENV_PATH
    _ENV_PATH = paths.get_config_dir() / ".env"


def load() -> None:
    """
    Read the stored settings into the process environment at startup, which is
    what makes every choice a player made last time take effect. Values already
    in the launching environment win, and a launch-time CHESS_SERVER_ADDR is
    honoured untouched; otherwise the active address is repaired to agree with
    the stored server mode, so the UI can never name one server and talk to
    another
    """
    if not _ENV_PATH.exists():
        return
    launch_server_addr = os.environ.get("CHESS_SERVER_ADDR")
    load_dotenv(_ENV_PATH, override=False)
    if launch_server_addr:
        return
    _infer_missing_server_mode()
    if os.environ.get("CHESS_SERVER_ADDR") != _resolved_server_addr():
        _apply_resolved_server_addr()


def _infer_missing_server_mode() -> None:
    """
    Give a settings file written before the server picker existed the mode it
    implies. Only an address that is exactly the production host becomes
    Official, so a player already pinned to the live server keeps playing there
    instead of being quietly redirected
    """
    if os.environ.get("CHESS_SERVER_MODE") in _SERVER_MODE_VALUES:
        return
    if _clean_server_addr(os.environ.get("CHESS_SERVER_ADDR")) == _PROD_SERVER_ADDR:
        os.environ["CHESS_SERVER_MODE"] = SERVER_MODE_OFFICIAL
        _persist("CHESS_SERVER_MODE", SERVER_MODE_OFFICIAL)


def set_overrides(*, client_uuid: str | None = None, nickname: str | None = None) -> None:
    """
    Apply the command-line identity overrides for this run only, never touching
    the settings file. It is how a second copy of the game plays as a different
    person while testing; a short alias is coerced into a real uuid4 first, or
    the server would reject it

    :param client_uuid: identity to play as, any string, coerced when needed;
        None leaves the stored identity in charge
    :param nickname: display name for this run, sanitised like a typed one;
        None leaves the stored name in charge
    """
    global _uuid_override, _nickname_override
    if client_uuid is not None:
        _uuid_override = _coerce_to_uuid4(client_uuid)
    if nickname is not None:
        _nickname_override = sanitize_nickname(nickname)


def _coerce_to_uuid4(value: str) -> str:
    """
    Turn any string into a real uuid4, since that is the only identity shape
    the server accepts. A genuine uuid4 passes straight through; anything else
    -- a hand-edited settings file, a debug alias such as alice -- is hashed
    into one, and the same input always yields the same identity so a test
    client keeps its games across restarts

    :param value: stored or typed identity, valid uuid4 or not
    :returns: a uuid4-shaped identity string the server will accept
    """
    try:
        parsed = uuid.UUID(value)
        if parsed.version == 4:
            return str(parsed)
    except ValueError:
        pass
    digest = hashlib.sha256(f"chess-debug-alias:{value}".encode()).hexdigest()[:32]
    digest = digest[:12] + "4" + digest[13:16] + "8" + digest[17:32]
    return f"{digest[0:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


def _default_server_addr() -> str:
    """
    Give the server a fresh install should talk to: the live server from a
    packaged build, the local development server from a source checkout, so a
    source run never queues players onto production by accident

    :returns: host, or host and port, of the default server
    """
    return _PROD_SERVER_ADDR if paths.is_frozen() else _DEV_SERVER_ADDR


def get_server_addr() -> str:
    """
    Give the address online play actually connects to right now. Everything
    that opens a socket or an HTTP request reads it from here, so the active
    address is settled in one place

    :returns: host, or host and port, of the server currently selected
    """
    return os.environ.get("CHESS_SERVER_ADDR") or _default_server_addr()


def official_server_addr() -> str:
    """
    Give the address of the official server as a fixed constant, never the
    currently active one. Official has to mean the same host for everybody, or
    a stale custom address would silently become what Official points at

    :returns: host of the official server
    """
    return _PROD_SERVER_ADDR


def _default_server_mode() -> str:
    """
    Say which side of the server picker a fresh install starts on: Official for
    a packaged build, Custom for a source checkout, matching where each kind of
    run is expected to play

    :returns: one of the two server-mode values
    """
    return SERVER_MODE_OFFICIAL if paths.is_frozen() else SERVER_MODE_CUSTOM


def get_server_mode() -> str:
    """
    Say whether the player has chosen the official server or their own address.
    The mode, not the stored address, decides where the game connects, and the
    Online options section shows it as a two-way switch

    :returns: one of the two server-mode values, defaulted when unset
    """
    return _get_enum("CHESS_SERVER_MODE", _SERVER_MODE_VALUES, _default_server_mode())


def set_server_mode(value: str) -> None:
    """
    Switch between the official server and the player's own, storing the choice
    and repointing the active address at it in one step. The address currently
    in use is first kept as the custom one, so flipping to Official and back
    does not lose the host the player had typed

    :param value: server mode to select; an unknown value falls back to the
        default for this build
    """
    _seed_custom_addr_from_active()
    _set_enum("CHESS_SERVER_MODE", value, _SERVER_MODE_VALUES, _default_server_mode())
    _apply_resolved_server_addr()


def _seed_custom_addr_from_active() -> None:
    """
    Rescue the custom address from a settings file written before the server
    picker existed, where the host lives only in the active key. Without it,
    the first switch to Official would erase that host for good and Custom
    would come back pointing at the local development server
    """
    if _clean_server_addr(os.environ.get("CHESS_CUSTOM_SERVER_ADDR")):
        return
    active = _clean_server_addr(os.environ.get("CHESS_SERVER_ADDR"))
    if active and active != _PROD_SERVER_ADDR:
        os.environ["CHESS_CUSTOM_SERVER_ADDR"] = active
        _persist("CHESS_CUSTOM_SERVER_ADDR", active)


def _clean_server_addr(value: str | None) -> str:
    """
    Accept a stored server address only when it is usable, rejecting outright
    any value carrying a control character. The setter cannot be the only gate:
    a quoted value hand-written into the settings file arrives with real
    newlines in it, and connecting to that fails deep inside a worker thread

    :param value: raw address as stored or as typed, blank or None allowed
    :returns: the trimmed address, or empty when it may not be used
    """
    value = (value or "").strip()
    return "" if _CONTROL_CHAR_RE.search(value) else value


def get_custom_server_addr() -> str:
    """
    Give the address the Custom side of the server picker should show and use.
    A stored custom host wins; failing that an address the run was launched
    with is offered, so a player pointed at a test box sees that box rather
    than a blank field

    :returns: host, or host and port, falling back to the local development
        server when nothing else is known
    """
    stored = _clean_server_addr(os.environ.get("CHESS_CUSTOM_SERVER_ADDR"))
    if stored:
        return stored
    active = _clean_server_addr(os.environ.get("CHESS_SERVER_ADDR"))
    if active and active != _PROD_SERVER_ADDR:
        return active
    return _DEV_SERVER_ADDR


def set_custom_server_addr(value: str | None) -> bool:
    """
    Store the address of the server the player runs themselves, as typed into
    the Online options. A value carrying any control character is refused
    before the process environment is touched, and the refusal is reported back
    rather than merely logged, so the options screen can say the address was
    invalid instead of quietly keeping the old one. The live connection is
    repointed only while Custom is the selected mode

    :param value: address to store; surrounding whitespace is trimmed, blank
        and None are ignored
    :returns: True when the address was accepted and stored
    """
    value = (value or "").strip()
    if not value:
        return False
    if _CONTROL_CHAR_RE.search(value):
        log.warning("refusing custom server address: value contains control characters")
        return False
    os.environ["CHESS_CUSTOM_SERVER_ADDR"] = value
    _persist("CHESS_CUSTOM_SERVER_ADDR", value)
    if get_server_mode() == SERVER_MODE_CUSTOM:
        _apply_resolved_server_addr()
    return True


def _resolved_server_addr() -> str:
    """
    Work out which address the current mode points at, the single rule that
    turns the picker into a host. Official always answers the fixed official
    host, Custom answers whatever the player last stored

    :returns: the address online play should be using
    """
    return (official_server_addr() if get_server_mode() == SERVER_MODE_OFFICIAL
            else get_custom_server_addr())


def _apply_resolved_server_addr() -> None:
    """
    Write the address the mode resolves to into the active key, in the process
    and in the settings file. This is what keeps the switch honest: after any
    change to the mode or the custom host, what the game connects to is exactly
    what the Online options claim
    """
    resolved = _resolved_server_addr()
    os.environ["CHESS_SERVER_ADDR"] = resolved
    _persist("CHESS_SERVER_ADDR", resolved)


def get_news_url() -> str:
    """
    Give the address the once-per-run news fetch reads the player-facing feed
    from, which fills the News card on the menu. Overridable for testing
    against a feed other than the published one

    :returns: URL of the news feed
    """
    return os.environ.get("CHESS_NEWS_URL") or _DEFAULT_NEWS_URL


def get_debug_hitbox() -> bool:
    """
    Say whether the developer hitbox overlay should be drawn on top of the UI.
    It is a debugging aid with no options row, set only in the environment

    :returns: True when the overlay is switched on
    """
    return (os.environ.get("CHESS_DEBUG_HITBOX") or "").strip().lower() in _TRUTHY_VALUES


def get_country() -> str:
    """
    Give the country the player picked for their profile, as the flag shown
    beside their nickname in the player strips. Anything unrecognised reads as
    no country at all, so a stale or hand-edited value cannot show a bad flag

    :returns: known two-letter country code, or empty when none is set
    """
    return countries.normalize(os.environ.get("CHESS_COUNTRY") or "")


def set_country(code: str | None) -> None:
    """
    Store the country the player chose in the country picker, or clear it. A
    code the country list does not know counts as clearing, which removes the
    setting from the file rather than storing something unusable

    :param code: two-letter country code to store; unknown, blank or None
        clears the setting instead
    """
    normalized = countries.normalize(code)
    if normalized:
        os.environ["CHESS_COUNTRY"] = normalized
        _persist("CHESS_COUNTRY", normalized)
    else:
        os.environ.pop("CHESS_COUNTRY", None)
        _persist_delete("CHESS_COUNTRY")


def sanitize_nickname(raw: str | None) -> str:
    """
    Reduce a typed name to what may safely be stored, sent and drawn: printable
    ASCII only, runs of whitespace collapsed, length capped to the same bound
    the server enforces. The hash character goes too, because an unquoted value
    containing one reads as a comment when the settings file is loaded back

    :param raw: name as typed or as found in the settings file, None allowed
    :returns: the cleaned name, possibly empty when nothing survived
    """
    kept = "".join(c for c in (raw or "") if c.isascii() and c.isprintable() and c != "#")
    return re.sub(r"\s+", " ", kept)[:_NICKNAME_MAX_LEN].strip()


def clip_nickname(raw: str | None) -> str:
    """
    Bound the length of a name without rewriting it, for names that arrived
    from the server and were normalised there already. The bound has to land
    before the name is stored, because an opponent's name is font-rendered in
    full before it is clipped to the width of the strip

    :param raw: name coming from outside this client, None allowed
    :returns: the same name, cut to the shared maximum length
    """
    return str(raw or "")[:_NICKNAME_MAX_LEN]


def _has_disallowed_nickname_chars(raw: str | None) -> bool:
    """
    Say whether a stored name contains anything outside printable ASCII, which
    is the cheap test that decides if a rewrite of the stored value is needed
    at all

    :param raw: stored name to inspect, None allowed
    :returns: True when the name would have to be cleaned before use
    """
    raw = raw or ""
    return not (raw.isascii() and raw.isprintable())


def normalize_stored_nickname() -> bool:
    """
    Repair a stored name that a previous build, or a hand edit, left with
    characters this client cannot render or send. Runs once at startup and
    rewrites both the process value and the settings file; a name that is
    already clean is left completely untouched

    :returns: True when the stored name was actually rewritten
    """
    raw = os.environ.get("CHESS_NICKNAME") or ""
    if not _has_disallowed_nickname_chars(raw):
        return False
    clean = sanitize_nickname(raw)
    os.environ["CHESS_NICKNAME"] = clean
    _persist("CHESS_NICKNAME", clean)
    return True


def get_nickname() -> str:
    """
    Give the name this player appears under -- in the profile card, in the
    player strips and in the name sent when queueing for a game. A command-line
    override wins for the run; otherwise the stored name is cleaned on the way
    out, so a bad stored value can never reach the wire

    :returns: the display name, empty when the player has not set one
    """
    if _nickname_override:
        return _nickname_override
    return sanitize_nickname(os.environ.get("CHESS_NICKNAME"))


def set_nickname(value: str | None) -> None:
    """
    Store the name the player typed into their profile. It is cleaned first,
    and a value that cleans away to nothing is ignored rather than stored as an
    empty name

    :param value: name as typed, None allowed
    """
    value = sanitize_nickname(value)
    if not value:
        return
    os.environ["CHESS_NICKNAME"] = value
    _persist("CHESS_NICKNAME", value)


def get_or_create_client_uuid() -> str:
    """
    Give the stable identity this installation plays under, minting one on
    first launch. It is what the server keys a player on, so reconnecting to a
    game in progress depends on it staying the same. A stored value that is not
    a real uuid4 -- hand-edited, or written by an older build -- is coerced
    into one and the coerced form is written back, so the coercion happens once
    and never on every launch

    :returns: the uuid4-shaped identity to send to the server
    """
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


def get_last_mode() -> str:
    """
    Give the game mode the player chose last time, so the menu opens on the
    chip they used rather than always on the first one

    :returns: the stored mode name, empty when there is nothing remembered
    """
    return os.environ.get("CHESS_LAST_MODE") or ""


def set_last_mode(mode: str) -> None:
    """
    Remember which game mode the player just started, so the next launch offers
    it again

    :param mode: mode name as the menu knows it
    """
    os.environ["CHESS_LAST_MODE"] = mode
    _persist("CHESS_LAST_MODE", mode)


def get_news_last_seen() -> str:
    """
    Give the marker of the newest news item the player has already read, which
    is what decides whether the News card shows an unread cue

    :returns: the stored marker, empty when no news has been seen yet
    """
    return os.environ.get("CHESS_NEWS_LAST_SEEN") or ""


def set_news_last_seen(value: str) -> None:
    """
    Remember that the player has read up to this news item, clearing the unread
    cue on the News card until the feed carries something newer

    :param value: marker identifying the newest item they have seen
    """
    os.environ["CHESS_NEWS_LAST_SEEN"] = value
    _persist("CHESS_NEWS_LAST_SEEN", value)


def set_data_dir(path: str | None) -> None:
    """
    Store the folder saved games are written under, as chosen in the Games
    folder row of the options. Clearing it puts the game back on the built-in
    default rather than storing an empty path

    :param path: absolute folder path to use; None or blank restores the
        default location
    """
    if path:
        os.environ["CHESS_DATA_DIR"] = path
        _persist("CHESS_DATA_DIR", path)
    else:
        os.environ.pop("CHESS_DATA_DIR", None)
        _persist_delete("CHESS_DATA_DIR")


def _get_volume(key: str, default: float) -> float:
    """
    Read one stored volume as a number the mixer can take, tolerating anything
    a settings file might hold. Unset, blank and unparseable all answer the
    default, and a stored number outside the range is pulled back into it

    :param key: settings key holding the volume
    :param default: value to answer when nothing usable is stored
    :returns: volume from 0.0 (silent) to 1.0 (full)
    """
    raw = os.environ.get(key)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(0.0, min(1.0, value))


def _set_volume(key: str, value: float) -> None:
    """
    Store one volume, clamped into range and written with a fixed number of
    decimals so the settings file does not churn on tiny slider movements

    :param key: settings key to write
    :param value: wanted volume, clamped to the 0.0 to 1.0 range
    """
    clamped = max(0.0, min(1.0, float(value)))
    os.environ[key] = f"{clamped:.3f}"
    _persist(key, f"{clamped:.3f}")


def get_master_volume() -> float:
    """
    Give the overall loudness of the game, the slider that scales every shot,
    callout and piece sound

    :returns: volume from 0.0 (silent) to 1.0 (full)
    """
    return _get_volume("CHESS_MASTER_VOLUME", _DEFAULT_MASTER_VOLUME)


def set_master_volume(value: float) -> None:
    """
    Store the overall loudness. The options screen defers this write while the
    slider is being dragged, so the file is touched once at the end

    :param value: wanted volume, clamped to the 0.0 to 1.0 range
    """
    _set_volume("CHESS_MASTER_VOLUME", value)


def get_menu_volume() -> float:
    """
    Give the loudness of the menu's own clicks and ticks, kept separate from
    the game sounds and much quieter by default

    :returns: volume from 0.0 (silent) to 1.0 (full)
    """
    return _get_volume("CHESS_MENU_VOLUME", _DEFAULT_MENU_VOLUME)


def set_menu_volume(value: float) -> None:
    """
    Store the loudness of the menu's own sounds, written the same deferred way
    as the master slider

    :param value: wanted volume, clamped to the 0.0 to 1.0 range
    """
    _set_volume("CHESS_MENU_VOLUME", value)


def _get_bool(key: str, default: bool) -> bool:
    """
    Read one on/off setting. Only the exact stored on value counts as on, so a
    stored zero reads as off rather than as a non-empty string, and unset or
    blank falls back to the default this switch ships with

    :param key: settings key holding the flag
    :param default: value to answer when nothing is stored
    :returns: True when the setting is on
    """
    raw = os.environ.get(key)
    if not raw:
        return default
    return raw == "1"


def _set_bool(key: str, value: bool) -> None:
    """
    Store one on/off setting in the single spelling the reader recognises, so
    every toggle in the options round-trips the same way

    :param key: settings key to write
    :param value: True to switch the setting on
    """
    flag = "1" if value else "0"
    os.environ[key] = flag
    _persist(key, flag)


def _get_enum(key: str, values: tuple[str, ...], default: str) -> str:
    """
    Read one setting that may only hold a value from a fixed set, such as the
    launch mode or the default time control. Anything outside the set -- an old
    spelling, a hand edit -- reads as the default rather than reaching the UI

    :param key: settings key holding the choice
    :param values: every accepted value for this setting
    :param default: value to answer when what is stored is not accepted
    :returns: the stored choice when valid, otherwise the default
    """
    value = os.environ.get(key)
    return value if value in values else default


def _set_enum(key: str, value: str, values: tuple[str, ...], default: str) -> None:
    """
    Store one setting from a fixed set, writing the default instead when the
    value offered is not one of the accepted ones, so the file can never end up
    holding a choice the reader would reject

    :param key: settings key to write
    :param value: choice to store
    :param values: every accepted value for this setting
    :param default: what to store instead when the choice is not accepted
    """
    if value not in values:
        value = default
    os.environ[key] = value
    _persist(key, value)


def get_show_fps() -> bool:
    """
    Say whether the frame rate is shown in the window title, one of the
    performance readouts in the options

    :returns: True when the frame rate should be displayed
    """
    return _get_bool("CHESS_SHOW_FPS", True)


def set_show_fps(value: bool) -> None:
    """
    Store whether the frame rate is shown in the window title

    :param value: True to display the frame rate
    """
    _set_bool("CHESS_SHOW_FPS", value)


def get_show_ping() -> bool:
    """
    Say whether the round-trip time to the server is shown in the window title
    during an online game

    :returns: True when the network latency should be displayed
    """
    return _get_bool("CHESS_SHOW_PING", True)


def set_show_ping(value: bool) -> None:
    """
    Store whether the round-trip time to the server is shown in the title

    :param value: True to display the network latency
    """
    _set_bool("CHESS_SHOW_PING", value)


def get_show_frame_stats() -> bool:
    """
    Say whether the rolling average and minimum frame rates are shown in the
    window title, the readout for spotting a slow stretch

    :returns: True when the rolling frame-rate figures should be displayed
    """
    return _get_bool("CHESS_SHOW_FRAME_STATS", False)


def set_show_frame_stats(value: bool) -> None:
    """
    Store whether the rolling average and minimum frame rates are shown

    :param value: True to display the rolling frame-rate figures
    """
    _set_bool("CHESS_SHOW_FRAME_STATS", value)


def get_show_1pct_low() -> bool:
    """
    Say whether the worst-one-percent frame rate is shown in the window title,
    the readout that exposes stutter an average hides

    :returns: True when the worst-one-percent figure should be displayed
    """
    return _get_bool("CHESS_SHOW_1PCT_LOW", False)


def set_show_1pct_low(value: bool) -> None:
    """
    Store whether the worst-one-percent frame rate is shown

    :param value: True to display the stutter figure
    """
    _set_bool("CHESS_SHOW_1PCT_LOW", value)


def get_show_frametime() -> bool:
    """
    Say whether the milliseconds of render work per frame are shown in the
    window title, the readout used when tuning the drawing itself

    :returns: True when the per-frame render time should be displayed
    """
    return _get_bool("CHESS_SHOW_FRAMETIME", False)


def set_show_frametime(value: bool) -> None:
    """
    Store whether the per-frame render time is shown

    :param value: True to display the milliseconds spent rendering
    """
    _set_bool("CHESS_SHOW_FRAMETIME", value)


def get_auto_queen() -> bool:
    """
    Say whether a promotion should take the queen automatically instead of
    asking. The skill check still fires either way -- this only skips the
    choice of piece

    :returns: True when promotions should pick the queen without asking
    """
    return _get_bool("CHESS_AUTO_QUEEN", False)


def set_auto_queen(value: bool) -> None:
    """
    Store whether promotions pick the queen without asking

    :param value: True to skip the promotion chooser
    """
    _set_bool("CHESS_AUTO_QUEEN", value)


def get_hide_opp_marks() -> bool:
    """
    Say whether the arrows and highlights an online opponent shares should be
    hidden. It is the player's own shield against unwanted drawings, and the
    server is told about it so the marks stop arriving at all

    :returns: True when the opponent's marks must not be shown
    """
    return _get_bool("CHESS_HIDE_OPP_MARKS", False)


def set_hide_opp_marks(value: bool) -> None:
    """
    Store whether an online opponent's shared marks are hidden

    :param value: True to hide the opponent's arrows and highlights
    """
    _set_bool("CHESS_HIDE_OPP_MARKS", value)


_RAIL_SECTION_KEYS = {
    "actions": "CHESS_RAIL_ACTIONS_OPEN",
    "signals": "CHESS_RAIL_SIGNALS_OPEN",
    "chat": "CHESS_RAIL_CHAT_OPEN",
}


def get_rail_section_open(section: str) -> bool:
    """
    Say whether one section of the in-game right rail was left open, so the
    rail comes back the way the player last had it rather than fully collapsed

    :param section: rail section name, one of the keys of the section table
    :returns: True when that section should start expanded
    """
    return _get_bool(_RAIL_SECTION_KEYS[section], False)


def set_rail_section_open(section: str, value: bool) -> None:
    """
    Remember that the player expanded or collapsed one section of the in-game
    right rail

    :param section: rail section name, one of the keys of the section table
    :param value: True when the section is now expanded
    """
    _set_bool(_RAIL_SECTION_KEYS[section], value)


def get_profile_hint_shown() -> bool:
    """
    Say whether the nudge towards setting up a profile has already been shown.
    It is a once-ever hint, so a returning player is not prodded again

    :returns: True when the hint has been shown before
    """
    return _get_bool("CHESS_PROFILE_HINT_SHOWN", False)


def set_profile_hint_shown() -> None:
    """
    Mark the profile hint as shown, so it never appears again. There is no way
    back on purpose -- this is a one-shot nudge, not a toggle
    """
    _set_bool("CHESS_PROFILE_HINT_SHOWN", True)


def get_default_time_control() -> str:
    """
    Give the clock length the Play view starts on, in minutes, or the untimed
    choice. It is stored as the label the time picker shows rather than a
    number, because untimed is one of the positions on that dial

    :returns: one of the accepted time-control labels
    """
    return _get_enum("CHESS_DEFAULT_TC", TIME_CONTROL_VALUES, _DEFAULT_TIME_CONTROL)


def set_default_time_control(value: str) -> None:
    """
    Store the clock length new games should start on, as picked in the options

    :param value: one of the accepted time-control labels; anything else
        stores the default instead
    """
    _set_enum("CHESS_DEFAULT_TC", value, TIME_CONTROL_VALUES, _DEFAULT_TIME_CONTROL)


def get_default_increment() -> str:
    """
    Give the number of seconds added to a player's clock after each of their
    moves that new games should start with

    :returns: one of the accepted increment labels, in seconds
    """
    return _get_enum("CHESS_DEFAULT_INCREMENT", INCREMENT_VALUES, _DEFAULT_INCREMENT)


def set_default_increment(value: str) -> None:
    """
    Store the per-move clock increment new games should start with

    :param value: one of the accepted increment labels; anything else stores
        the default instead
    """
    _set_enum("CHESS_DEFAULT_INCREMENT", value, INCREMENT_VALUES, _DEFAULT_INCREMENT)


def get_default_time_minutes() -> int | None:
    """
    Give the default clock length as a number the match setup can use, which is
    the form the time control travels in. The untimed choice has no number and
    is reported as nothing at all

    :returns: minutes on the clock, or None for an untimed game
    """
    value = get_default_time_control()
    return None if value == "∞" else int(value)


def get_default_increment_seconds() -> int:
    """
    Give the default increment as a number the match setup can use, in seconds
    added after each move

    :returns: seconds added to the mover's clock each ply
    """
    return int(get_default_increment())


def get_focus_show() -> str:
    """
    Say what stays on screen in focus mode, where everything but the board is
    collapsed away: nothing at all, the slim time line, or the full player
    strips

    :returns: one of the accepted focus-mode choices
    """
    return _get_enum("CHESS_FOCUS_SHOW", _FOCUS_SHOW_VALUES, _DEFAULT_FOCUS_SHOW)


def set_focus_show(value: str) -> None:
    """
    Store what focus mode should keep on screen beside the board

    :param value: one of the accepted focus-mode choices; anything else stores
        the default instead
    """
    _set_enum("CHESS_FOCUS_SHOW", value, _FOCUS_SHOW_VALUES, _DEFAULT_FOCUS_SHOW)


def get_launch_mode() -> str:
    """
    Say how the game window should open -- windowed, maximized or fullscreen.
    It is read once while the window is being created, so a change only shows
    on the next launch

    :returns: one of the accepted launch modes
    """
    return _get_enum("CHESS_LAUNCH_MODE", _LAUNCH_MODE_VALUES, _DEFAULT_LAUNCH_MODE)


def set_launch_mode(value: str) -> None:
    """
    Store how the window should open next time the game starts

    :param value: one of the accepted launch modes; anything else stores the
        default instead
    """
    _set_enum("CHESS_LAUNCH_MODE", value, _LAUNCH_MODE_VALUES, _DEFAULT_LAUNCH_MODE)


def _rewrite_lines(key: str, replacement: str | None) -> tuple[list[str], bool]:
    """
    Rebuild the settings file line by line, touching only the one key that is
    being written or removed. Everything the module does not own is copied
    through untouched -- comments, blank lines, other keys, and even lines that
    are not settings at all -- so a hand-edited file survives a write

    :param key: settings key to replace or drop
    :param replacement: the full line to put in its place, or None to remove
        the key entirely
    :returns: the rebuilt lines, and whether the key was found at all
    """
    existing = _ENV_PATH.read_text(encoding="utf-8") if _ENV_PATH.exists() else ""
    out_lines = []
    matched = False
    for line in existing.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue
        match = _KEY_LINE_RE.match(stripped)
        if match is not None and match.group(1) == key:
            matched = True
            if replacement is not None:
                out_lines.append(replacement)
        else:
            out_lines.append(line)
    return out_lines, matched


def _persist(key: str, value: str) -> None:
    """
    Write one setting to the settings file, in place when the key is already
    there and appended when it is not. Any value carrying a line break is
    refused and the whole write dropped: the file is one key per line, so a
    newline in a value would write a second line the next launch would honour
    as a real setting, letting one stored setting forge another. The refusal
    leaves the file exactly as it was, foreign lines included

    :param key: settings key to write
    :param value: value to store, written unquoted
    """
    value = str(value)
    if any(char in value for char in _LINE_BREAK_CHARS):
        log.warning("refusing to persist key=%s: value contains a line break", key)
        return
    out_lines, replaced = _rewrite_lines(key, f"{key}={value}")
    if not replaced:
        out_lines.append(f"{key}={value}")
    _atomic_write("\n".join(out_lines) + "\n")
    log.info("setting persisted key=%s", key)


def _persist_delete(key: str) -> None:
    """
    Remove one setting from the file entirely, which is how clearing a country
    or resetting the data folder goes back to the built-in default instead of
    storing a blank. Every other line is preserved

    :param key: settings key to remove
    """
    if not _ENV_PATH.exists():
        return
    out_lines, _ = _rewrite_lines(key, None)
    _atomic_write(("\n".join(out_lines) + "\n") if out_lines else "")
    log.info("setting persisted key=%s (deleted)", key)


def atomic_write_text(path: Path, text: str, *, retries: int = 1,
                      backoff_s: float = 0.0) -> bool:
    """
    Replace a file's contents in one step, by writing a temporary file beside
    it and moving that into place, so a reader never sees a half-written file
    and a crash mid-write cannot corrupt the old one. Shared by the settings
    file and the cached news feed. On Windows a replace can fail while another
    process holds the file, hence the retries; a write that never lands leaves
    no temporary file behind

    :param path: file to replace; missing parent directories are created
    :param text: full new contents, written as UTF-8
    :param retries: how many times to attempt the replace before giving up
    :param backoff_s: seconds to wait between attempts
    :returns: True when the new contents are in place
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + f".tmp.{os.getpid()}")
    tmp_path.write_text(text, encoding="utf-8")
    for attempt in range(retries):
        try:
            os.replace(tmp_path, path)
            return True
        except PermissionError:
            if attempt < retries - 1:
                time.sleep(backoff_s)
    try:
        tmp_path.unlink()
    except OSError:
        pass
    return False


def _atomic_write(body: str) -> None:
    """
    Put the rebuilt settings file on disk, retrying a few times when something
    else is holding it. A write that still cannot land is logged and dropped
    rather than raised, because losing one stored setting must never take down
    the game the player is in the middle of

    :param body: full new contents of the settings file
    """
    if not atomic_write_text(_ENV_PATH, body, retries=_ATOMIC_WRITE_RETRIES,
                             backoff_s=_ATOMIC_WRITE_BACKOFF_S):
        log.warning("could not persist %s (file locked); this write was dropped", _ENV_PATH)
