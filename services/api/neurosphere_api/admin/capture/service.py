"""Authorization and reads behind the capture admin routes (PRP-103 item 5).

Who may read:

* ``?domain_id=<id>``: ``config.manage`` on that domain (or customer-level ``config.manage``);
  anything else is 403 ``target_out_of_scope``, recorded as a denied attempt.
* no ``domain_id`` (every domain of the customer): customer-level ``config.manage`` on the
  customer control domain; a domain-only admin gets 403 ``customer_scope_required``, recorded.
* one policy by id: ``config.manage`` somewhere (the inventory marker), then on the policy's own
  domain (or customer-wide). A policy the caller may not read answers exactly like an unknown
  one (404 ``capture_policy_not_found``, the denial recorded), so its existence does not leak.

The customer always comes from the server-derived scope, never from the request.

Data comes from ``app.state`` as the ``interactions`` builder left it (PRP-103 item 4), read
with ``getattr(..., None)`` because the attributes are absent when that builder is not composed:
``interaction_capture`` (``EdgeCapture``), ``interaction_capture_stats`` (its counters),
``interaction_capture_policy_store`` and ``interaction_capture_off_reason``. No store means an
empty or off view with reason ``capture_not_configured``, never a 500. Nothing here writes: a
change is a ``capture_policy_change`` action (PRP-108).

No ``from __future__ import annotations``: FastAPI inspects the dependency signatures below.
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Final

from fastapi import Depends, Query, Request
from neurosphere_core.auth.scope import Permission, permits, permits_customer_wide
from neurosphere_core.errors import ForbiddenError, NotFoundError
from neurosphere_core.interactions import CapturePolicy, CapturePolicyStore, StoredCapturePolicy
from neurosphere_core.scope import IdentityScope

from neurosphere_api.admin.capture.models import (
    NOT_CONFIGURED,
    CapturePolicyView,
    CaptureStatusView,
    PolicyStateCounts,
    counters_view,
    policy_view,
)
from neurosphere_api.audit.access import CUSTOMER_SCOPE_REQUIRED, record_denial
from neurosphere_api.authz import AuthzState, get_authz_state, require

__all__ = [
    "DOMAIN_ID_PATTERN",
    "POLICY_ID_PATTERN",
    "SCAN_LIMIT",
    "STATE_EDGE",
    "STATE_OFF_REASON",
    "STATE_POLICY_STORE",
    "STATE_STATS",
    "CaptureReadScope",
    "capture_policy_reader",
    "capture_read_scope",
    "get_policy",
    "list_policies",
    "read_status",
]

#: ``app.state`` attribute names written by ``runtime/builders/interactions.py``.
STATE_EDGE: Final = "interaction_capture"
STATE_STATS: Final = "interaction_capture_stats"
STATE_POLICY_STORE: Final = "interaction_capture_policy_store"
STATE_OFF_REASON: Final = "interaction_capture_off_reason"

#: Policies read from the store per request (the store's own upper bound); a domain filter is
#: applied after the read, so a full read means the view may be truncated.
SCAN_LIMIT: Final = 1000
DOMAIN_ID_PATTERN: Final = (
    r"^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:domain:[a-z0-9._/=-]+$"
)
POLICY_ID_PATTERN: Final = r"^[a-z0-9][a-z0-9._-]{0,63}$"
_PERMISSION: Final = Permission.CONFIG_MANAGE
_NOT_FOUND: Final = "capture_policy_not_found"

_config_manage_somewhere = require(_PERMISSION)

DomainFilter = Annotated[
    str | None,
    Query(
        max_length=256,
        pattern=DOMAIN_ID_PATTERN,
        description="Domain id; omit for every domain (needs customer-level config.manage).",
    ),
]


@dataclass(frozen=True, slots=True)
class CaptureReadScope:
    """The caller's scope, the domain filter (``None`` = all) and whether it is customer-wide."""

    scope: IdentityScope
    domain_id: str | None
    customer_wide: bool
    now: datetime

    @property
    def customer_id(self) -> str:
        return self.scope.customer_id

    def may_read(self, domain_id: str) -> bool:
        if self.customer_wide:
            return True
        return permits(self.scope, _PERMISSION, now=self.now, domain_id=domain_id) is True


def _now(state: AuthzState) -> datetime:
    return datetime.fromtimestamp(state.clock(), UTC)


async def capture_read_scope(
    request: Request,
    scope: Annotated[IdentityScope, Depends(_config_manage_somewhere)],
    state: Annotated[AuthzState, Depends(get_authz_state)],
    domain_id: DomainFilter = None,
) -> CaptureReadScope:
    """Dependency of the list and status routes (see the module docstring for the rules)."""
    now = _now(state)
    customer_wide = permits_customer_wide(scope, _PERMISSION, now=now) is True
    read = CaptureReadScope(scope, domain_id, customer_wide, now)
    if domain_id is None:
        if not customer_wide:
            await record_denial(state, request, scope, _PERMISSION, None, CUSTOMER_SCOPE_REQUIRED)
            raise ForbiddenError(
                "every domain needs customer-level config.manage; name a domain_id",
                reason=CUSTOMER_SCOPE_REQUIRED,
            )
        return read
    if not read.may_read(domain_id):
        await record_denial(state, request, scope, _PERMISSION, domain_id, "target_out_of_scope")
        raise ForbiddenError("insufficient scope for this operation", reason="target_out_of_scope")
    return read


async def capture_policy_reader(
    scope: Annotated[IdentityScope, Depends(_config_manage_somewhere)],
    state: Annotated[AuthzState, Depends(get_authz_state)],
) -> CaptureReadScope:
    """Dependency of the detail route: the per-domain check runs once the policy is read."""
    now = _now(state)
    return CaptureReadScope(
        scope, None, permits_customer_wide(scope, _PERMISSION, now=now) is True, now
    )


def _policy_store(request: Request) -> CapturePolicyStore | None:
    store = getattr(request.app.state, STATE_POLICY_STORE, None)
    return store if isinstance(store, CapturePolicyStore) else None


async def _visible(
    request: Request, read: CaptureReadScope
) -> tuple[list[CapturePolicy], bool, bool]:
    """``(policies, truncated, configured)`` the caller may read, ordered by policy id."""
    store = _policy_store(request)
    if store is None:
        return [], False, False
    stored: list[StoredCapturePolicy] = await store.list(
        customer_id=read.customer_id, limit=SCAN_LIMIT
    )
    truncated = len(stored) >= SCAN_LIMIT
    policies = [
        s.policy
        for s in stored
        if s.policy.customer == read.customer_id
        and (read.domain_id is None or s.policy.domain == read.domain_id)
        and read.may_read(s.policy.domain)
    ]
    policies.sort(key=lambda p: p.policy_id)
    return policies, truncated, True


async def list_policies(
    request: Request, read: CaptureReadScope, limit: int
) -> tuple[list[CapturePolicyView], bool, bool]:
    """``(views, truncated, configured)``: at most ``limit`` policies the caller may read."""
    policies, truncated, configured = await _visible(request, read)
    return (
        [policy_view(p) for p in policies[:limit]],
        truncated or len(policies) > limit,
        configured,
    )


async def get_policy(
    request: Request,
    state: AuthzState,
    read: CaptureReadScope,
    policy_id: str,
) -> CapturePolicyView:
    """One policy of the caller's customer; 404 when unknown, unconfigured or not readable."""
    store = _policy_store(request)
    if store is None:
        raise NotFoundError("capture is not configured", reason=NOT_CONFIGURED)
    stored = await store.get(policy_id, customer_id=read.customer_id)
    if stored is None or stored.policy.customer != read.customer_id:
        raise NotFoundError("capture policy not found", reason=_NOT_FOUND)
    if not read.may_read(stored.policy.domain):
        await record_denial(
            state, request, read.scope, _PERMISSION, stored.policy.domain, "target_out_of_scope"
        )
        raise NotFoundError("capture policy not found", reason=_NOT_FOUND)
    return policy_view(stored.policy)


def _off_reason(app_state: Any) -> tuple[str | None, bool]:
    """``(off_reason, configured)``; ``None`` only while capture is active."""
    if not hasattr(app_state, STATE_OFF_REASON):
        return NOT_CONFIGURED, False
    reason = getattr(app_state, STATE_OFF_REASON, None)
    if reason is None:
        edge = getattr(app_state, STATE_EDGE, None)
        if edge is None:
            return NOT_CONFIGURED, False
        status = getattr(edge, "status", None)
        current = status() if callable(status) else None
        return (None if current is None else str(current)), True
    return str(reason), True


def _snapshot(app_state: Any) -> Mapping[str, object] | None:
    stats = getattr(app_state, STATE_STATS, None)
    if stats is None:
        edge = getattr(app_state, STATE_EDGE, None)
        stats = getattr(edge, "stats", None)
    snapshot = getattr(stats, "snapshot", None)
    if not callable(snapshot):
        return None
    value = snapshot()
    return value if isinstance(value, Mapping) else None  # pyright: ignore[reportUnknownVariableType]


async def read_status(request: Request, read: CaptureReadScope) -> CaptureStatusView:
    app_state = request.app.state
    off_reason, configured = _off_reason(app_state)
    policies, truncated, store_configured = await _visible(request, read)
    counts = Counter(p.state for p in policies)
    snapshot = _snapshot(app_state) if read.customer_wide else None
    return CaptureStatusView(
        state="active" if off_reason is None else "off",
        off_reason=off_reason,
        configured=configured or store_configured,
        domain_id=read.domain_id,
        policies=PolicyStateCounts(
            total=len(policies),
            proposed=counts["proposed"],
            active=counts["active"],
            suspended=counts["suspended"],
            retired=counts["retired"],
        ),
        policies_truncated=truncated,
        counters=None if snapshot is None else counters_view(snapshot),
        counters_scope="customer",
    )
