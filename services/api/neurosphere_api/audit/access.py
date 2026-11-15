"""Shared pieces of the PRP-40 audit routes: readable chains, filters, cursor and denials.

Chains are ALWAYS derived server-side from the caller's scope: a domain id (named by the caller
or taken from the scope) maps to its chain through
:func:`neurosphere_api.ui_adapters.audit.auditable_chain`. No route accepts a chain id, query
text or SQL. A named domain the caller may not read is 403 ``target_out_of_scope`` and is
recorded through the configured denial recorder (a recorder failure on these GET routes is
logged and the request is still denied).

No ``from __future__ import annotations``: FastAPI inspects the dependency signatures below.
"""

import base64
import binascii
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Final, Literal

from fastapi import Depends, Query, Request
from neurosphere_core.audit import AuditContext, find_sensitive_content
from neurosphere_core.auth.scope import Permission, domains_with_permission, permits_customer_wide
from neurosphere_core.errors import DependencyTransientError, ForbiddenError, InvalidSchemaError
from neurosphere_core.observability import get_logger
from neurosphere_core.scope import IdentityScope

from neurosphere_api.audit.search_store import (
    AuditSearchFilter,
    AuditSearchStore,
    SearchPosition,
)
from neurosphere_api.authz import AuthzState, DeniedAttempt, get_authz_state, require
from neurosphere_api.middleware import correlation_id_of

__all__ = [
    "CUSTOMER_SCOPE_REQUIRED",
    "DENIALS_CHAIN_NAME",
    "MAX_DOMAINS_PER_REQUEST",
    "MAX_SEARCH_WINDOW",
    "SearchFilters",
    "audit_context",
    "decode_cursor",
    "encode_cursor",
    "get_search_store",
    "now_of",
    "record_denial",
    "require_customer_wide",
    "resolve_chains",
    "safe_correlation_id",
]

#: The longest ``until - since`` a search or export may cover (documented in the runbook).
MAX_SEARCH_WINDOW: Final = timedelta(days=31)
#: How many ``domain`` filters one request may name.
MAX_DOMAINS_PER_REQUEST: Final = 50
#: Chain ``<customer>.<this>`` holds denials for non-member targets; equals
#: ``runtime.builders.authz.DENIAL_CHAIN_NAME`` (a test pins it; not imported to stay leaf-level).
DENIALS_CHAIN_NAME: Final = "authz-denials"
CUSTOMER_SCOPE_REQUIRED: Final = "customer_scope_required"

_LOG = get_logger("neurosphere_api.audit")
_CORRELATION: Final = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_TIMESTAMP: Final = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"
)
_CHAIN: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")

OPERATION_PATTERN: Final = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){0,7}$"
ACTOR_PATTERN: Final = r"^p-[A-Za-z0-9_-]{1,96}$"
CORRELATION_PATTERN: Final = r"^[A-Za-z0-9._-]{1,128}$"
CURSOR_PATTERN: Final = r"^[A-Za-z0-9_-]{1,512}$"
DOMAIN_MAX_LENGTH: Final = 256


def now_of(state: AuthzState) -> datetime:
    return datetime.fromtimestamp(state.clock(), UTC)


def get_search_store(request: Request) -> AuditSearchStore:
    store = getattr(request.app.state, "audit_search_store", None)
    if not isinstance(store, AuditSearchStore):
        raise DependencyTransientError(
            "audit search is not configured", reason="capability_unavailable"
        )
    return store


# --------------------------------------------------------------------------- filters


class SearchFilters:
    """The validated query filters shared by search and export (dependency class)."""

    def __init__(
        self,
        since: Annotated[datetime, Query(description="Inclusive start (RFC 3339, with zone)")],
        until: Annotated[datetime, Query(description="Exclusive end (RFC 3339, with zone)")],
        domain: Annotated[
            list[str] | None,
            Query(max_length=MAX_DOMAINS_PER_REQUEST, description="Domain ids; default: all"),
        ] = None,
        operation: Annotated[str | None, Query(max_length=128, pattern=OPERATION_PATTERN)] = None,
        kind: Literal["before", "after", "denied"] | None = None,
        outcome: Literal["succeeded", "failed", "rolled_back"] | None = None,
        actor: Annotated[str | None, Query(pattern=ACTOR_PATTERN)] = None,
        correlation_id: Annotated[str | None, Query(pattern=CORRELATION_PATTERN)] = None,
    ) -> None:
        if since.tzinfo is None or until.tzinfo is None:
            raise InvalidSchemaError("since and until need a time zone", reason="invalid_range")
        if until <= since:
            raise InvalidSchemaError("until must be after since", reason="invalid_range")
        if until - since > MAX_SEARCH_WINDOW:
            raise InvalidSchemaError(
                f"the time range is capped at {MAX_SEARCH_WINDOW.days} days",
                reason="range_too_large",
            )
        for value in domain or ():
            if not value or len(value) > DOMAIN_MAX_LENGTH:
                raise InvalidSchemaError("invalid domain id", reason="invalid_domain")
        self.domains: tuple[str, ...] = tuple(dict.fromkeys(domain or ()))
        self.filter = AuditSearchFilter(
            since=since.astimezone(UTC),
            until=until.astimezone(UTC),
            operation=operation,
            kind=kind,
            outcome=outcome,
            actor=actor,
            correlation_id=correlation_id,
        )

    def describe(self) -> dict[str, object]:
        """Filters as plain data (for the export audit record digest)."""
        f = self.filter
        return {
            "domains": sorted(self.domains),
            "since": f.since.isoformat(),
            "until": f.until.isoformat(),
            "operation": f.operation,
            "kind": f.kind,
            "outcome": f.outcome,
            "actor": f.actor,
            "correlation_id": f.correlation_id,
        }


# --------------------------------------------------------------------------- chains


async def record_denial(
    state: AuthzState,
    request: Request,
    scope: IdentityScope,
    perm: Permission,
    domain_id: str | None,
    reason: str,
) -> None:
    """Record a denied attempt like ``require`` does (safe methods: a failure is logged)."""
    recorder = state.denial_recorder
    if recorder is None:
        return
    attempt = DeniedAttempt(
        scope=scope,
        permission=perm.value,
        reason=reason,
        method=request.method,
        path=request.url.path,
        domain_id=domain_id,
        resource_id=None,
        correlation_id=correlation_id_of(request.scope),
    )
    try:
        await recorder.record_denial(attempt)
    except Exception:
        _LOG.warning(
            "denied-attempt audit record failed",
            extra={"permission": perm.value, "deny_reason": reason},
        )


async def resolve_chains(
    request: Request,
    state: AuthzState,
    scope: IdentityScope,
    requested: tuple[str, ...],
    permissions: tuple[Permission, ...],
) -> dict[str, str]:
    """``{domain_id: chain_id}`` the caller may use with every one of ``permissions``.

    With no ``requested`` domains: every auditable domain of the scope that holds them all
    (403 ``permission_missing`` when none). A requested domain outside that set is 403
    ``target_out_of_scope`` (recorded), never silently dropped.
    """
    # Local import: ui_adapters imports this package (no import cycle at module load).
    from neurosphere_api.ui_adapters.audit import auditable_chain

    now = now_of(state)
    held: set[str] | None = None
    for perm in permissions:
        domains = set(domains_with_permission(scope, perm, now=now))
        held = domains if held is None else held & domains
    readable: dict[str, str] = {}
    for domain_id in sorted(held or ()):
        chain = auditable_chain(scope, domain_id)
        if chain is not None:
            readable[domain_id] = chain
    if not requested:
        if not readable:
            raise ForbiddenError("no auditable domain in scope", reason="permission_missing")
        return readable
    chosen: dict[str, str] = {}
    for domain_id in requested:
        chain = readable.get(domain_id)
        if chain is None:
            perm = next(
                (
                    p
                    for p in permissions
                    if domain_id not in domains_with_permission(scope, p, now=now)
                ),
                permissions[0],
            )
            await record_denial(state, request, scope, perm, domain_id, "target_out_of_scope")
            raise ForbiddenError(
                "insufficient scope for this operation", reason="target_out_of_scope"
            )
        chosen[domain_id] = chain
    return chosen


def require_customer_wide(permission: Permission) -> Callable[..., Awaitable[IdentityScope]]:
    """Dependency (after ``require(permission)``): ``permission`` on the customer control domain.

    A domain-only holder gets 403 ``customer_scope_required`` (recorded on the denials chain).
    """

    base = require(permission)

    async def require_customer_wide_permission(
        request: Request,
        scope: Annotated[IdentityScope, Depends(base)],
        state: Annotated[AuthzState, Depends(get_authz_state)],
    ) -> IdentityScope:
        if permits_customer_wide(scope, permission, now=now_of(state)) is True:
            return scope
        await record_denial(state, request, scope, permission, None, CUSTOMER_SCOPE_REQUIRED)
        raise ForbiddenError(
            f"this view covers the whole customer and needs customer-level {permission.value}",
            reason=CUSTOMER_SCOPE_REQUIRED,
        )

    require_customer_wide_permission.__name__ = (
        f"require_customer_wide_{permission.value.replace('.', '_')}"
    )
    return require_customer_wide_permission


# --------------------------------------------------------------------------- cursor


def encode_cursor(position: SearchPosition) -> str:
    raw = json.dumps([position.recorded_at, position.chain_id, position.sequence])
    return base64.urlsafe_b64encode(raw.encode("ascii")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None, chains: set[str]) -> SearchPosition | None:
    """The position in ``cursor``; anything malformed or naming another chain is 422."""
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, binascii.Error, UnicodeError):
        raise InvalidSchemaError("invalid cursor", reason="invalid_cursor") from None
    if (
        not isinstance(value, list)
        or len(value) != 3  # pyright: ignore[reportUnknownArgumentType]
        or not isinstance(value[0], str)
        or not isinstance(value[1], str)
        or not isinstance(value[2], int)
        or isinstance(value[2], bool)
        or not _TIMESTAMP.fullmatch(value[0])
        or not _CHAIN.fullmatch(value[1])
        or value[1] not in chains
        or not 0 <= value[2] < 10**18
    ):
        raise InvalidSchemaError("invalid cursor", reason="invalid_cursor")
    return SearchPosition(value[0], value[1], value[2])


# --------------------------------------------------------------------------- audit context


def audit_context(request: Request, scope: IdentityScope, operation: str) -> AuditContext:
    """Audit context with the request's correlation id in audit-safe form (else generated)."""
    return AuditContext.from_scope(
        scope,
        correlation_id=safe_correlation_id(correlation_id_of(request.scope)),
        operation=operation,
        channel="rest",
    )


def safe_correlation_id(request_id: str | None) -> str:
    """The middleware correlation id in audit-safe form (``corr-`` plus the id without dashes,
    the ``actions.common`` convention) when it passes the guard, else a generated one."""
    if request_id:
        candidate = "corr-" + request_id.replace("-", "")
        if candidate != "corr-" and _CORRELATION.fullmatch(candidate):
            if not find_sensitive_content({"correlation_id": candidate}):
                return candidate
    return f"corr-{uuid.uuid4().hex}"
