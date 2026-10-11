"""Deterministic primitives: seeded RNG factory, canonical IDs, pseudonyms, hex IDs, timestamps."""

from __future__ import annotations

import hashlib
import random
import re
from datetime import UTC, datetime, timedelta

_SEGMENT = re.compile(r"[a-z0-9._-]+")
_LAST = re.compile(r"[a-z0-9._/=-]+")
_EPOCH0 = datetime(1970, 1, 1, tzinfo=UTC)


def rng_for(*parts: object) -> random.Random:
    """Independent seeded stream per label.

    String seeds are hashed with SHA-512 by CPython (not ``hash()``), so streams are stable
    across processes and platforms. Deriving a stream per (entity, day, trace) also keeps
    output independent of generation order.
    """
    label = ":".join(str(p) for p in parts)
    # Not cryptographic: synthetic test data only, determinism is the requirement.
    return random.Random(label)  # noqa: S311


def digest_hex(label: str, nbytes: int) -> str:
    return hashlib.blake2b(label.encode("utf-8"), digest_size=nbytes).hexdigest()


def digest_int(label: str) -> int:
    return int(digest_hex(label, 8), 16)


def pseudonym(seed: int, n: int) -> str:
    """Stable ``psn_`` principal pseudonym derived from the seed (no personal data involved)."""
    return "psn_" + digest_hex(f"sandbox-psn:{seed}:{n}", 16)


def canonical_id(cloud: str, customer: str, source: str, type_: str, ident: str) -> str:
    """PRP-01 canonical grammar ``cloud:customer:source:type:id``."""
    for seg in (customer, source, type_):
        if not _SEGMENT.fullmatch(seg):
            raise ValueError(f"bad canonical id segment: {seg!r}")
    if not _LAST.fullmatch(ident):
        raise ValueError(f"bad canonical id tail: {ident!r}")
    return f"{cloud}:{customer}:{source}:{type_}:{ident}"


def fmt_ts(ms: int) -> str:
    """Integer epoch milliseconds -> RFC 3339 UTC with millisecond precision."""
    dt = _EPOCH0 + timedelta(milliseconds=ms)
    return f"{dt:%Y-%m-%dT%H:%M:%S}.{dt.microsecond // 1000:03d}Z"


def fmt_ts_s(ms: int) -> str:
    """Whole-second RFC 3339 UTC."""
    dt = _EPOCH0 + timedelta(milliseconds=ms)
    return f"{dt:%Y-%m-%dT%H:%M:%SZ}"


def fmt_date(ms: int) -> str:
    dt = _EPOCH0 + timedelta(milliseconds=ms)
    return f"{dt:%Y-%m-%d}"


def month_bounds(ms: int) -> tuple[str, str, str]:
    """(first day, last day, YYYYMM) of the UTC month containing ``ms``."""
    dt = _EPOCH0 + timedelta(milliseconds=ms)
    first = dt.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    last = nxt - timedelta(days=1)
    return f"{first:%Y-%m-%d}", f"{last:%Y-%m-%d}", f"{first:%Y%m}"
