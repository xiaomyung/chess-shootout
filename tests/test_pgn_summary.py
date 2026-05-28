from datetime import datetime

import pytest

from frontend.pgn.load import (
    PgnSummary, parse_pgn, parse_pgn_headers, summarize_pgn_file,
)


def _pgn(headers, body="1. e4 *"):
    lines = [f'[{k} "{v}"]' for k, v in headers.items()]
    return "\n".join(lines) + "\n\n" + body + "\n"


def _summary(filename, headers=None, mtime=1000.0):
    text = _pgn(headers) if headers is not None else ""
    return summarize_pgn_file(f"/games/{filename}", text, mtime, filename=filename)


# ---------- Time column ----------

def test_time_parsed_from_filename_timestamp():
    s = _summary("online-20260529-152355.pgn")
    assert s.time == "2026.05.29 15:23:55"
    assert s.sort_key == datetime(2026, 5, 29, 15, 23, 55).timestamp()


def test_time_falls_back_to_mtime_when_no_timestamp_in_name():
    mtime = 1_700_000_000.0
    s = _summary("whatever.pgn", mtime=mtime)
    assert s.time == datetime.fromtimestamp(mtime).strftime("%Y.%m.%d %H:%M:%S")
    assert s.sort_key == mtime


def test_time_falls_back_to_mtime_on_invalid_date():
    # Regex matches 8+6 digits but the date is not a real calendar date.
    mtime = 5000.0
    s = _summary("online-99999999-999999.pgn", mtime=mtime)
    assert s.time == datetime.fromtimestamp(mtime).strftime("%Y.%m.%d %H:%M:%S")
    assert s.sort_key == mtime


# ---------- Type column ----------

@pytest.mark.parametrize("filename,expected", [
    ("online-20260529-152355.pgn", "Online"),
    ("bot-20260509-174255.pgn", "Bot"),
    ("local-20260509-150435.pgn", "Local"),
    ("game-20260508-134345.pgn", "Local"),
    ("random-20260101-000000.pgn", "—"),
    ("noprefix.pgn", "—"),
])
def test_type_from_filename_prefix(filename, expected):
    assert _summary(filename).type == expected


# ---------- Time Control column ----------

@pytest.mark.parametrize("tc,expected", [
    ("600+5", "10+5"),
    ("300+2", "5+2"),
    ("60+0", "1+0"),
    ("-", "No clock"),
    ("", "No clock"),
    ("abc", "No clock"),
    ("600", "No clock"),
    ("+5", "No clock"),
    ("600+", "No clock"),
])
def test_time_control_formatting(tc, expected):
    s = _summary("local-20260101-000000.pgn", headers={"TimeControl": tc})
    assert s.time_control == expected


def test_time_control_missing_tag_is_no_clock():
    s = _summary("local-20260101-000000.pgn", headers={"White": "A"})
    assert s.time_control == "No clock"


# ---------- White / Black columns ----------

def test_white_black_from_headers():
    s = _summary("local-20260101-000000.pgn",
                 headers={"White": "Alice", "Black": "Bob"})
    assert s.white == "Alice"
    assert s.black == "Bob"


def test_white_black_default_to_question_mark():
    s = _summary("local-20260101-000000.pgn", headers={"TimeControl": "600+5"})
    assert s.white == "?"
    assert s.black == "?"


# ---------- Result column ----------

@pytest.mark.parametrize("code", ["1-0", "0-1", "1/2-1/2", "*"])
def test_result_code_preserved(code):
    s = _summary("local-20260101-000000.pgn", headers={"Result": code})
    assert s.result_code == code


def test_result_missing_defaults_to_unfinished():
    s = _summary("local-20260101-000000.pgn", headers={"White": "A"})
    assert s.result_code == "*"


# ---------- Robustness ----------

def test_summary_handles_empty_and_garbage_text():
    for text in ("", "x", "not a pgn at all"):
        s = summarize_pgn_file("/games/local-20260101-000000.pgn", text, 1000.0)
        assert isinstance(s, PgnSummary)
        assert s.white == "?"
        assert s.result_code == "*"
        assert s.time_control == "No clock"


def test_filename_defaults_to_basename_of_path():
    s = summarize_pgn_file("/games/online-20260529-152355.pgn", "", 1000.0)
    assert s.type == "Online"
    assert s.time == "2026.05.29 15:23:55"


# ---------- parse_pgn_headers ----------

def test_parse_pgn_headers_empty_on_garbage():
    assert parse_pgn_headers("x") == {}


def test_parse_pgn_headers_matches_parse_pgn_headers_field():
    text = (
        '[White "A"]\n[Black "B"]\n[Result "1-0"]\n\n'
        '1. e4 {king pawn} e5 (1...c5 {sicilian}) 2. Nf3 Nc6 1-0'
    )
    assert parse_pgn_headers(text) == parse_pgn(text).headers


def test_parse_pgn_still_parses_moves_after_refactor():
    text = '[White "A"]\n[Black "B"]\n\n1. e4 e5 2. Nf3 Nc6 *'
    parsed = parse_pgn(text)
    assert parsed.moves == ["e4", "e5", "Nf3", "Nc6"]
    assert parsed.headers["White"] == "A"
