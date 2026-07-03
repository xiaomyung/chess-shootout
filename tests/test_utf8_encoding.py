"""Windows-crash regression net for locale-codec-dependent file I/O.

`open()` / `Path.read_text` / `Path.write_text` / `*FileHandler` with no
`encoding=` bind to the process locale codec. On Linux that is UTF-8 so bugs
never surface; on Windows it is cp1251/cp1252, which cannot encode the
skill-check PGN glyphs (U+2713 checkmark, U+2717 ballot-X, U+00B7 middle dot)
or non-ASCII nicknames -> `UnicodeEncodeError` and a hard crash at game end.

Two layers:
  * `test_all_text_io_declares_encoding` -- an AST guard that fails if any
    text-I/O call in the repo omits `encoding=`. This is the only check that
    can catch a *future* regression on UTF-8 Linux CI (a behavioral test can't,
    because Linux writes UTF-8 by default even without the keyword).
  * the hostile-locale subprocess tests -- run the real production writers under
    `LC_ALL=C` (which forces the ASCII codec, reproducing the Windows failure
    mode on Linux) and prove they emit UTF-8. Each has a no-`encoding` negative
    control that must crash, so a green result is meaningful.
"""
import ast
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_DIRS = ("chessshootout", "tests", "packaging", "tools")

_FLAGGED_ATTRS = {"read_text", "write_text"}
_HANDLER_NAMES = {
    "FileHandler", "RotatingFileHandler",
    "TimedRotatingFileHandler", "WatchedFileHandler",
}

# Env that forces the stdlib to pick the ASCII locale codec for open()/argv,
# reproducing the Windows cp1252 failure mode on a Linux box.
_ASCII_LOCALE = {"LC_ALL": "C", "LANG": "C", "LC_CTYPE": "C",
                 "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"}

# The skill-check comment shape that crashed the real game, plus a nickname that
# spans cp1252-representable (Latin-1 o-umlaut) and cp1252-impossible (Cyrillic)
# code points. Kept as \u escapes so DRIVER source stays pure ASCII -- under
# LC_ALL=C the `python -c` argument itself is decoded as ASCII, so a raw glyph
# in the source bytes would fail before the driver even runs.
GLYPHS = "Steady-Aim ✗ Qxf7 · Wheel ✓"
NICK = "Björn–Щ"


def _has_encoding(call):
    return any(kw.arg == "encoding" for kw in call.keywords)


def _mode_is_binary(call):
    mode = call.args[1] if len(call.args) >= 2 else None
    for kw in call.keywords:
        if kw.arg == "mode":
            mode = kw.value
    return (isinstance(mode, ast.Constant) and isinstance(mode.value, str)
            and "b" in mode.value)


def _offenders_in(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_open = isinstance(func, ast.Name) and func.id == "open"
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        is_text = isinstance(func, ast.Attribute) and func.attr in _FLAGGED_ATTRS
        is_handler = name in _HANDLER_NAMES
        if is_open and _mode_is_binary(node):
            continue
        if (is_open or is_text or is_handler) and not _has_encoding(node):
            out.append(f"{os.path.relpath(path, REPO_ROOT)}:{node.lineno}")
    return out


def _iter_py_files():
    for base in SCAN_DIRS:
        for root, _dirs, files in os.walk(os.path.join(REPO_ROOT, base)):
            if "__pycache__" in root:
                continue
            for name in sorted(files):
                if name.endswith(".py"):
                    yield os.path.join(root, name)


def test_all_text_io_declares_encoding():
    offenders = []
    for path in _iter_py_files():
        offenders.extend(_offenders_in(path))
    assert offenders == [], (
        "text file I/O without encoding= (locale-codec-dependent, crashes on "
        "Windows cp1252): " + ", ".join(offenders)
    )


def _run_driver(driver, *args, extra_env=None):
    env = {**os.environ, **_ASCII_LOCALE}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", driver, *[str(a) for a in args]],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )


def _ascii_only(text):
    return text.encode("ascii").decode("ascii") == text


# --- PGN auto-save (the crash) ------------------------------------------------

_PGN_DRIVER = (
    "import sys\n"
    "path, enc = sys.argv[1], sys.argv[2]\n"
    "text = '[White \"\\u0429\"]\\n\\n1. Bxf7# {Steady-Aim \\u2717 "
    "Qxf7 \\u00b7 Wheel \\u2713} 1-0\\n'\n"
    "kwargs = {} if enc == 'none' else {'encoding': enc}\n"
    "with open(path, 'w', **kwargs) as f:\n"
    "    f.write(text)\n"
)


def test_pgn_style_write_uses_utf8_under_ascii_locale(tmp_path):
    path = tmp_path / "g.pgn"
    proc = _run_driver(_PGN_DRIVER, path, "utf-8")
    assert proc.returncode == 0, proc.stderr
    expected = ('[White "Щ"]\n\n1. Bxf7# {' + GLYPHS + "} 1-0\n").encode("utf-8")
    assert path.read_bytes() == expected


def test_pgn_style_write_without_encoding_crashes_under_ascii_locale(tmp_path):
    path = tmp_path / "bad.pgn"
    proc = _run_driver(_PGN_DRIVER, path, "none")
    assert proc.returncode != 0
    assert "UnicodeEncodeError" in proc.stderr


# --- crash log ----------------------------------------------------------------

_CRASH_DRIVER = (
    "import sys\n"
    "from pathlib import Path\n"
    "from chessshootout.infra.crash_log import write_crash_log\n"
    "root = Path(sys.argv[1])\n"
    "exc = ValueError('boom \\u2717 \\u00b7 \\u2713')\n"
    "p = write_crash_log(exc, ['log line \\u0429'], {'nick': 'Bj\\u00f6rn'}, root=root)\n"
    "sys.stdout.write(str(p))\n"
)


def test_crash_log_write_uses_utf8_under_ascii_locale(tmp_path):
    proc = _run_driver(_CRASH_DRIVER, tmp_path)
    assert proc.returncode == 0, proc.stderr
    written = tmp_path / "crashlogs"
    files = list(written.glob("*.txt"))
    assert files, proc.stdout
    body = files[0].read_bytes().decode("utf-8")
    assert "✗" in body and "Щ" in body and "Björn" in body


# --- .env persistence ---------------------------------------------------------

# Exercise the file writer directly (env._persist -> _atomic_write). Going through
# set_nickname would also do os.environ[...] = value, and under LC_ALL=C the POSIX
# env encodes with the ASCII fs codec and raises -- an artifact of the Linux
# simulation, not the Windows file bug (Windows env vars are natively Unicode).
_ENV_DRIVER = (
    "import sys\n"
    "from pathlib import Path\n"
    "from chessshootout.infra import env\n"
    "env._ENV_PATH = Path(sys.argv[1])\n"
    "env._persist('CHESS_NICKNAME', '\\u0429\\u00e9')\n"
)


def test_env_persist_uses_utf8_under_ascii_locale(tmp_path):
    env_path = tmp_path / ".env"
    proc = _run_driver(_ENV_DRIVER, env_path)
    assert proc.returncode == 0, proc.stderr
    assert b"CHESS_NICKNAME=" + "Щé".encode("utf-8") in env_path.read_bytes()
    leftovers = list(tmp_path.glob(".env.tmp.*"))
    assert leftovers == [], leftovers


# --- server rotating log handler ----------------------------------------------

_LOG_DRIVER = (
    "import logging, sys\n"
    "from chessshootout.server.logging_setup import attach_rotating_file_handler\n"
    "logging.getLogger().setLevel(logging.INFO)\n"
    "h = attach_rotating_file_handler(sys.argv[1], level='INFO')\n"
    "logging.getLogger('chess.server').info('matchmake nickname=%s', '\\u0429')\n"
    "h.flush()\n"
)


def test_server_log_handler_uses_utf8_under_ascii_locale(tmp_path):
    log_path = tmp_path / "server.log"
    proc = _run_driver(_LOG_DRIVER, log_path)
    assert proc.returncode == 0, proc.stderr
    assert "Щ".encode("utf-8") in log_path.read_bytes()


# --- History scan read path (the silent-vanish bug) ---------------------------

_SCAN_DRIVER = (
    "import sys\n"
    "from pathlib import Path\n"
    "from chessshootout.domain.pgn.load import scan_pgn_summaries\n"
    "d = Path(sys.argv[1])\n"
    "text = '[White \"\\u0429\"]\\n\\n1. e4 e5 {Wheel \\u2713} *\\n'\n"
    "(d / 'online-20260101-000000.pgn').write_text(text, encoding='utf-8')\n"
    "s = scan_pgn_summaries(str(d), '*.pgn')\n"
    # Emit an ASCII marker -- writing the decoded name to stdout would itself fail
    # under LC_ALL=C. "1|True" proves the read decoded the Cyrillic name as UTF-8.
    "sys.stdout.write(str(len(s)) + '|' + str(bool(s) and s[0].white == '\\u0429'))\n"
)


def test_scan_pgn_read_uses_utf8_under_ascii_locale(tmp_path):
    proc = _run_driver(_SCAN_DRIVER, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "1|True"


_BARE_READ_DRIVER = (
    "import sys\n"
    "from pathlib import Path\n"
    "p = Path(sys.argv[1])\n"
    "p.write_text('1. e4 {Wheel \\u2713} *\\n', encoding='utf-8')\n"
    "open(p).read()\n"
)


def test_bare_read_crashes_under_ascii_locale(tmp_path):
    """The negative control for the read paths: a read WITHOUT encoding= genuinely
    fails under the ASCII locale, so a passing scan/load test above is meaningful."""
    proc = _run_driver(_BARE_READ_DRIVER, tmp_path / "g.pgn")
    assert proc.returncode != 0
    assert "UnicodeDecodeError" in proc.stderr


# --- .env read-modify-write (the read at env.py:249) --------------------------

_ENV_RMW_DRIVER = (
    "import sys\n"
    "from pathlib import Path\n"
    "from chessshootout.infra import env\n"
    "p = Path(sys.argv[1])\n"
    "p.write_text('CHESS_NICKNAME=\\u0429\\u00e9\\nCHESS_LAST_MODE=online\\n', encoding='utf-8')\n"
    "env._ENV_PATH = p\n"
    "env._persist('CHESS_MASTER_VOLUME', '0.5')\n"
)


def test_env_read_modify_write_preserves_nonascii_under_ascii_locale(tmp_path):
    env_path = tmp_path / ".env"
    proc = _run_driver(_ENV_RMW_DRIVER, env_path)
    assert proc.returncode == 0, proc.stderr
    data = env_path.read_bytes()
    assert b"CHESS_NICKNAME=" + "Щé".encode("utf-8") in data
    assert b"CHESS_MASTER_VOLUME=0.5" in data
