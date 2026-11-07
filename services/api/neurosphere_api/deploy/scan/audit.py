"""Audit events for scan, plan and consent decisions (#37), over the PRP-06 audit repository.

One :class:`DeployAuditor` is built per request from the server-derived ``IdentityScope`` and the
request correlation id, so actor and scope hash are never taken from request input. Events carry
digests and opaque ids only: subscription ids, consent ids and resource ids are hashed into the
state digest, never written, and no credential value ever reaches this module.

Chain: ``<customer>.deploy`` (the audit_mount ``<customer>.<name>`` convention).

Also adapts :class:`neurosphere_core.deploy.register.ConsentAuditSink` for register-side consent
recording (:class:`ConsentSinkAdapter`).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from neurosphere_core.audit import (
    AuditContext,
    AuditRepository,
    build_after,
    build_allowed,
    build_denied,
    make_subject,
)
from neurosphere_core.audit.builders import DenialCode
from neurosphere_core.deploy.register import ConsentRecord as RegisterConsentRecord
from neurosphere_core.errors import DependencyTransientError, NeuroSphereError
from neurosphere_core.scope import IdentityScope

OP_SCAN = "deploy.scan"
OP_PLAN = "deploy.plan"
OP_CONSENT = "deploy.consent"
ENTITY_SCAN = "deployment_scan"
ENTITY_PLAN = "deployment_plan"
ENTITY_CONSENT = "deployment_consent"


def audit_chain(customer_id: str) -> str:
    return f"{customer_id}.deploy"


def correlation_for(request_id: str) -> str:
    """Audit-safe correlation id (the content guard rejects GUID-shaped values)."""
    return "corr-" + request_id.replace("-", "")


def opaque_id(prefix: str, value: str) -> str:
    """Stable, non-reversible id for caller-supplied text (never GUID/e-mail shaped)."""
    return f"{prefix}-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"


class DeployAuditor:
    def __init__(
        self,
        repository: AuditRepository | None,
        scope: IdentityScope,
        *,
        correlation_id: str,
    ) -> None:
        if repository is None:
            # Fail closed: an unaudited scan/plan/consent decision is not allowed to proceed.
            raise DependencyTransientError(
                "Audit is not configured.", reason="audit_not_configured"
            )
        self._repo = repository
        self._scope = scope
        self._correlation_id = correlation_id

    def _ctx(self, operation: str) -> AuditContext:
        return AuditContext.from_scope(
            self._scope,
            correlation_id=self._correlation_id,
            operation=operation,
            channel="rest",
        )

    def _canonical(self, kind: str, ident: str) -> str:
        return f"{self._scope.cloud}:{self._scope.customer_id}:deploy:{kind}:{ident}"

    async def _append(self, draft: Any) -> None:
        await self._repo.append(audit_chain(self._scope.customer_id), draft)

    async def scan_completed(self, scan_id: str, state: Mapping[str, Any]) -> None:
        subject = make_subject(self._canonical("scan", scan_id), ENTITY_SCAN, state=state)
        await self._append(build_allowed(self._ctx(OP_SCAN), subject))

    async def plan_built(self, plan_id: str, state: Mapping[str, Any], *, source: str) -> None:
        subject = make_subject(self._canonical("plan", plan_id), ENTITY_PLAN, state=state)
        draft = build_after(
            self._ctx(OP_PLAN),
            subject,
            result="succeeded",
            verified=False,
            detail=f"scan_source={source}",
        )
        await self._append(draft)

    async def consent_decision(
        self,
        consent_id: str,
        *,
        granted: bool,
        state: Mapping[str, Any],
        operation: str = OP_CONSENT,
    ) -> None:
        subject = make_subject(
            self._canonical("consent", opaque_id("c", consent_id)), ENTITY_CONSENT, state=state
        )
        draft = build_after(
            self._ctx(operation),
            subject,
            result="succeeded",
            verified=False,
            detail="consent_granted" if granted else "consent_not_granted",
        )
        await self._append(draft)

    async def refused(
        self, operation: str, error: NeuroSphereError, *, target: str | None, entity: str
    ) -> None:
        """Record a refused scan/plan. ``target`` is an already-opaque id, or ``None``."""
        subject = make_subject(target, entity) if target else None
        code: DenialCode = "forbidden" if error.code == "forbidden" else "invalid_schema"
        reason = (error.reason or error.code).lower()[:64]
        await self._append(
            build_denied(self._ctx(operation), code=code, reason=reason, subject=subject)
        )


class ConsentSinkAdapter:
    """``ConsentAuditSink`` for ``record_consent`` (register-side), bound to one request."""

    def __init__(self, auditor: DeployAuditor) -> None:
        self._auditor = auditor

    async def consent_recorded(self, consent: RegisterConsentRecord) -> None:
        await self._auditor.consent_decision(
            consent.consent_id,
            granted=True,
            state={
                "plan": opaque_id("plan", consent.plan_id),
                "resources": len(consent.resource_ids),
            },
        )
