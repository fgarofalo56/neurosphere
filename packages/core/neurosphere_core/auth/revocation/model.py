"""Revocation list model, settings and documented defaults (PRP-06 item 5, C12).

Revocation is BOUNDED BY A TTL, NOT INSTANT. A revocation is written to the shared store at once,
but every API replica answers ``is_revoked`` from a short in-process cache, so a replica that
cached "not revoked" just before the write keeps allowing that principal until its cache entry
expires. The worst-case delay between ``revoke`` returning and a 403 on every replica is
``NS_REVOCATION_TTL_SECONDS`` (default :data:`DEFAULT_REVOCATION_TTL_SECONDS` = 60 seconds). The
replica that performs the revocation drops its own entry through the cache-invalidation hooks,
so it denies immediately. The bound assumes the store returns a committed write to every reader
(Cosmos Strong or Bounded Staleness, or Session within one region); weaker cross-region
consistency adds the replication lag on top. Pushed sessions are closed through
``PushSessionRegistry`` on the revoking replica (C13; the gateway is PRP-18).

Semantics: a principal revoked at ``revoked_at`` is denied for every token whose ``iat`` is at or
before ``revoked_at + clock_skew_seconds``. The skew allowance (default 60 s) covers a token
minted by Entra a few seconds before the revocation whose ``iat`` reads later than our clock; it
errs toward denial. Tokens issued after that point are accepted again (the principal signed in
anew; disabling the account itself is an Entra action).

Modes (PRP-39): ``issued_before`` (the default, everything above) and ``until_lifted``, which
denies EVERY token of the principal, including ones issued after the revocation, until an admin
lifts it. A blocking entry carries no per-item ``ttl`` (it never silently expires); lifting turns
it into an ``issued_before`` entry with the original ``revoked_at`` (tokens from before the block
stay refused) plus ``lifted_at``/``lifted_by``, and retention restarts. Entries stored before
PRP-39 have no ``mode`` and read as ``issued_before``.

Retention: each entry carries a Cosmos per-item ``ttl`` of ``NS_REVOCATION_RETENTION_SECONDS``
(default 48 h, minimum 28 h, the longest Entra access-token lifetime including CAE tokens). After
that every token issued before the revocation has expired and is rejected on ``exp`` anyway.

Environment (read once by :func:`load_revocation_settings`):

====================================  =======  ================================================
Variable                              Default  Meaning
====================================  =======  ================================================
``NS_REVOCATION_TTL_SECONDS``         60       Max staleness of a replica's revocation answer.
``NS_REVOCATION_RETENTION_SECONDS``   172800   Cosmos per-item TTL of a revocation entry.
``NS_REVOCATION_CLOCK_SKEW_SECONDS``  60       ``iat`` allowance on the deny side.
====================================  =======  ================================================
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = [
    "DEFAULT_CLOCK_SKEW_SECONDS",
    "DEFAULT_REVOCATION_RETENTION_SECONDS",
    "DEFAULT_REVOCATION_TTL_SECONDS",
    "MAX_REVOCATION_TTL_SECONDS",
    "MIN_REVOCATION_RETENTION_SECONDS",
    "PRINCIPAL_ID_PATTERN",
    "REASON_CODE_PATTERN",
    "REVOCATION_SCHEMA_VERSION",
    "ReasonCode",
    "RevocationEntry",
    "RevocationMode",
    "RevocationSettings",
    "is_canonical_principal_id",
    "is_reason_code",
    "lifted_entry",
    "load_revocation_settings",
    "merge_entries",
    "revocation_document_id",
]

REVOCATION_SCHEMA_VERSION: Final = "1.0.0"

#: Documented default for ``NS_REVOCATION_TTL_SECONDS``: revocation reaches every replica within
#: this many seconds. It is a bound, not instant revocation.
DEFAULT_REVOCATION_TTL_SECONDS: Final = 60
MAX_REVOCATION_TTL_SECONDS: Final = 900
#: Default Cosmos per-item TTL for a revocation entry (48 h).
DEFAULT_REVOCATION_RETENTION_SECONDS: Final = 172_800
#: 28 h: longest Entra access-token lifetime (CAE). Shorter retention could resurrect a token.
MIN_REVOCATION_RETENTION_SECONDS: Final = 100_800
DEFAULT_CLOCK_SKEW_SECONDS: Final = 60

#: Canonical principal id minted by ``PrincipalPseudonymizer`` (pseudonymous; no raw object id).
PRINCIPAL_ID_PATTERN: Final = (
    r"^(commercial|government):[a-z0-9._-]{1,128}:entra:(person|principal):p-[0-9a-f]{64}$"
)
_PRINCIPAL_ID_RE: Final = re.compile(PRINCIPAL_ID_PATTERN)

#: Machine reason code, never free text (free text could carry names or UPNs into audit).
REASON_CODE_PATTERN: Final = r"^[a-z][a-z0-9_]{0,63}$"
_REASON_CODE_RE: Final = re.compile(REASON_CODE_PATTERN)
ReasonCode = Annotated[str, StringConstraints(pattern=REASON_CODE_PATTERN)]
PrincipalId = Annotated[str, StringConstraints(pattern=PRINCIPAL_ID_PATTERN)]
#: ``issued_before``: deny tokens issued at or before ``revoked_at`` (+ skew). ``until_lifted``:
#: deny every token until an admin lifts the entry.
RevocationMode = Literal["issued_before", "until_lifted"]


def is_canonical_principal_id(value: object) -> bool:
    return isinstance(value, str) and _PRINCIPAL_ID_RE.fullmatch(value) is not None


def is_reason_code(value: object) -> bool:
    return isinstance(value, str) and _REASON_CODE_RE.fullmatch(value) is not None


def revocation_document_id(principal_id: str) -> str:
    """Cosmos id of a principal's revocation entry (the pseudonym segment; no raw ids)."""
    if not is_canonical_principal_id(principal_id):
        raise ValueError("not a canonical principal id")
    return "revocation." + principal_id.rsplit(":", 1)[-1]


class RevocationEntry(BaseModel):
    """One revoked principal. Only the latest ``revoked_at`` is kept per principal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = REVOCATION_SCHEMA_VERSION
    principal_id: PrincipalId
    revoked_at: datetime
    reason: ReasonCode
    revoked_by: PrincipalId
    mode: RevocationMode = "issued_before"
    #: Set when an ``until_lifted`` block was lifted (the entry then reads ``issued_before``).
    lifted_at: datetime | None = None
    lifted_by: PrincipalId | None = None

    @field_validator("revoked_at", "lifted_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _lift_pair(self) -> RevocationEntry:
        if (self.lifted_at is None) != (self.lifted_by is None):
            raise ValueError("lifted_at and lifted_by are set together")
        if self.lifted_at is not None and self.mode != "issued_before":
            raise ValueError("a lifted entry is no longer blocking")
        return self

    @property
    def blocking(self) -> bool:
        """True for an unlifted ``until_lifted`` entry: every token is refused."""
        return self.mode == "until_lifted"


def merge_entries(existing: RevocationEntry | None, new: RevocationEntry) -> RevocationEntry:
    """The entry a store keeps when ``new`` is written over ``existing``.

    An active block is never weakened by an ``issued_before`` write (the block is kept). A new
    block always applies and keeps the later ``revoked_at`` of the two, so lifting it later never
    re-admits a token that the existing revocation refused. Otherwise the latest ``revoked_at``
    wins (PRP-06 behaviour; equal keeps ``existing``).
    """
    if existing is None:
        return new
    if existing.blocking and not new.blocking:
        return existing
    if new.blocking and not existing.blocking:
        if existing.revoked_at > new.revoked_at:
            return new.model_copy(update={"revoked_at": existing.revoked_at})
        return new
    return existing if existing.revoked_at >= new.revoked_at else new


def lifted_entry(entry: RevocationEntry, *, lifted_at: datetime, lifted_by: str) -> RevocationEntry:
    """``entry`` after its block is lifted: ``issued_before`` from the same ``revoked_at``."""
    return RevocationEntry(
        principal_id=entry.principal_id,
        revoked_at=entry.revoked_at,
        reason=entry.reason,
        revoked_by=entry.revoked_by,
        mode="issued_before",
        lifted_at=lifted_at,
        lifted_by=lifted_by,
    )


class RevocationSettings(BaseSettings):
    """``NS_REVOCATION_*`` settings. Frozen; read once at startup."""

    model_config = SettingsConfigDict(env_prefix="NS_REVOCATION_", frozen=True, extra="forbid")

    ttl_seconds: int = Field(
        default=DEFAULT_REVOCATION_TTL_SECONDS, ge=1, le=MAX_REVOCATION_TTL_SECONDS
    )
    retention_seconds: int = Field(
        default=DEFAULT_REVOCATION_RETENTION_SECONDS,
        ge=MIN_REVOCATION_RETENTION_SECONDS,
        le=30 * 86_400,
    )
    clock_skew_seconds: int = Field(default=DEFAULT_CLOCK_SKEW_SECONDS, ge=0, le=600)


def load_revocation_settings() -> RevocationSettings:
    """Read ``NS_REVOCATION_*`` once; invalid values fail at startup, never at request time."""
    return RevocationSettings()
