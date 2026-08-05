import asyncio


MAX_CONCURRENT_DETECTS = 2
PLAYER_REFILL_CPU_SECONDS = 0.15
PLAYER_BURST_CPU_SECONDS = 0.6
ROOM_REFILL_CPU_SECONDS = 0.25
ROOM_BURST_CPU_SECONDS = 1.0
BUCKET_PRUNE_THRESHOLD = 512

PLAYER = "player"
ROOM = "room"


def _keys(room_id, color):
    return ((PLAYER, room_id, color), (ROOM, room_id))


class _Bucket:

    __slots__ = ("debt", "at")

    def __init__(self, now):
        self.debt = 0.0
        self.at = now

    def drain(self, now, refill):
        self.debt = max(0.0, self.debt - max(0.0, now - self.at) * refill)
        self.at = now
        return self.debt


class ModerationLoad:

    def __init__(self, *, max_concurrent=MAX_CONCURRENT_DETECTS,
                 player_refill=PLAYER_REFILL_CPU_SECONDS,
                 player_burst=PLAYER_BURST_CPU_SECONDS,
                 room_refill=ROOM_REFILL_CPU_SECONDS,
                 room_burst=ROOM_BURST_CPU_SECONDS):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self._refill = {PLAYER: player_refill, ROOM: room_refill}
        self._burst = {PLAYER: player_burst, ROOM: room_burst}
        self._buckets = {}

    def over_budget(self, room_id, color, now):
        for key in _keys(room_id, color):
            bucket = self._buckets.get(key)
            if bucket is None:
                continue
            if bucket.drain(now, self._refill[key[0]]) >= self._burst[key[0]]:
                return True
        return False

    def charge(self, room_id, color, cpu_seconds, now):
        for key in _keys(room_id, color):
            bucket = self._bucket(key, now)
            bucket.drain(now, self._refill[key[0]])
            bucket.debt += cpu_seconds

    def _bucket(self, key, now):
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= BUCKET_PRUNE_THRESHOLD:
                self._prune(now)
            bucket = _Bucket(now)
            self._buckets[key] = bucket
        return bucket

    def _prune(self, now):
        for key, bucket in list(self._buckets.items()):
            if bucket.drain(now, self._refill[key[0]]) <= 0.0:
                del self._buckets[key]
