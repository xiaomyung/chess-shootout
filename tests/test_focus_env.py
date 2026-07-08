"""CHESS_FOCUS_SHOW round-trips and persists like the other string settings."""

import os

import pytest

from chessshootout.infra import env


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("CHESS_FOCUS_SHOW", raising=False)
    yield
    monkeypatch.delenv("CHESS_FOCUS_SHOW", raising=False)


def test_default_is_line():
    assert env.get_focus_show() == "line"


@pytest.mark.parametrize("value", ["nothing", "line", "strips"])
def test_round_trip(value):
    env.set_focus_show(value)
    assert env.get_focus_show() == value
    assert os.environ["CHESS_FOCUS_SHOW"] == value


@pytest.mark.parametrize("bad", ["bogus", "", "STRIPS", "hide"])
def test_invalid_coerced_to_default_on_set(bad):
    env.set_focus_show(bad)
    assert env.get_focus_show() == "line"


def test_invalid_env_read_coerced_to_default(monkeypatch):
    monkeypatch.setenv("CHESS_FOCUS_SHOW", "bananas")
    assert env.get_focus_show() == "line"


def test_persist_writes_single_line(monkeypatch, tmp_path):
    path = tmp_path / ".env"
    monkeypatch.setattr(env, "_ENV_PATH", path)
    env.set_focus_show("line")
    env.set_focus_show("strips")
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines()
             if ln.startswith("CHESS_FOCUS_SHOW=")]
    assert lines == ["CHESS_FOCUS_SHOW=strips"]
