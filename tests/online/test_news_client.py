"""NewsClient: tolerant parse (missing fields skipped, unknown fields kept
through the cache round-trip), atomic cache write, once-per-run fetch gate,
failure falls back to the cached copy and stays silent, env URL override.
Every test injects a fake `fetch_news` — zero real network."""

import json
import logging

from chessshootout.online import news
from chessshootout.online.news import (
    NewsClient, format_news_date, parse_news_items,
)
from chessshootout.online.transport import TransportError


def test_parse_skips_items_missing_required_fields():
    raw = [
        {"title": "Good", "body": "Body", "date": "2026-07-14"},
        {"title": "No body", "date": "2026-07-14"},
        {"body": "No title", "date": "2026-07-14"},
        {"title": "No date", "body": "Body"},
        {"title": "", "body": "Body", "date": "2026-07-14"},
        "not a dict",
    ]
    items = parse_news_items(raw)
    assert [item["title"] for item in items] == ["Good"]


def test_parse_returns_empty_list_for_non_list_payload():
    assert parse_news_items({"title": "x"}) == []
    assert parse_news_items(None) == []


def test_parse_keeps_unknown_fields():
    raw = [{"title": "T", "body": "B", "date": "2026-07-14",
           "cta": "Read more", "id": 7}]
    items = parse_news_items(raw)
    assert items[0]["cta"] == "Read more"
    assert items[0]["id"] == 7


def test_parse_sorts_newest_first():
    raw = [
        {"title": "Old", "body": "B", "date": "2026-01-01"},
        {"title": "New", "body": "B", "date": "2026-07-14"},
        {"title": "Mid", "body": "B", "date": "2026-03-01"},
    ]
    items = parse_news_items(raw)
    assert [item["title"] for item in items] == ["New", "Mid", "Old"]


def test_parse_puts_unparseable_dates_last():
    raw = [
        {"title": "Weird", "body": "B", "date": "not-a-date"},
        {"title": "Real", "body": "B", "date": "2026-01-01"},
    ]
    items = parse_news_items(raw)
    assert [item["title"] for item in items] == ["Real", "Weird"]


def test_format_news_date_absolute_style():
    assert format_news_date("2026-07-14") == "JUL 14"


def test_format_news_date_falls_back_to_raw_on_bad_input():
    assert format_news_date("garbage") == "garbage"


def test_client_defaults_url_from_env(monkeypatch):
    monkeypatch.setenv("CHESS_NEWS_URL", "https://example.com/news.json")
    client = NewsClient(cache_path=None)
    assert client.url == "https://example.com/news.json"


def test_client_explicit_url_overrides_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CHESS_NEWS_URL", "https://example.com/news.json")
    client = NewsClient(url="https://other.example/n.json", cache_path=tmp_path / "c.json")
    assert client.url == "https://other.example/n.json"


def test_client_starts_empty_with_no_cache_file(tmp_path):
    client = NewsClient(url="unused://", cache_path=tmp_path / "missing.json")
    assert client.items() == []


def test_client_loads_existing_cache_on_construction(tmp_path):
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps(
        [{"title": "Cached", "body": "B", "date": "2026-01-01"}]), encoding="utf-8")
    client = NewsClient(url="unused://", cache_path=cache_path)
    assert [item["title"] for item in client.items()] == ["Cached"]


def test_client_ignores_a_corrupt_cache_file(tmp_path):
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("{not json", encoding="utf-8")
    client = NewsClient(url="unused://", cache_path=cache_path)
    assert client.items() == []


def test_fetch_worker_replaces_items_and_writes_cache_on_success(monkeypatch, tmp_path):
    cache_path = tmp_path / "cache.json"
    client = NewsClient(url="fake://x", cache_path=cache_path)
    monkeypatch.setattr(news, "fetch_news",
                        lambda url: [{"title": "Fresh", "body": "B", "date": "2026-07-14"}])

    client._fetch_worker()

    assert [item["title"] for item in client.items()] == ["Fresh"]
    on_disk = json.loads(cache_path.read_text(encoding="utf-8"))
    assert on_disk[0]["title"] == "Fresh"


def test_fetch_worker_round_trips_unknown_fields_through_the_cache(monkeypatch, tmp_path):
    cache_path = tmp_path / "cache.json"
    client = NewsClient(url="fake://x", cache_path=cache_path)
    monkeypatch.setattr(news, "fetch_news", lambda url: [
        {"title": "T", "body": "B", "date": "2026-07-14", "banner_color": "#ff0000"}])

    client._fetch_worker()

    reloaded = NewsClient(url="fake://x", cache_path=cache_path)
    assert reloaded.items()[0]["banner_color"] == "#ff0000"


def test_fetch_worker_keeps_cache_on_transport_failure(monkeypatch, tmp_path, caplog):
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps(
        [{"title": "Stale but fine", "body": "B", "date": "2026-01-01"}]), encoding="utf-8")
    client = NewsClient(url="fake://x", cache_path=cache_path)

    def boom(url):
        raise TransportError("connection refused")
    monkeypatch.setattr(news, "fetch_news", boom)

    with caplog.at_level(logging.DEBUG, logger="chess.client.news"):
        client._fetch_worker()

    assert [item["title"] for item in client.items()] == ["Stale but fine"]
    assert not any(r.levelno > logging.DEBUG for r in caplog.records)


def test_fetch_worker_empty_response_keeps_existing_items(monkeypatch, tmp_path):
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps(
        [{"title": "Kept", "body": "B", "date": "2026-01-01"}]), encoding="utf-8")
    client = NewsClient(url="fake://x", cache_path=cache_path)
    monkeypatch.setattr(news, "fetch_news", lambda url: [])

    client._fetch_worker()

    assert [item["title"] for item in client.items()] == ["Kept"]


def test_fetch_worker_failure_shows_no_toast_no_retry(monkeypatch, tmp_path):
    """Silent-failure contract: a failed fetch never raises, never touches a
    toast, and fetch_once only ever spawns the thread once (no automatic
    retry loop lives in the client)."""
    client = NewsClient(url="fake://x", cache_path=tmp_path / "cache.json")
    monkeypatch.setattr(news, "fetch_news",
                        lambda url: (_ for _ in ()).throw(TransportError("boom")))
    client._fetch_worker()
    assert client.items() == []


def test_fetch_once_spawns_the_thread_only_once(monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr("threading.Thread",
                        lambda *a, **k: started.append(k.get("target")) or _FakeThread())
    client = NewsClient(url="fake://x", cache_path=tmp_path / "cache.json")

    client.fetch_once()
    client.fetch_once()
    client.fetch_once()

    assert len(started) == 1
    assert started[0] == client._fetch_worker


def test_fetch_once_spawns_a_daemon_thread(monkeypatch, tmp_path):
    captured = {}

    def fake_thread(*args, **kwargs):
        captured.update(kwargs)
        return _FakeThread()
    monkeypatch.setattr("threading.Thread", fake_thread)
    client = NewsClient(url="fake://x", cache_path=tmp_path / "cache.json")

    client.fetch_once()

    assert captured.get("daemon") is True
    assert captured.get("target") == client._fetch_worker


class _FakeThread:
    def start(self):
        pass
