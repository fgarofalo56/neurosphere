"""Audit and counters for roles applied from the Entra claim role mapping (PRP-138 item 4).

:class:`ClaimGrantAuditObserver` is the deriver's ``ClaimGrantObserver``. The first request of
each token that results in a mapped role appends ONE ``identity.claim_role_applied`` record:

* on the customer control domain's chain (``domain_audit_chain_id(customer, control domain)``);
* actor pseudonym and scope hash from the derived scope (``AuditContext.from_scope``);
* subject: the control domain (the deployment the mapping administers), no state;
* ``outcome.detail``: a machine code carrying the token's issued-at and expiry (epoch seconds),
  the number of distinct domains granted, the claim kind(s), the role(s) and the mapping entry
  ids. Never a token, a claim list, a group object id or a name: the mapping entry id stands in
  for the group (the audit metadata guard refuses GUID-shaped values anyway).

"Once per token" is per process (PRP-138 clarification 13): a bounded cache keyed by principal,
token issued-at and the sorted entry ids. A key is remembered only AFTER the append succeeded, so
a failed write is retried on the next request. A missing audit repository or a failed append
raises; the deriver turns that into 503 ``audit_write_failed`` (fail closed, never an allow).

:class:`ClaimMappingStats` holds in-process counters (counts only; no ids, values or principals):
``applied`` (grants applied), ``groups_overage`` (tokens with a group overage indicator) and
``unmatched_values`` (role or group values of a bound token that no entry maps). The authz builder
installs it on ``app.state`` only when a mapping is configured; ``current_derivation`` feeds it.
"""

from __future__ import annotations

import threading
import uuid
from collections import Counter, OrderedDict
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Final

from neurosphere_core.audit import AuditContext, AuditRepository, build_after, make_subject
from neurosphere_core.audit.chains import domain_audit_chain_id
from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.scope import (
    ClaimGrant,
    ClaimGrantObserver,
    ClaimRoleMapping,
    DomainDirectory,
    customer_control_domain_id,
)
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.scope import IdentityScope

__all__ = [
    "CLAIM_MAPPING_STATS_ATTRIBUTE",
    "CLAIM_ROLE_APPLIED_OPERATION",
    "DEFAULT_SEEN_TOKENS",
    "ClaimGrantAuditObserver",
    "ClaimMappingStats",
    "claim_mapping_stats",
    "claim_role_applied_detail",
    "deriver_mapping_options",
    "install_claim_mapping_stats",
]

#: Audit operation of a record written when a mapped role is applied to a token.
CLAIM_ROLE_APPLIED_OPERATION: Final = "identity.claim_role_applied"
#: Bound of the once-per-token cache (oldest key evicted first).
DEFAULT_SEEN_TOKENS: Final = 10_000
#: ``app.state`` attribute of the :class:`ClaimMappingStats` (absent when no mapping is set).
CLAIM_MAPPING_STATS_ATTRIBUTE: Final = "claim_mapping_stats"

#: ``outcome.detail`` must match the audit guard's machine-code pattern (128 characters).
_MAX_DETAIL: Final = 128
_ENTITY_DOMAIN: Final = "domain"
_CORRELATION_PREFIX: Final = "corr-"

_SeenKey = tuple[str, int, tuple[str, ...]]


class ClaimMappingStats:
    """Thread-safe counters of the claim role mapping (counts only, low cardinality)."""

    APPLIED: Final = "applied"
    GROUPS_OVERAGE: Final = "groups_overage"
    UNMATCHED_VALUES: Final = "unmatched_values"

    def __init__(self, mapping: ClaimRoleMapping) -> None:
        self._lock = threading.Lock()
        self._counts: Counter[str] = Counter()
        self._tenant = mapping.tenant_id
        self._audience = mapping.audience
        self._roles = frozenset(e.value for e in mapping.entries if e.claim == "roles")
        self._groups = frozenset(e.value for e in mapping.entries if e.claim == "groups")

    def add(self, name: str, count: int = 1) -> None:
        if count <= 0:
            return
        with self._lock:
            self._counts[name] += count

    def observe_claims(self, claims: object) -> None:
        """Count the overage flag and the unmatched values of a token bound to the mapping.

        A token of another tenant or audience is not this mapping's concern and is not counted.
        Only the number of values is kept, never a value.
        """
        if not isinstance(claims, VerifiedClaims):
            return
        if claims.tenant_id.lower() != self._tenant or claims.audience != self._audience:
            return
        if claims.groups_overage:
            self.add(self.GROUPS_OVERAGE)
        unmatched = sum(1 for value in set(claims.roles) if value not in self._roles)
        if not claims.groups_overage:
            unmatched += sum(
                1 for value in {g.lower() for g in claims.groups} if value not in self._groups
            )
        self.add(self.UNMATCHED_VALUES, unmatched)

    def snapshot(self) -> Mapping[str, int]:
        with self._lock:
            return dict(self._counts)


def install_claim_mapping_stats(app_state: object, stats: ClaimMappingStats) -> None:
    setattr(app_state, CLAIM_MAPPING_STATS_ATTRIBUTE, stats)


def claim_mapping_stats(app_state: object) -> ClaimMappingStats | None:
    """The app's :class:`ClaimMappingStats`, or ``None`` when no mapping is configured."""
    stats = getattr(app_state, CLAIM_MAPPING_STATS_ATTRIBUTE, None)
    return stats if isinstance(stats, ClaimMappingStats) else None


def deriver_mapping_options(
    mapping: ClaimRoleMapping | None,
    *,
    domain_directory: DomainDirectory | None,
    observer: ClaimGrantObserver | None,
    env: str,
) -> dict[str, Any]:
    """The ``ScopeDeriver`` keyword arguments of the claim role mapping (PRP-138).

    Empty when the mapping is off, so the deriver keeps every default. Otherwise the mapping, the
    directory, the observer, and the local token issuer accepted for mapping only in
    ``NS_ENV=local`` (the composed validator never trusts that issuer outside local anyway).
    """
    if mapping is None:
        return {}
    return {
        "claim_mapping": mapping,
        "domain_directory": domain_directory,
        "claim_grant_observer": observer,
        "allow_dev_issuer": env == "local",
    }


def _epoch(value: datetime) -> int:
    return int(value.timestamp())


def claim_role_applied_detail(
    grants: tuple[ClaimGrant, ...], issued_at: datetime, expires_at: datetime
) -> str:
    """The record's ``outcome.detail`` machine code (fits the guard's 128-character pattern).

    ``iat=<s>:exp=<s>:domains=<n>:claims=<a.b>:roles=<a.b>:entries=<id.id>``. When the entry ids
    do not all fit, as many as fit are listed and ``:more=<k>`` counts the rest.
    """
    domains = len({d for grant in grants for d in grant.domain_ids})
    claims = ".".join(sorted({grant.claim for grant in grants}))
    roles = ".".join(sorted({grant.role.value for grant in grants}))
    head = (
        f"iat={_epoch(issued_at)}:exp={_epoch(expires_at)}:domains={domains}"
        f":claims={claims}:roles={roles}"
    )
    ids = sorted({grant.entry_id for grant in grants})
    full = f"{head}:entries={'.'.join(ids)}"
    if len(full) <= _MAX_DETAIL:
        return full
    listed: list[str] = []
    for entry_id in ids:
        candidate = [*listed, entry_id]
        more = len(ids) - len(candidate)
        text = f"{head}:entries={'.'.join(candidate)}:more={more}"
        if len(text) > _MAX_DETAIL:
            break
        listed = candidate
    if not listed:
        return f"{head}:more={len(ids)}"[:_MAX_DETAIL]
    return f"{head}:entries={'.'.join(listed)}:more={len(ids) - len(listed)}"


class ClaimGrantAuditObserver:
    """``ClaimGrantObserver`` appending one ``identity.claim_role_applied`` record per token.

    ``repository`` is resolved per call (the data builder publishes it after the authz builder
    runs); ``None`` raises. See the module docstring for the record content.
    """

    def __init__(
        self,
        repository: Callable[[], AuditRepository | None],
        *,
        stats: ClaimMappingStats | None = None,
        max_tokens: int = DEFAULT_SEEN_TOKENS,
    ) -> None:
        if max_tokens < 1:
            raise ValueError("max_tokens must be >= 1")
        self._repository = repository
        self._stats = stats
        self._max = max_tokens
        self._seen: OrderedDict[_SeenKey, None] = OrderedDict()
        self._lock = threading.Lock()

    def _key(
        self, scope: IdentityScope, grants: tuple[ClaimGrant, ...], issued_at: datetime
    ) -> _SeenKey:
        principal = scope.to_contract().principal.principal_pseudonym
        entries = tuple(sorted({grant.entry_id for grant in grants}))
        return (str(principal), _epoch(issued_at), entries)

    def _already_audited(self, key: _SeenKey) -> bool:
        with self._lock:
            if key in self._seen:
                self._seen.move_to_end(key)
                return True
            return False

    def _remember(self, key: _SeenKey) -> None:
        with self._lock:
            self._seen[key] = None
            self._seen.move_to_end(key)
            while len(self._seen) > self._max:
                self._seen.popitem(last=False)

    @property
    def remembered(self) -> int:
        with self._lock:
            return len(self._seen)

    async def on_claim_grants(
        self,
        scope: IdentityScope,
        grants: tuple[ClaimGrant, ...],
        issued_at: datetime,
        expires_at: datetime,
    ) -> None:
        if not grants:
            return
        if self._stats is not None:
            self._stats.add(ClaimMappingStats.APPLIED, len(grants))
        key = self._key(scope, grants, issued_at)
        if self._already_audited(key):
            return
        repository = self._repository()
        if repository is None:
            raise DependencyTransientError(
                "audit store is not configured", reason="audit_store_unconfigured"
            )
        control = customer_control_domain_id(str(scope.cloud), scope.customer_id)
        chain = domain_audit_chain_id(scope.customer_id, control)
        ctx = AuditContext.from_scope(
            scope,
            correlation_id=f"{_CORRELATION_PREFIX}{uuid.uuid4().hex}",
            operation=CLAIM_ROLE_APPLIED_OPERATION,
            channel="rest",
        )
        draft = build_after(
            ctx,
            make_subject(control, _ENTITY_DOMAIN),
            result="succeeded",
            verified=False,
            detail=claim_role_applied_detail(grants, issued_at, expires_at),
        )
        await repository.append(chain, draft)
        self._remember(key)
