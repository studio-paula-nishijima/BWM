"""Bounded, transport-independent recent event-ID cache."""

from collections import OrderedDict
import time


class RecentEventIds:
    def __init__(self, max_entries: int = 1024, ttl_seconds: float = 3600, clock=time.monotonic):
        if max_entries < 1 or ttl_seconds <= 0:
            raise ValueError("max_entries and ttl_seconds must be positive")
        self._max_entries, self._ttl, self._clock = max_entries, float(ttl_seconds), clock
        self._seen: OrderedDict[str, float] = OrderedDict()

    def seen(self, event_id: str) -> bool:
        now = self._clock()
        self._purge(now)
        if event_id in self._seen:
            self._seen.move_to_end(event_id)
            return True
        self._seen[event_id] = now
        while len(self._seen) > self._max_entries:
            self._seen.popitem(last=False)
        return False

    def _purge(self, now: float) -> None:
        while self._seen and now - next(iter(self._seen.values())) >= self._ttl:
            self._seen.popitem(last=False)
