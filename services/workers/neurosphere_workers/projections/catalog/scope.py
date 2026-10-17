"""The projection worker's ``IdentityScope`` (PRP-10 item 3, PRP-06 derivation).

The worker has no end user. Its scope still comes from the one derivation path every caller uses:
a workload principal (a managed identity or service principal, ``identity_type == "app"``) presents
``VerifiedClaims`` and ``ScopeDeriver.from_verified_claims`` computes the scope from the policy
store. Nothing here builds a scope by hand or reaches for the private contract-to-scope
constructor (a test asserts it), so the worker holds exactly the domains the policy store grants
its principal (never a bypass) and loses them when the policy, a role expiry or a revocation
says so.

Where the claims come from (the validated token of the worker's managed identity) is the
deployment's concern: ``ClaimsSource`` is the seam.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Final, Protocol, runtime_checkable

from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.scope import ScopeDeriver
from neurosphere_core.catalog.rules import parse_timestamp
from neurosphere_core.errors import ForbiddenError
from neurosphere_core.scope import IdentityScope

REFRESH_SKEW_SECONDS: Final = 30.0
"""A cached scope is re-derived this long before it expires."""


@runtime_checkable
class ScopeProvider(Protocol):
    async def get(self) -> IdentityScope:
        """A currently valid scope for the worker. Raises when none can be derived (deny)."""
        raise NotImplementedError


@runtime_checkable
class ClaimsSource(Protocol):
    async def claims(self) -> VerifiedClaims:
        """Validator-built claims of the worker's own workload identity."""
        raise NotImplementedError


class WorkloadScopeProvider:
    """Derives, caches and refreshes the worker's scope through ``ScopeDeriver``."""

    def __init__(
        self,
        deriver: ScopeDeriver,
        claims_source: ClaimsSource,
        *,
        clock: Callable[[], float] = time.time,
        refresh_skew_seconds: float = REFRESH_SKEW_SECONDS,
    ) -> None:
        self._deriver = deriver
        self._claims_source = claims_source
        self._clock = clock
        self._skew = refresh_skew_seconds
        self._scope: IdentityScope | None = None
        self._expires_at: float = 0.0

    async def get(self) -> IdentityScope:
        if self._scope is not None and self._clock() < self._expires_at - self._skew:
            return self._scope
        claims = await self._claims_source.claims()
        if claims.identity_type != "app":
            # A user token must never run the projection: its scope is a person's, not the worker's.
            raise ForbiddenError("the projection worker requires a workload identity")
        scope = await self._deriver.from_verified_claims(claims)
        expiry = scope.to_contract().expires_at
        self._scope = scope
        self._expires_at = parse_timestamp(expiry.root).timestamp() if expiry is not None else 0.0
        return scope
