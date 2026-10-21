"""Action API flows: draft, validate, confirmation, confirm, decisions, reads (PRP-17 item 4).

Every surface (button, chat, REST, later MCP) reaches these methods through the same routes and
builds the same ``ActionIntent`` server-side; ``channel`` is metadata only. State changes happen
ONLY inside :class:`~neurosphere_core.actions.ActionService` (allowlist, maker rule, hash and
expiry binding, rechecks, kill switch, audit). This module adds the API-side prerequisites, the
connector ``dry_run`` probe, the per-kind approval policy and the maker-checker hand-off to
HITL. It never calls a connector's ``apply`` or ``rollback``; the executor worker does.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from neurosphere_connector.write import WriteConnector
from neurosphere_contracts.actions.v1.action_intent import PrerequisiteResult
from neurosphere_core.actions import (
    ActionCaller,
    IntentKey,
    StoredIntent,
    confirmation_hashes_equal,
    validate_proposed_diff,
)
from neurosphere_core.actions.errors import (
    CONFIRMATION_HASH_MISMATCH,
    NOT_MAKER,
    POLICY_STORE_UNAVAILABLE,
    ActionValidationError,
    InvalidTransitionError,
)
from neurosphere_core.actions.models import format_timestamp
from neurosphere_core.auth.scope import Permission
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    NeuroSphereError,
)
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.approval import decide_maker_checker, refuse_advisory
from neurosphere_api.actions.common import (
    action_view,
    caller_for,
    connector_unavailable,
    load_intent,
    not_found,
    probe_target_version,
    write_request,
)
from neurosphere_api.actions.dependencies import ActionPlane
from neurosphere_api.actions.models import (
    ActionList,
    ActionView,
    ConfirmBody,
    DecisionBody,
    DraftIntentBody,
)

__all__ = ["ON_BEHALF_OF_UNRESOLVED", "ActionApi"]

ON_BEHALF_OF_UNRESOLVED: Final = "on_behalf_of_unresolved"


def _reason(exc: NeuroSphereError) -> str:
    return exc.reason if isinstance(exc.reason, str) and exc.reason else exc.code


class ActionApi:
    """Request-scoped facade over the :class:`ActionPlane`."""

    def __init__(self, plane: ActionPlane) -> None:
        self._plane = plane

    # -- reads -----------------------------------------------------------------------------

    async def get(self, key: IntentKey) -> ActionView:
        return action_view(self._plane, await load_intent(self._plane, key))

    async def list(
        self,
        scope: IdentityScope,
        domain: str,
        *,
        state: str | None,
        cursor: str | None,
        limit: int,
    ) -> ActionList:
        page = await self._plane.intents.list(
            scope.customer_id, domain, state=state, cursor=cursor, limit=limit
        )
        return ActionList(
            items=[action_view(self._plane, s) for s in page.items], next_cursor=page.next_cursor
        )

    # -- draft -----------------------------------------------------------------------------

    async def draft(
        self, scope: IdentityScope, domain: str, body: DraftIntentBody, correlation_id: str
    ) -> tuple[ActionView, bool]:
        """Draft (or replay) an intent. Returns the view and whether it was created now."""
        caller = caller_for(scope, correlation_id, body.channel)
        outcome = await self._plane.actions.draft(
            caller,
            body.to_draft_request(),
            customer_id=scope.customer_id,
            domain_id=domain,
            now=self._plane.now(),
        )
        return action_view(self._plane, outcome.stored), outcome.created

    # -- validate --------------------------------------------------------------------------

    async def validate(
        self, scope: IdentityScope, key: IntentKey, correlation_id: str
    ) -> ActionView:
        """Prerequisites plus the connector ``dry_run``: ``validated`` or ``failed``.

        Transient failures (policy store, connector) raise 503 and leave the intent ``drafted``
        so the call can be retried; a definite failure is recorded as a ``failed`` check.
        """
        plane = self._plane
        stored = await load_intent(plane, key)
        caller = self._caller(scope, correlation_id, stored)
        if stored.state != "drafted":
            raise InvalidTransitionError(stored.state, "validated")
        if caller.principal_id != stored.principal_id:
            raise ForbiddenError("only the maker may validate this intent", reason=NOT_MAKER)
        at = plane.now()
        connector = plane.connector_for(stored.intent.action_kind)
        advisory = connector is None
        results = [
            await self._permission_check(stored, advisory, at),
            self._policy_check(stored, at),
            self._diff_check(stored, at),
            self._connector_check(advisory, at),
            await self._dry_run_check(connector, stored, at),
        ]
        saved = await plane.actions.record_validation(
            key, caller, results, advisory=advisory, now=at
        )
        return action_view(plane, saved)

    async def _permission_check(
        self, stored: StoredIntent, advisory: bool, at: datetime
    ) -> PrerequisiteResult:
        permission = Permission.ACTION_PROPOSE if advisory else Permission.ACTION_EXECUTE
        try:
            granted = await self._plane.rechecker.check(
                stored.principal_id, stored.customer_id, stored.domain_id, permission.value
            )
        except NeuroSphereError:
            raise
        except Exception as exc:
            raise DependencyTransientError(
                "policy store unavailable", reason=POLICY_STORE_UNAVAILABLE
            ) from exc
        detail = None if granted else f"maker does not hold {permission.value} on the domain"
        return _check("actor_permission", "passed" if granted else "failed", detail, at)

    def _policy_check(self, stored: StoredIntent, at: datetime) -> PrerequisiteResult:
        kind = stored.intent.action_kind
        if not self._plane.requires_approval(kind):
            return _check("approval_policy", "not_applicable", "no approval required", at)
        try:
            self._plane.policies.resolve("maker_checker", kind)
        except NeuroSphereError as exc:
            return _check("approval_policy", "failed", _reason(exc), at)
        return _check("approval_policy", "passed", None, at)

    @staticmethod
    def _diff_check(stored: StoredIntent, at: datetime) -> PrerequisiteResult:
        try:
            validate_proposed_diff(stored.intent.proposed_diff)
        except ActionValidationError as exc:
            return _check("diff_well_formed", "failed", _reason(exc), at)
        return _check("diff_well_formed", "passed", None, at)

    @staticmethod
    def _connector_check(advisory: bool, at: datetime) -> PrerequisiteResult:
        if advisory:
            return _check(
                "write_connector_supported",
                "warning",
                "no supported write connector for this action; advisory only",
                at,
            )
        return _check("write_connector_supported", "passed", None, at)

    @staticmethod
    async def _dry_run_check(
        connector: WriteConnector | None, stored: StoredIntent, at: datetime
    ) -> PrerequisiteResult:
        if connector is None:
            return _check("target_dry_run", "not_applicable", "advisory: nothing to plan", at)
        try:
            result = await connector.dry_run(write_request(stored))
        except DependencyTransientError:
            raise
        except NeuroSphereError as exc:
            # stale_version, capability_unavailable, invalid_schema, forbidden: a definite no.
            return _check("target_dry_run", "failed", _reason(exc), at)
        except Exception as exc:
            raise connector_unavailable(exc) from exc
        if result.target_version != stored.intent.target_version:
            return _check("target_dry_run", "failed", "target_version_changed", at)
        if not result.would_change:
            return _check("target_dry_run", "warning", "the diff changes nothing", at)
        return _check("target_dry_run", "passed", None, at)

    # -- confirmation ----------------------------------------------------------------------

    async def present_confirmation(
        self, scope: IdentityScope, key: IntentKey, correlation_id: str
    ) -> ActionView:
        """``validated`` -> ``awaiting_confirmation`` (maker only); binds hash and expiry.

        The expiry is longer when the kind requires approval, so the checker can decide
        before the confirmation lapses.
        """
        plane = self._plane
        stored = await load_intent(plane, key)
        caller = self._caller(scope, correlation_id, stored)
        current: str | None = None
        if stored.state == "validated" and caller.principal_id == stored.principal_id:
            connector = None if stored.advisory else plane.connector_for(stored.intent.action_kind)
            if connector is not None:
                current = await probe_target_version(connector, stored)
        saved = await plane.actions.present_confirmation(
            key,
            caller,
            current_target_version=current,
            ttl=plane.settings.confirmation_ttl_for(stored.intent.action_kind),
            now=plane.now(),
        )
        return action_view(plane, saved)

    async def confirm(
        self, scope: IdentityScope, key: IntentKey, body: ConfirmBody, correlation_id: str
    ) -> ActionView:
        """Maker confirms: -> ``awaiting_approval`` (review item opened) or ``executing``."""
        plane = self._plane
        stored = await load_intent(plane, key)
        caller = self._caller(scope, correlation_id, stored)
        kind = stored.intent.action_kind
        if self._needs_review_link(stored, caller):
            # Recovery: confirmed, but opening the review item failed last time.
            if not confirmation_hashes_equal(
                body.confirmation_hash,
                None
                if stored.intent.confirmation_hash is None
                else stored.intent.confirmation_hash.root,
            ):
                raise ActionValidationError(
                    CONFIRMATION_HASH_MISMATCH, "confirmation does not match the bound intent"
                )
            return action_view(plane, await self._open_review(stored, caller))
        requires_approval = plane.requires_approval(kind)
        connector = plane.connector_for(kind)
        advisory = stored.advisory or connector is None
        if not advisory and requires_approval and stored.intent.actor.on_behalf_of is not None:
            # Self-approval separation needs the REAL principal behind an on-behalf-of maker;
            # this API cannot derive it, so it fails closed before anything changes.
            raise ForbiddenError(
                "an on-behalf-of maker needs a resolvable principal", reason=ON_BEHALF_OF_UNRESOLVED
            )
        current = stored.intent.target_version
        if (
            not advisory
            and connector is not None
            and stored.state == "awaiting_confirmation"
            and caller.principal_id == stored.principal_id
        ):
            current = await probe_target_version(connector, stored)
        saved = await plane.actions.confirm(
            key,
            caller,
            confirmation_hash=body.confirmation_hash,
            current_target_version=current,
            requires_approval=requires_approval,
            advisory=advisory,
            now=plane.now(),
        )
        if saved.state == "awaiting_approval":
            saved = await self._open_review(saved, caller)
        return action_view(plane, saved)

    @staticmethod
    def _needs_review_link(stored: StoredIntent, caller: ActionCaller) -> bool:
        return (
            stored.state == "awaiting_approval"
            and stored.review_item_id is None
            and caller.principal_id == stored.principal_id
        )

    async def _open_review(self, stored: StoredIntent, caller: ActionCaller) -> StoredIntent:
        plane = self._plane
        bound = stored.intent.confirmation_hash
        if bound is None:  # cannot happen in awaiting_approval (core validates the binding)
            raise ActionValidationError(CONFIRMATION_HASH_MISMATCH, "no confirmation binding")
        if stored.intent.actor.on_behalf_of is not None:
            raise ForbiddenError(
                "an on-behalf-of maker needs a resolvable principal", reason=ON_BEHALF_OF_UNRESOLVED
            )
        item = await plane.hitl.open_item(
            kind="maker_checker",
            customer_id=stored.customer_id,
            domain_id=stored.domain_id,
            subject_ref=stored.intent.target.canonical_id,
            now=plane.now(),
            correlation_id=caller.correlation_id,
            action_kind=stored.intent.action_kind,
            intent_id=stored.intent_id,
            confirmation_hash=bound.root,
            maker_principal_id=stored.principal_id,
            maker_on_behalf_of_principal_id=None,
            maker=stored.intent.actor,
            opened_by=caller.actor,
            scope_hash=caller.scope_hash,
            channel=caller.channel,
        )
        return await plane.actions.link_review_item(stored.key, item.item_id)

    # -- decisions -------------------------------------------------------------------------

    async def decide(
        self, scope: IdentityScope, key: IntentKey, body: DecisionBody, correlation_id: str
    ) -> ActionView:
        """Maker-checker decision on the intent's linked review item (the one approval path)."""
        plane = self._plane
        stored = await load_intent(plane, key)
        caller = self._caller(scope, correlation_id, stored)
        refuse_advisory(plane, stored)
        if stored.review_item_id is None:
            raise InvalidTransitionError(stored.state, "executing")
        item = await plane.hitl.get(stored.review_item_id)
        if item is None:
            raise not_found()
        saved = await decide_maker_checker(
            plane,
            stored=stored,
            item=item,
            caller=caller,
            decision=body.decision,
            reason=body.reason,
            confirmation_hash=body.confirmation_hash,
        )
        return action_view(plane, saved)

    # -- helpers ---------------------------------------------------------------------------

    @staticmethod
    def _caller(scope: IdentityScope, correlation_id: str, stored: StoredIntent) -> ActionCaller:
        # Follow-up calls are audited under the channel the intent arrived through (metadata).
        return caller_for(scope, correlation_id, stored.intent.channel)


def _check(check_id: str, status: str, detail: str | None, at: datetime) -> PrerequisiteResult:
    return PrerequisiteResult.model_validate(
        {
            "check_id": check_id,
            "status": status,
            "detail": detail,
            "evaluated_at": format_timestamp(at),
            "evidence_ids": [],
        }
    )
