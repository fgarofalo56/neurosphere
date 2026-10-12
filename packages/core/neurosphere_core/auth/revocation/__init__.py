"""Principal revocation (PRP-06 item 5): list, TTL-bounded check, fan-out, admin revoke.

Revocation is bounded by ``NS_REVOCATION_TTL_SECONDS`` (default 60 s,
:data:`DEFAULT_REVOCATION_TTL_SECONDS`), not instant: every replica re-reads a principal's
revocation state at most that often, so a revoked principal is denied (403, reason
``principal_revoked``) on every replica no later than the TTL after the revocation, and at once
on the replica that performed it. See ``model`` for the full statement and settings.

Wiring (the API layer, item 6 fixtures and PRP-18 do this; nothing here imports services)::

    store = CosmosRevocationStore.from_client(client, database=db)  # or InMemoryRevocationStore
    checker = CachedRevocationChecker.from_settings(store, load_revocation_settings())
    deriver = ScopeDeriver(cfg, ..., revocation_checker=checker)
    hooks = RevocationHookRegistry()
    hooks.register_cache_invalidator("revocation-checker", checker.invalidate_principal)
    hooks.register_cache_invalidator("scope-deriver", deriver.invalidate_principal)
    hooks.register_push_registry("websocket", gateway_registry)  # PRP-18
    service = RevocationService(store=store, authorizer=..., auditor=..., hooks=hooks)
"""

from neurosphere_core.auth.revocation.checker import (
    DEFAULT_CHECKER_MAX_ENTRIES,
    CachedRevocationChecker,
)
from neurosphere_core.auth.revocation.cosmos_store import (
    DEFAULT_REVOCATION_CONTAINER,
    CosmosRevocationStore,
)
from neurosphere_core.auth.revocation.fanout import (
    DEFAULT_HOOK_TIMEOUT_SECONDS,
    CacheInvalidator,
    FanoutReport,
    HookKind,
    PushSessionRegistry,
    RevocationHookRegistry,
)
from neurosphere_core.auth.revocation.model import (
    DEFAULT_CLOCK_SKEW_SECONDS,
    DEFAULT_REVOCATION_RETENTION_SECONDS,
    DEFAULT_REVOCATION_TTL_SECONDS,
    MAX_REVOCATION_TTL_SECONDS,
    MIN_REVOCATION_RETENTION_SECONDS,
    PRINCIPAL_ID_PATTERN,
    REASON_CODE_PATTERN,
    ReasonCode,
    RevocationEntry,
    RevocationSettings,
    is_canonical_principal_id,
    is_reason_code,
    load_revocation_settings,
    revocation_document_id,
)
from neurosphere_core.auth.revocation.service import (
    REVOKE_ACTION,
    AuditPhase,
    RevocationAuditEvent,
    RevocationAuditor,
    RevocationAuthorizer,
    RevocationOutcome,
    RevocationService,
    ScopePermissionRevocationAuthorizer,
)
from neurosphere_core.auth.revocation.store import InMemoryRevocationStore, RevocationStore

__all__ = [
    "DEFAULT_CHECKER_MAX_ENTRIES",
    "DEFAULT_CLOCK_SKEW_SECONDS",
    "DEFAULT_HOOK_TIMEOUT_SECONDS",
    "DEFAULT_REVOCATION_CONTAINER",
    "DEFAULT_REVOCATION_RETENTION_SECONDS",
    "DEFAULT_REVOCATION_TTL_SECONDS",
    "MAX_REVOCATION_TTL_SECONDS",
    "MIN_REVOCATION_RETENTION_SECONDS",
    "PRINCIPAL_ID_PATTERN",
    "REASON_CODE_PATTERN",
    "REVOKE_ACTION",
    "AuditPhase",
    "CacheInvalidator",
    "CachedRevocationChecker",
    "CosmosRevocationStore",
    "FanoutReport",
    "HookKind",
    "InMemoryRevocationStore",
    "PushSessionRegistry",
    "ReasonCode",
    "RevocationAuditEvent",
    "RevocationAuditor",
    "RevocationAuthorizer",
    "RevocationEntry",
    "RevocationHookRegistry",
    "RevocationOutcome",
    "RevocationService",
    "RevocationSettings",
    "RevocationStore",
    "ScopePermissionRevocationAuthorizer",
    "is_canonical_principal_id",
    "is_reason_code",
    "load_revocation_settings",
    "revocation_document_id",
]
