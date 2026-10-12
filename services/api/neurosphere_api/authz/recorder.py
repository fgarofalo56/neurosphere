"""Optional denied-attempt recorder hook (PRP-06 item 3).

Writing audit records is item 4's job (``neurosphere_core.audit``); item 6 wires a recorder
that appends ``build_denied`` records. This module only defines the protocol ``require`` calls
when it denies. The hook is optional: with no recorder, denials are not recorded here.

Failure rule: if the recorder raises on a mutating request (any method outside
:data:`SAFE_METHODS`), the request fails closed with 503 ``audit_write_failed`` instead of 403,
because a mutating path must not proceed or report without its audit trail. On a safe request a
recorder failure is logged and the request is still denied with 403. In no case does a recorder
failure turn a deny into an allow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

from neurosphere_core.scope import IdentityScope

__all__ = ["SAFE_METHODS", "DenialRecorder", "DeniedAttempt"]

SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True, slots=True)
class DeniedAttempt:
    """Metadata only (C11): no token, no body, no raw object id. ``scope`` is server-derived."""

    scope: IdentityScope
    permission: str
    reason: str
    method: str
    path: str
    domain_id: str | None
    resource_id: str | None


@runtime_checkable
class DenialRecorder(Protocol):
    async def record_denial(self, attempt: DeniedAttempt) -> None: ...
