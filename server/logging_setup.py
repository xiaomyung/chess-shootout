import logging
import os


def configure(level=None):
    level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s [room=%(room_id)s player=%(player_uuid)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.setLogRecordFactory(_make_factory(logging.getLogRecordFactory()))


def _make_factory(base):
    def factory(*args, **kwargs):
        record = base(*args, **kwargs)
        if not hasattr(record, "room_id"):
            record.room_id = "-"
        if not hasattr(record, "player_uuid"):
            record.player_uuid = "-"
        return record
    return factory


def get_logger(name="chess.server"):
    return logging.getLogger(name)
