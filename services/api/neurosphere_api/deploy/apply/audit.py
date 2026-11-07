"""Audit events for plan approval, apply requests and uninstall previews (PRP-08 item 12).

Same repository, chain and builders as the scan/plan auditor (``<customer>.deploy``); this module
only adds the operation names. Events carry digests and opaque ids, never resource ids as text.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from neurosphere_core.audit import build_after, make_subject
from neurosphere_core.errors import NeuroSphereError

from neurosphere_api.deploy.scan.audit import DeployAuditor, opaque_id

OP_APPROVE = "deploy.apply.approve"
OP_APPLY = "deploy.apply.request"
OP_UNINSTALL = "deploy.uninstall.preview"
ENTITY_PLAN = "deployment_plan"
ENTITY_DEPLOYMENT = "deployment"

__all__ = [
    "ENTITY_DEPLOYMENT",
    "ENTITY_PLAN",
    "OP_APPLY",
    "OP_APPROVE",
    "OP_UNINSTALL",
    "ApplyAuditor",
]


class ApplyAuditor(DeployAuditor):
    """:class:`DeployAuditor` plus the apply-side events (built per request from the scope)."""

    async def _record(
        self,
        operation: str,
        kind: str,
        ident: str,
        entity: str,
        state: Mapping[str, Any],
        detail: str,
    ) -> None:
        subject = make_subject(self._canonical(kind, ident), entity, state=state)
        draft = build_after(
            self._ctx(operation), subject, result="succeeded", verified=False, detail=detail
        )
        await self._append(draft)

    async def refused_for(
        self, operation: str, error: NeuroSphereError, *, kind: str, ident: str, entity: str
    ) -> None:
        """Audit a refusal against a target named by caller-supplied text (hashed, never raw)."""
        target = self._canonical(kind, opaque_id("x", ident))
        await self.refused(operation, error, target=target, entity=entity)

    async def plan_approved(self, plan_id: str, state: Mapping[str, Any]) -> None:
        await self._record(OP_APPROVE, "plan", plan_id, ENTITY_PLAN, state, "plan_approved")

    async def apply_requested(self, plan_id: str, state: Mapping[str, Any]) -> None:
        await self._record(OP_APPLY, "plan", plan_id, ENTITY_PLAN, state, "apply_drafted")

    async def uninstall_previewed(self, deployment_id: str, state: Mapping[str, Any]) -> None:
        await self._record(
            OP_UNINSTALL, "deployment", deployment_id, ENTITY_DEPLOYMENT, state, "dry_run_only"
        )
