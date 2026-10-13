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

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
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
    "RevocationSettings",
    "is_canonical_principal_id",
    "is_reason_code",
    "load_revocation_settings",
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

    @field_validator("revoked_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("revoked_at must be timezone-aware")
        return value


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
