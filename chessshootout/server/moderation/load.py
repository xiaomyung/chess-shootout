import asyncio


MAX_CONCURRENT_DETECTS = 2
ADMISSION_TIMEOUT_SECONDS = 0.5
PLAYER_REFILL_CPU_SECONDS = 0.15
PLAYER_BURST_CPU_SECONDS = 0.6
ROOM_REFILL_CPU_SECONDS = 0.25
ROOM_BURST_CPU_SECONDS = 1.0
BUCKET_PRUNE_THRESHOLD = 512

PLAYER = "player"
ROOM = "room"


def _keys(room_id: str, color: str) -> tuple[tuple[str, str, str], tuple[str, str]]:
    """
    Name the two buckets one player's mark-checking is billed to: their own, and
    the one their room shares with the opponent. Every check and every charge
    touches both, which is what makes the room ceiling proof against two players
    splitting a flood between them

    :param room_id: room the marks were drawn in.
    :param color: side that drew them, white or black.
    :returns: the player bucket key and the shared room bucket key.
    """
    return ((PLAYER, room_id, color), (ROOM, room_id))


class _Bucket:
    """
    One leaky bucket of moderation debt, measured in the CPU-seconds the symbol
    filter really burned. Debt drains away as real time passes, so a bucket that
    filled up empties itself and nobody has to clear it
    """

    __slots__ = ("debt", "at")

    def __init__(self, now: float) -> None:
        """
        Open an empty bucket, settled up as of now

        :param now: server clock in seconds, monotonic.
        """
        self.debt = 0.0
        self.at = now

    def drain(self, now: float, refill: float) -> float:
        """
        Leak the debt down for the time that has passed since this bucket was
        last touched, then report what is left. Time never runs backwards here:
        a clock that appears to step back leaks nothing rather than adding debt

        :param now: server clock in seconds, monotonic.
        :param refill: CPU-seconds forgiven per second of real time.
        :returns: the debt still owed, in CPU-seconds.
        """
        self.debt = max(0.0, self.debt - max(0.0, now - self.at) * refill)
        self.at = now
        return self.debt


class ModerationLoad:
    """
    The budget that keeps screening shared board marks from ever costing the
    server more than it can spare: a cap on how many screenings run at once,
    plus leaky buckets charged in the CPU-seconds those screenings really burn,
    one per player and one shared per room. Handlers ask it before doing the
    work and bill it afterwards
    """

    def __init__(self, *, max_concurrent: int = MAX_CONCURRENT_DETECTS,
                 admission_timeout: float = ADMISSION_TIMEOUT_SECONDS,
                 player_refill: float = PLAYER_REFILL_CPU_SECONDS,
                 player_burst: float = PLAYER_BURST_CPU_SECONDS,
                 room_refill: float = ROOM_REFILL_CPU_SECONDS,
                 room_burst: float = ROOM_BURST_CPU_SECONDS) -> None:
        """
        Build the budget with its concurrency cap and its two ledgers. The
        semaphore is the hard limit on screenings in flight, since each one runs
        in a worker thread and competes with the event loop that ticks clocks
        and answers heartbeats; the buckets are the sustained-cost limit. The
        shipped defaults leave honest drawing orders of magnitude clear of the
        refills while a flood outruns them within seconds

        :param max_concurrent: screenings allowed to run at the same time.
        :param admission_timeout: seconds a message may wait for a free slot
            before it is refused instead of queued up behind the flood.
        :param player_refill: CPU-seconds forgiven per second on a player bucket.
        :param player_burst: CPU-seconds one player may owe before being cut off.
        :param room_refill: CPU-seconds forgiven per second on a room bucket.
        :param room_burst: CPU-seconds a room may owe before both sides are cut off.
        """
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.admission_timeout = admission_timeout
        self._refill = {PLAYER: player_refill, ROOM: room_refill}
        self._burst = {PLAYER: player_burst, ROOM: room_burst}
        self._buckets: dict[tuple[str, ...], _Bucket] = {}

    def over_budget(self, room_id: str, color: str, now: float) -> bool:
        """
        Say whether this player's marks may be screened at all. Asked before the
        work, so a player over budget has their sharing force-stopped rather
        than relayed unscreened. The room bucket counts as well as the player's
        own, so one side's flood also stops the opponent -- deliberate, because
        the abuse worth defending against is two players cooperating. A bucket
        nobody has charged yet counts as empty

        :param room_id: room the marks were drawn in.
        :param color: side that drew them, white or black.
        :param now: server clock in seconds, monotonic.
        :returns: True when either bucket is at its ceiling right now.
        """
        for key in _keys(room_id, color):
            bucket = self._buckets.get(key)
            if bucket is None:
                continue
            if bucket.drain(now, self._refill[key[0]]) >= self._burst[key[0]]:
                return True
        return False

    def charge(self, room_id: str, color: str, cpu_seconds: float, now: float) -> None:
        """
        Bill what one finished screening really cost to the player's bucket and
        the room's alike. Billing afterwards from a measured cost is the whole
        point of the meter: a drawing is charged what it actually burned, not
        what a message count guessed it might

        :param room_id: room the marks were drawn in.
        :param color: side that drew them, white or black.
        :param cpu_seconds: CPU time the screening measured on its own thread.
        :param now: server clock in seconds, monotonic.
        """
        for key in _keys(room_id, color):
            bucket = self._bucket(key, now)
            bucket.drain(now, self._refill[key[0]])
            bucket.debt += cpu_seconds

    def _bucket(self, key: tuple[str, ...], now: float) -> _Bucket:
        """
        Fetch one bucket, opening it on first use and sweeping the ledger once
        it has grown too large. Buckets are keyed by room, and a room lives only
        as long as one match, so the ledger tidies after itself instead of
        relying on the room manager to say when a game is gone

        :param key: bucket key from _keys, either a player or a room bucket.
        :param now: server clock in seconds, monotonic.
        :returns: the live bucket for that key.
        """
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= BUCKET_PRUNE_THRESHOLD:
                self._prune(now)
            bucket = _Bucket(now)
            self._buckets[key] = bucket
        return bucket

    def _prune(self, now: float) -> None:
        """
        Drop every bucket that has already leaked back to nothing. A bucket with
        no debt left is indistinguishable from one that never existed, while a
        bucket still in debt survives the sweep it triggered and keeps its
        holder cut off

        :param now: server clock in seconds, monotonic.
        """
        for key, bucket in list(self._buckets.items()):
            if bucket.drain(now, self._refill[key[0]]) <= 0.0:
                del self._buckets[key]
