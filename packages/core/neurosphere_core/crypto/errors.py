"""Envelope-encryption reason codes (PRP-102). The exception text is the reason code, nothing else.

No URL, vault host, key name, key identifier or key material is ever placed in a message, and
every raise site uses ``from None`` so no inner exception text chains through.
"""

from __future__ import annotations

from typing import Final, Literal

__all__ = [
    "CONTENT_INTEGRITY_FAILED",
    "KEY_HOST_REFUSED",
    "KEY_WRAP_UNAVAILABLE",
    "EnvelopeError",
    "EnvelopeReason",
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
