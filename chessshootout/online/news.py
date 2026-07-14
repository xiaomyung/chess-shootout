import json
import logging
import os
import threading
from datetime import datetime

from chessshootout import paths
from chessshootout.infra import env
from chessshootout.online.transport import TransportError, fetch_news


log = logging.getLogger("chess.client.news")

CACHE_FILENAME = "news_cache.json"

NEWS_MAX_ITEMS = 20


def _cache_path():
    return paths.get_config_dir() / CACHE_FILENAME


def _valid_str(value):
    return isinstance(value, str) and value.strip() != ""


def _coerce_item(raw):
    if not isinstance(raw, dict):
        return None
    if not (_valid_str(raw.get("title")) and _valid_str(raw.get("body"))
            and _valid_str(raw.get("date"))):
        return None
    return dict(raw)


def _sort_key(item):
    try:
        return datetime.strptime(item["date"], "%Y-%m-%d")
    except ValueError:
        return datetime.min


def parse_news_items(raw):
    if not isinstance(raw, list):
        return []
    items = [item for item in (_coerce_item(entry) for entry in raw) if item is not None]
    items.sort(key=_sort_key, reverse=True)
    return items[:NEWS_MAX_ITEMS]


def format_news_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %d").upper()
    except ValueError:
        return date_str


def _atomic_write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + f".tmp.{os.getpid()}")
    try:
        tmp_path.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp_path, path)
    except OSError:
        log.debug("news cache write failed", exc_info=True)
        try:
            tmp_path.unlink()
        except OSError:
            pass


def _load_cache(path):
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return parse_news_items(raw)


class NewsClient:

    def __init__(self, url=None, cache_path=None):
        self.url = url or env.get_news_url()
        self._cache_path = cache_path or _cache_path()
        self._lock = threading.Lock()
        self._items = _load_cache(self._cache_path)
        self._generation = 0
        self._fetched = False

    def items(self):
        with self._lock:
            return list(self._items)

    def generation(self):
        with self._lock:
            return self._generation

    def fetch_once(self):
        with self._lock:
            if self._fetched:
                return
            self._fetched = True
        thread = threading.Thread(target=self._fetch_worker, daemon=True)
        thread.start()

    def _fetch_worker(self):
        try:
            raw = fetch_news(self.url)
        except TransportError as exc:
            log.debug("news fetch failed url=%s: %s", self.url, exc)
            return
        items = parse_news_items(raw)
        if not items:
            log.debug("news fetch returned no usable items url=%s", self.url)
            return
        with self._lock:
            self._items = items
            self._generation += 1
        _atomic_write_json(self._cache_path, items)
