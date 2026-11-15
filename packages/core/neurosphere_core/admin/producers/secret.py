"""Producer secret generation (PRP-41): show-once value plus the digest that is stored.

The secret is ``secrets.token_urlsafe(32)`` (256 bits, 43 URL-safe characters, no ``.`` so it
splits cleanly off ``<producer_id>.<secret>``). Only :func:`secret_digest` of it is ever stored,
logged or audited. :class:`IssuedSecret` redacts itself in ``repr``/``str`` so an exception
message or a log line that formats it cannot leak the value.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

__all__ = ["SECRET_BYTES", "IssuedSecret", "issue_secret", "secret_digest"]

#: Entropy of a generated secret in bytes (256 bits).
SECRET_BYTES: Final = 32
_REDACTED: Final = "IssuedSecret(<redacted>)"


def secret_digest(secret: str) -> str:
    """Lowercase hex SHA-256 of ``secret`` (same function as the ingest edge's ``hash_secret``)."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True, repr=False)
class IssuedSecret:
    """A freshly generated secret and its digest. The value exists only in this object."""

    secret: str
    sha256: str

    def __repr__(self) -> str:
        return _REDACTED

    def __str__(self) -> str:
        return _REDACTED


def issue_secret(token_factory: Callable[[int], str] = secrets.token_urlsafe) -> IssuedSecret:
    """Generate a producer secret; ``token_factory`` is a test seam, production never passes it."""
    secret = token_factory(SECRET_BYTES)
    return IssuedSecret(secret=secret, sha256=secret_digest(secret))
