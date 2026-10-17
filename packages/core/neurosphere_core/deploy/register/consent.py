"""Consent recording with an audit hook.

Wiring the PRP-06 audit repository needs a scope/subject context that belongs to the API layer,
so core exposes a small sink protocol (default: no-op). The API layer adapts it to
``AuditRepository`` (PRP-08 clarification 10).
"""

from __future__ import annotations

from typing import Protocol

from neurosphere_core.deploy.register.models import ConsentRecord
from neurosphere_core.deploy.register.store import RegisterStore


class ConsentAuditSink(Protocol):
    async def consent_recorded(self, consent: ConsentRecord) -> None: ...


class NoOpConsentAuditSink:
    async def consent_recorded(self, consent: ConsentRecord) -> None:
        return None


async def record_consent(
    store: RegisterStore, consent: ConsentRecord, sink: ConsentAuditSink | None = None
) -> None:
    """Store the consent document first, then emit the audit event."""
    await store.put_consent(consent)
    await (sink or NoOpConsentAuditSink()).consent_recorded(consent)
