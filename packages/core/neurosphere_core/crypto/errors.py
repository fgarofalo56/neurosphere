"""Envelope-encryption reason codes (PRP-102). The exception text is the reason code, nothing else.

No URL, vault host, key name, key identifier or key material is ever placed in a message. Raise
sites use ``from None``, and the public entry points (``seal``, ``open_envelope``, the Key Vault
wrapper) re-raise through :func:`without_context`, so the error leaves with no chain at all.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Final, Literal

__all__ = [
    "CONTENT_INTEGRITY_FAILED",
    "KEY_HOST_REFUSED",
    "KEY_WRAP_UNAVAILABLE",
    "EnvelopeError",
    "EnvelopeReason",
    "without_context",
]


KEY_WRAP_UNAVAILABLE: Final = "key_wrap_unavailable"
CONTENT_INTEGRITY_FAILED: Final = "content_integrity_failed"
KEY_HOST_REFUSED: Final = "key_host_refused"

EnvelopeReason = Literal["key_wrap_unavailable", "content_integrity_failed", "key_host_refused"]


class EnvelopeError(Exception):
    """Sealing, opening or key wrapping failed. ``reason`` is a machine code; nothing else."""

    def __init__(self, reason: EnvelopeReason) -> None:
        super().__init__(reason)
        self.reason: EnvelopeReason = reason

    def __str__(self) -> str:
        return self.reason


async def without_context[T](operation: Awaitable[T]) -> T:
    """Await ``operation``; re-raise any :class:`EnvelopeError` with no exception chain.

    ``raise ... from None`` hides the inner exception from tracebacks but keeps it on
    ``__context__``, where error reporters that walk the chain could read an httpx URL. The
    fresh error is raised after the ``except`` block has ended, so it carries no context.
    """
    try:
        return await operation
    except EnvelopeError as exc:
        reason = exc.reason
    raise EnvelopeError(reason)
