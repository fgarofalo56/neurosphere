"""Auditing of failures before a scope exists (PRP-40 item 5, Clarification 3).

``authz.dependencies.current_derivation`` calls the installed hook (``app.state.prescope_audit``)
when token validation or scope derivation fails. The recorded decision:

* Identity known (a valid token, then a revoked principal, a policy- or revocation-store
  outage, a timeout or an invalid derived scope): a ``denied`` record on
  ``<customer>.authz-denials`` with the actor pseudonym, principal kind, operation
  ``authz.derive``, the error code as the denial code and its reason code. No scope exists, so
  ``scope_hash`` is the fixed :data:`NO_SCOPE_HASH` marker.
* Unauthenticated (401): NO chain record (an anonymous caller could otherwise flood the hash
  chain); a redacted ``neurosphere.authn.v1`` SIEM signal with the reason code, and an
  in-process counter per reason.

Neither path changes the authorization outcome: the caller raises the original error whatever
happens here, and :func:`neurosphere_api.authz.dependencies` logs a hook failure.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Final

from neurosphere_core.audit import AuditContext, AuditRepository, build_denied
from neurosphere_core.audit.siem import SiemExporter
from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.scope import PrincipalPseudonymizer

from neurosphere_api.audit.access import DENIALS_CHAIN_NAME, safe_correlation_id

__all__ = [
    "AUTHN_EVENT_TYPE",
    "NO_SCOPE_HASH",
    "PRESCOPE_OPERATION",
    "PrescopeAuditor",
]

PRESCOPE_OPERATION: Final = "authz.derive"
AUTHN_EVENT_TYPE: Final = "neurosphere.authn.v1"
#: ``scope_hash`` of a record written before any scope was derived (a fixed, documented marker).
NO_SCOPE_HASH: Final = "sha256:" + hashlib.sha256(b"neurosphere:no-scope").hexdigest()

_REASON: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DENIAL_CODES: Final = frozenset(
    {
        "unauthorized",
        "forbidden",
        "capability_unavailable",
        "stale_version",
        "rate_limited",
        "invalid_schema",
        "dependency_transient",
        "not_found",
    }
)
#: Distinct 401 reasons counted; anything beyond is folded into ``other`` (bounded memory).
_MAX_COUNTED_REASONS: Final = 32


def _reason(value: str | None, fallback: str) -> str:
    return value if value is not None and _REASON.fullmatch(value) else fallback


class PrescopeAuditor:
    """The hook installed as ``app.state.prescope_audit`` (see the module docstring)."""

    def __init__(
        self,
        *,
        repository: Callable[[], AuditRepository | None],
        pseudonymizer: PrincipalPseudonymizer,
        customer_id: str,
        exporter: SiemExporter | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._pseudonymizer = pseudonymizer
        self._chain = f"{customer_id}.{DENIALS_CHAIN_NAME}"
        self._exporter = exporter
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._unauthenticated: Counter[str] = Counter()

    @property
    def chain_id(self) -> str:
        return self._chain

    def unauthenticated_counts(self) -> Mapping[str, int]:
        with self._lock:
            return dict(self._unauthenticated)

    async def identity_failure(
        self, claims: VerifiedClaims, code: str, reason: str | None, correlation_id: str | None
    ) -> None:
        """Append a ``denied`` record for a caller whose identity is known but has no scope."""
        repository = self._repository()
        if repository is None:
            return
        kind = "service_principal" if claims.identity_type == "app" else "user"
        ctx = AuditContext.model_validate(
            {
                "actor": {
                    "principal_pseudonym": self._pseudonymizer.pseudonym(
                        claims.tenant_id, claims.object_id
                    ),
                    "principal_kind": kind,
                    "on_behalf_of": None,
                },
                "scope_hash": NO_SCOPE_HASH,
                "correlation_id": safe_correlation_id(correlation_id),
                "operation": PRESCOPE_OPERATION,
                "channel": "rest",
            }
        )
        denial_code: Any = code if code in _DENIAL_CODES else "forbidden"
        draft = build_denied(ctx, code=denial_code, reason=_reason(reason, denial_code))
        await repository.append(self._chain, draft)

    async def unauthenticated(self, reason: str | None, correlation_id: str | None) -> None:
        """Count the 401 and send a redacted SIEM signal; never a chain record."""
        code = _reason(reason, "unauthorized")
        with self._lock:
            if code not in self._unauthenticated and len(self._unauthenticated) >= (
                _MAX_COUNTED_REASONS
            ):
                code = "other"
            self._unauthenticated[code] += 1
        if self._exporter is None:
            return
        await self._exporter.export_signal(
            AUTHN_EVENT_TYPE,
            {
                "outcome": "unauthenticated",
                "reason": code,
                "correlation_id": safe_correlation_id(correlation_id),
                "observed_at": self._clock().isoformat(),
            },
        )
