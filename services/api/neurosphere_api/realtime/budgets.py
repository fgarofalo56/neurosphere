"""Per-session message-rate budget: a token bucket on an injectable clock (PRP-18 item 1)."""

from collections.abc import Callable

__all__ = ["TokenBucket"]


class TokenBucket:
    """``rate`` tokens/second up to ``burst``; ``take`` is False when the bucket is empty."""

    __slots__ = ("_burst", "_clock", "_rate", "_stamp", "_tokens")

    def __init__(self, rate: float, burst: int, clock: Callable[[], float]) -> None:
        if rate <= 0 or burst < 1:
            raise ValueError("rate must be positive and burst at least 1")
        self._rate = rate
        self._burst = float(burst)
        self._clock = clock
        self._tokens = float(burst)
        self._stamp = clock()

    def take(self) -> bool:
        now = self._clock()
        elapsed = max(0.0, now - self._stamp)
        self._stamp = now
        self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    @property
    def retry_after_seconds(self) -> int:
        """Whole seconds (at least 1) until a token is available."""
        missing = max(0.0, 1.0 - self._tokens)
        return max(1, int(missing / self._rate) + 1)
