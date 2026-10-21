"""Shared fixtures for action-plane tests: callers, a draft request, a wired service, a clock."""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from neurosphere_contracts.actions.v1.action_intent import PrerequisiteResult
from neurosphere_core.actions import (
    ActionCaller,
    ActionService,
    DraftRequest,
    GrantTablePermissionRechecker,
    InMemoryExecutionControl,
    InMemoryIntentStore,
    IntentKey,
    RecordingActionAuditor,
    StoredIntent,
)

REPO = Path(__file__).resolve().parents[4]
CONTRACTS = REPO / "packages" / "contracts" / "schemas" / "actions" / "v1"

CUSTOMER = "contoso"
DOMAIN = "commercial:contoso:catalog:domain:retail"
OTHER_DOMAIN = "commercial:contoso:catalog:domain:finance"
TARGET_ID = "commercial:contoso:foundry:model_deployment:eastus2/chat-prod"
TARGET_VERSION = "etag-0x8dce1f2a3b4c5d6"
MAKER_ID = "commercial:contoso:entra:person:psn_maker0000000001"
CHECKER_ID = "commercial:contoso:entra:person:psn_checker00000001"
OUTSIDER_ID = "commercial:contoso:entra:person:psn_outsider0000001"
START = datetime(2026, 10, 20, 12, 0, 0, 250000, tzinfo=UTC)


def load_contract(name: str) -> dict[str, Any]:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def scope_hash(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def caller(
    principal_id: str = MAKER_ID,
    pseudonym: str = "p-maker01",
    *,
    channel: str = "rest",
    correlation_id: str = "corr-action-0001",
) -> ActionCaller:
    return ActionCaller.model_validate(
        {
            "principal_id": principal_id,
            "actor": {
                "principal_pseudonym": pseudonym,
                "principal_kind": "user",
                "on_behalf_of": None,
            },
            "scope_hash": scope_hash(pseudonym),
            "correlation_id": correlation_id,
            "channel": channel,
        }
    )


MAKER = caller()
CHECKER = caller(CHECKER_ID, "p-checker01")
OUTSIDER = caller(OUTSIDER_ID, "p-outsider01")


def request(
    key: str = "idem-2026-10-20-chat-prod-0001",
    *,
    channel: str = "rest",
    new_version: str = "2026-06-15",
    target_id: str = TARGET_ID,
    dry_run: bool = False,
) -> DraftRequest:
    return DraftRequest.model_validate(
        {
            "action_kind": "model_swap",
            "target": {"canonical_id": target_id, "entity_type": "model_deployment"},
            "target_version": TARGET_VERSION,
            "proposed_diff": {
                "format": "json_patch",
                "operations": [
                    {"op": "test", "path": "/model/version", "value": "2025-08-01"},
                    {"op": "replace", "path": "/model/version", "value": new_version},
                ],
            },
            "evidence": [
                {
                    "evidence_id": "rec-0042",
                    "kind": "recommendation",
                    "ref": "commercial:contoso:neurosphere:recommendation:rec-0042",
                    "observed_at": None,
                }
            ],
            "idempotency_key": key,
            "channel": channel,
            "dry_run": dry_run,
        }
    )


def passed(check_id: str = "actor_permission", status: str = "passed") -> PrerequisiteResult:
    return PrerequisiteResult.model_validate(
        {
            "check_id": check_id,
            "status": status,
            "detail": None,
            "evaluated_at": "2026-10-20T12:00:01Z",
            "evidence_ids": [],
        }
    )


class FakeClock:
    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now = self.now + delta


def _ids() -> Any:
    counter = itertools.count(1)
    return lambda: f"00000000-0000-4000-8000-{next(counter):012d}"


@dataclass
class Harness:
    store: InMemoryIntentStore = field(default_factory=InMemoryIntentStore)
    auditor: RecordingActionAuditor = field(default_factory=RecordingActionAuditor)
    rechecker: GrantTablePermissionRechecker = field(default_factory=GrantTablePermissionRechecker)
    control: InMemoryExecutionControl = field(default_factory=InMemoryExecutionControl)
    clock: FakeClock = field(default_factory=FakeClock)
    service: ActionService = field(init=False)

    def __post_init__(self) -> None:
        self.service = ActionService(
            self.store,
            auditor=self.auditor,
            rechecker=self.rechecker,
            execution_control=self.control,
            clock=self.clock,
            id_factory=_ids(),
        )
        for principal in (MAKER_ID, CHECKER_ID):
            for permission in ("action.execute", "action.approve"):
                self.rechecker.grant(principal, CUSTOMER, DOMAIN, permission)

    async def drafted(
        self, req: DraftRequest | None = None, who: ActionCaller = MAKER
    ) -> StoredIntent:
        outcome = await self.service.draft(
            who, req or request(), customer_id=CUSTOMER, domain_id=DOMAIN
        )
        return outcome.stored

    async def validated(self, req: DraftRequest | None = None) -> StoredIntent:
        stored = await self.drafted(req)
        return await self.service.record_validation(stored.key, MAKER, [passed()])

    async def awaiting_confirmation(self, req: DraftRequest | None = None) -> StoredIntent:
        stored = await self.validated(req)
        return await self.service.present_confirmation(stored.key, MAKER)

    async def confirm(
        self,
        stored: StoredIntent,
        who: ActionCaller = MAKER,
        *,
        requires_approval: bool = False,
        advisory: bool = False,
        version: str = TARGET_VERSION,
        confirmation_hash: str | None = None,
    ) -> StoredIntent:
        bound = stored.intent.confirmation_hash
        assert bound is not None
        return await self.service.confirm(
            stored.key,
            who,
            confirmation_hash=confirmation_hash or bound.root,
            current_target_version=version,
            requires_approval=requires_approval,
            advisory=advisory,
        )

    async def executing(self, req: DraftRequest | None = None) -> StoredIntent:
        return await self.confirm(await self.awaiting_confirmation(req))

    async def awaiting_approval(self, req: DraftRequest | None = None) -> StoredIntent:
        return await self.confirm(await self.awaiting_confirmation(req), requires_approval=True)

    async def current(self, key: IntentKey) -> StoredIntent:
        return await self.service.get(key)

    def transitions(self) -> list[tuple[str | None, str | None]]:
        return [
            (e.from_state, e.to_state)
            for e in self.auditor.events
            if e.kind == "after" and e.to_state is not None
        ]

    def denials(self) -> list[tuple[str, str | None]]:
        return [(e.operation, e.reason) for e in self.auditor.events if e.kind == "denied"]
