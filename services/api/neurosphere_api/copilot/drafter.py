"""``ActionDrafter`` bound to the PRP-17 action API (PRP-19 item 2).

Chat drafts an intent through :class:`~neurosphere_api.actions.service.ActionApi.draft`, the very
method behind ``POST /api/v1/actions/domains/{domain}/intents``, so a chat-produced intent is the
same document with the same confirmation hash input as a REST- or button-produced one (the
channel is metadata, never hashed). This module exposes ``draft`` only: there is no confirm,
validate or execute call anywhere in the copilot package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from neurosphere_contracts.actions.v1.action_intent import ActionIntent
from neurosphere_core.actions import DraftRequest, compute_confirmation_hash
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.dependencies import ActionPlane
from neurosphere_api.actions.models import DraftIntentBody
from neurosphere_api.actions.service import ActionApi

__all__ = ["ActionPlaneDrafter", "DraftedIntent"]


@dataclass(frozen=True, slots=True)
class DraftedIntent:
    """What the ``action_suggestion`` event carries for one draft."""

    intent_id: str
    domain_id: str
    action_type: str
    target: dict[str, Any]
    intent_hash: str


@dataclass
class ActionPlaneDrafter:
    """Per-turn drafter. ``plane`` is ``None`` when the action plane is not configured: drafting
    then fails closed with 503 and chat keeps working for read-only questions."""

    plane: ActionPlane | None
    correlation_id: str
    drafted: list[DraftedIntent] = field(default_factory=list[DraftedIntent])

    async def draft(
        self, scope: IdentityScope, request: DraftRequest, *, domain_id: str
    ) -> ActionIntent:
        if self.plane is None:
            raise DependencyTransientError(
                "action plane is not configured", reason="action_plane_unconfigured"
            )
        body = DraftIntentBody(
            action_kind=request.action_kind,
            target=request.target,
            target_version=request.target_version,
            proposed_diff=request.proposed_diff,
            evidence=list(request.evidence),
            idempotency_key=request.idempotency_key,
            channel="chat",
            dry_run=request.dry_run,
        )
        view, _created = await ActionApi(self.plane).draft(
            scope, domain_id, body, self.correlation_id
        )
        intent = view.intent
        self.drafted.append(
            DraftedIntent(
                intent_id=intent.intent_id.root,
                domain_id=domain_id,
                action_type=intent.action_kind,
                target=intent.target.model_dump(mode="json"),
                intent_hash=compute_confirmation_hash(intent),
            )
        )
        return intent
