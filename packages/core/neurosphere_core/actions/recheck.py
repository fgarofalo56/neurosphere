"""Policy-store ``PermissionRechecker`` for execution-time rechecks without a bearer token.

The executor worker (PRP-17 item 2) and the action API (item 4) recheck the MAKER's permission
when an intent is confirmed, approved and executed. The worker holds no user token, so the
recheck cannot go through ``ScopeDeriver.from_verified_claims``; it reads the principal's
CURRENT policy from the PRP-06 policy repository and evaluates it with the same rules
derivation and :func:`neurosphere_core.auth.scope.permits` apply to a domain question:

1. Revocation first: a revoked principal is denied regardless of roles. The worker has no token
   ``iat``, so the question asked is "is there ANY live revocation entry?" (``issued_at`` is the
   epoch): a principal revoked and then re-admitted stays denied for executor rechecks until the
   entry's retention lapses (PRP-06 default 48 h). That errs toward denial on purpose.
2. Policy head, then the principal document. Missing head or document = no grants (deny).
   A document for another customer/principal is ``dependency_transient`` ``upstream_invalid``.
3. Unexpired role assignments only, clipped to the principal's domain memberships and to
   domains of this deployment's cloud and the asked customer; the role's permission set comes
   from :func:`role_permissions` (the fixed NS-08 table). Resource grants never confer a domain
   permission (``permits`` ignores them for a domain-only question), so they are not consulted.

Fail closed: a policy or revocation store failure or timeout raises ``dependency_transient``
(reason ``policy_store_unavailable`` / ``revocation_unavailable``); nothing is cached, so no
answer is ever served from a stale allow after an outage. An unknown permission string denies.

The evaluation mirrors ``ScopeDeriver._build`` + ``permits`` (core auth has no public "evaluate a
policy document" helper); ``test_recheck_policy.py`` asserts parity against a derived scope.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Final

from neurosphere_core.actions.errors import POLICY_STORE_UNAVAILABLE
from neurosphere_core.auth.scope import (
    DEFAULT_STORE_TIMEOUT_SECONDS,
    NoRevocationCheck,
    Permission,
    PolicyRepository,
    PrincipalPolicy,
    RevocationChecker,
    role_permissions,
)
from neurosphere_core.cloud import CloudName
from neurosphere_core.errors import DependencyTransientError, NeuroSphereError

__all__ = ["REVOCATION_REFERENCE_INSTANT", "PolicyPermissionRechecker"]

#: ``issued_at`` used for the revocation question: every live revocation entry denies.
REVOCATION_REFERENCE_INSTANT: Final = datetime(1970, 1, 1, tzinfo=UTC)
REVOCATION_UNAVAILABLE: Final = "revocation_unavailable"

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _invalid(detail: str) -> DependencyTransientError:
    return DependencyTransientError(detail, reason="policy_document_invalid", upstream_invalid=True)


class PolicyPermissionRechecker:
    """Implements :class:`neurosphere_core.actions.PermissionRechecker` over the policy store.

    ``cloud`` is the deployment binding (the domain and principal ids must be of that cloud);
    ``revocation_checker`` is required (pass ``NoRevocationCheck()`` to opt out visibly, local
    development only). ``store_timeout_seconds`` bounds every store read.
    """

    def __init__(
        self,
        *,
        cloud: CloudName,
        policy_repository: PolicyRepository,
        revocation_checker: RevocationChecker,
        clock: Clock = _utc_now,
        store_timeout_seconds: float = DEFAULT_STORE_TIMEOUT_SECONDS,
    ) -> None:
        if not isinstance(revocation_checker, RevocationChecker):
            raise TypeError(
                "revocation_checker is required; pass a RevocationChecker or NoRevocationCheck()"
            )
        if store_timeout_seconds <= 0:
            raise ValueError("store_timeout_seconds must be positive")
        self._cloud = CloudName(cloud)
        self._repo = policy_repository
        self._revocation = revocation_checker
        self._clock = clock
        self._timeout = store_timeout_seconds

    async def check(
        self, principal_id: str, customer_id: str, domain_id: str, permission: str
    ) -> bool:
        """``True`` only when the current policy grants ``permission`` on ``domain_id``."""
        try:
            wanted = Permission(permission)
        except ValueError:
            return False
        if not (self._owned(principal_id, customer_id) and self._owned(domain_id, customer_id)):
            return False
        if domain_id.split(":")[3] != "domain":
            return False
        if await self._revoked(principal_id):
            return False
        head = await self._guarded(self._repo.get_policy_head, customer_id)
        if head is None:
            return False
        if head.customer_id != customer_id:
            raise _invalid("policy head belongs to another customer")
        policy = await self._guarded(self._repo.get_principal_policy, customer_id, principal_id)
        if policy is None:
            return False
        if policy.customer_id != customer_id or policy.principal_id != principal_id:
            raise _invalid("policy document belongs to another principal")
        return self._grants(policy, wanted, domain_id, customer_id, self._now())

    # -- internals ---------------------------------------------------------------------------

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("PolicyPermissionRechecker needs timezone-aware instants")
        return now.astimezone(UTC)

    def _owned(self, canonical_id: str, customer_id: str) -> bool:
        """Five-segment canonical id of this deployment's cloud and the asked customer."""
        parts = canonical_id.split(":")
        return len(parts) == 5 and parts[0] == self._cloud.value and parts[1] == customer_id

    def _grants(
        self,
        policy: PrincipalPolicy,
        permission: Permission,
        domain_id: str,
        customer_id: str,
        now: datetime,
    ) -> bool:
        members = {d for d in policy.domain_memberships if self._owned(d, customer_id)}
        if domain_id not in members:
            return False
        for assignment in policy.role_assignments:
            if assignment.expires_at is not None and now >= assignment.expires_at:
                continue
            if domain_id not in assignment.domain_ids:
                continue
            if permission in role_permissions(assignment.role):
                return True
        return False

    async def _revoked(self, principal_id: str) -> bool:
        if isinstance(self._revocation, NoRevocationCheck):
            return False
        try:
            async with asyncio.timeout(self._timeout):
                revoked = await self._revocation.is_revoked(
                    principal_id, REVOCATION_REFERENCE_INSTANT
                )
        except NeuroSphereError:
            raise
        except Exception as exc:
            raise DependencyTransientError(
                "revocation check unavailable", reason=REVOCATION_UNAVAILABLE
            ) from exc
        if revoked is True:
            return True
        if revoked is False:
            return False
        raise DependencyTransientError(
            "revocation check returned an invalid answer",
            reason=REVOCATION_UNAVAILABLE,
            upstream_invalid=True,
        )

    async def _guarded[T](self, call: Callable[..., Awaitable[T]], *args: str) -> T:
        try:
            async with asyncio.timeout(self._timeout):
                return await call(*args)
        except DependencyTransientError:
            raise
        except Exception as exc:
            raise DependencyTransientError(
                "policy store unavailable", reason=POLICY_STORE_UNAVAILABLE
            ) from exc
