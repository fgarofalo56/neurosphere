"""Test support for the action executor: a counting fake write connector, a faulty store, fakes.

The fake connector keeps the target state in memory and counts every call, so a test can prove
"zero connector calls" or "apply exactly once". ``SimulatedCrash`` is a ``BaseException`` so it
passes through the executor's ``except Exception`` handlers exactly as a process death would:
nothing after it runs, and the store keeps whatever was durably written before it.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

import httpx
from azure.core.credentials import AccessToken
from neurosphere_connector import build_manifest
from neurosphere_connector.write import (
    ApplyResult,
    DryRunResult,
    RollbackResult,
    VerifyResult,
    WriteRequest,
    WriteTargetRegistry,
    build_verify_result,
)
from neurosphere_connector_foundry_actions import (
    AccountRef,
    ArmClient,
    FoundryModelSwapConnector,
)
from neurosphere_contracts.connectors.v1.connector_manifest import ConnectorManifest, Granularity
from neurosphere_core.actions import (
    ActionCaller,
    ActionService,
    CreateOutcome,
    DraftRequest,
    GrantTablePermissionRechecker,
    InMemoryExecutionControl,
    InMemoryIntentStore,
    IntentKey,
    RecordingActionAuditor,
    StoredIntent,
)
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.errors import StaleVersionError
from neurosphere_core.paging import Page
from neurosphere_workers.actions import ActionExecutor, CanaryProbe

CUSTOMER = "contoso"
DOMAIN = "commercial:contoso:catalog:domain:retail"
TARGET_ID = "commercial:contoso:foundry:model_deployment:dep1"
TARGET_VERSION = "etag-1"
MAKER_ID = "commercial:contoso:entra:person:p-maker0000000001"
ACTION_KIND = "model_deployment_swap"
FAKE_CONNECTOR = "fake-swap"
START = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
SWAP_OPS: list[dict[str, Any]] = [
    {"op": "replace", "path": "/properties/model/name", "value": "gpt-4.1"},
    {"op": "replace", "path": "/properties/model/version", "value": "2025-04-14"},
]


class SimulatedCrash(BaseException):
    """Process death at an injected point (not an ``Exception``: nothing handles it)."""


class FakeClock:
    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now = self.now + delta


def maker() -> ActionCaller:
    return ActionCaller.model_validate(
        {
            "principal_id": MAKER_ID,
            "actor": {
                "principal_pseudonym": "p-maker01",
                "principal_kind": "user",
                "on_behalf_of": None,
            },
            "scope_hash": "sha256:" + "a" * 64,
            "correlation_id": "corr-exec-0001",
            "channel": "rest",
        }
    )


def draft_request(
    *,
    key: str = "idem-executor-0001",
    operations: Sequence[dict[str, Any]] | None = None,
    action_kind: str = ACTION_KIND,
    target_version: str = TARGET_VERSION,
    dry_run: bool = False,
) -> DraftRequest:
    return DraftRequest.model_validate(
        {
            "action_kind": action_kind,
            "target": {"canonical_id": TARGET_ID, "entity_type": "model_deployment"},
            "target_version": target_version,
            "proposed_diff": {
                "format": "json_patch",
                "operations": list(operations if operations is not None else SWAP_OPS),
            },
            "evidence": [],
            "idempotency_key": key,
            "channel": "rest",
            "dry_run": dry_run,
        }
    )


# -- counting fake connector ----------------------------------------------------------------


def _initial_state() -> dict[str, Any]:
    return {
        "etag": TARGET_VERSION,
        "properties": {"model": {"format": "OpenAI", "name": "gpt-4o", "version": "2024-08-06"}},
    }


class CountingConnector:
    """In-memory write target that counts calls. Knobs simulate failures and crashes."""

    def __init__(self, name: str = FAKE_CONNECTOR, *, advisory: bool = False) -> None:
        self._name = name
        self._advisory = advisory
        self.state: dict[str, Any] = _initial_state()
        self.calls: list[str] = []
        self.apply_noop = False  # "pretend change": apply reports success, target unchanged
        self.apply_error: Exception | None = None
        self.crash_in_apply: Literal["before_write", "after_write"] | None = None
        self.dry_run_error: Exception | None = None
        self.verify_error: Exception | None = None
        self.rollback_error: Exception | None = None
        self.crash_in_verify = False
        self.drift_after_verify: int | None = None  # verify call number after which state drifts
        self._etag_n = 1

    # counters
    def count(self, name: str) -> int:
        return self.calls.count(name)

    @property
    def manifest(self) -> ConnectorManifest:
        return build_manifest(
            name=self._name,
            version="0.0.1",
            capabilities=["health_reporting"],
            supported_clouds=["commercial"],
            granularity=Granularity(time_grain="unknown", subject_level="deployment"),
            write_actions=[] if self._advisory else [ACTION_KIND],
        )

    @property
    def advisory(self) -> bool:
        return self._advisory

    def _model(self) -> dict[str, Any]:
        return self.state["properties"]["model"]

    async def dry_run(self, request: WriteRequest) -> DryRunResult:
        self.calls.append("dry_run")
        if self.dry_run_error is not None:
            raise self.dry_run_error
        if self.state["etag"] != request.target_version:
            raise StaleVersionError("target changed", reason="target_version_changed")
        return DryRunResult(
            target=request.target,
            target_version=request.target_version,
            planned_diff=request.proposed_diff,
            would_change=True,
        )

    async def apply(self, request: WriteRequest) -> ApplyResult:
        self.calls.append("apply")
        if self.crash_in_apply == "before_write":
            raise SimulatedCrash("apply: before write")
        if self.apply_error is not None:
            raise self.apply_error
        if self.state["etag"] != request.target_version:
            raise StaleVersionError("target changed", reason="target_version_changed")
        prior = dict(self._model())
        if not self.apply_noop:
            for op in request.proposed_diff.operations:
                self._model()[op.path.rsplit("/", 1)[1]] = op.value
            self._etag_n += 1
            self.state["etag"] = f"etag-{self._etag_n}"
        if self.crash_in_apply == "after_write":
            raise SimulatedCrash("apply: after write, before the result returned")
        return ApplyResult(
            target=request.target,
            version_before=request.target_version,
            version_after=self.state["etag"],
            applied_diff=request.proposed_diff,
            rollback_token=json.dumps(prior, sort_keys=True),
        )

    async def verify(self, request: WriteRequest) -> VerifyResult:
        self.calls.append("verify")
        if self.crash_in_verify:
            raise SimulatedCrash("verify")
        if self.verify_error is not None:
            raise self.verify_error
        result = build_verify_result(
            request, copy.deepcopy(self.state), observed_version=self.state["etag"]
        )
        if self.drift_after_verify is not None and self.count("verify") == self.drift_after_verify:
            self._model()["version"] = "drifted"
        return result

    async def rollback(self, applied: ApplyResult) -> RollbackResult:
        self.calls.append("rollback")
        if self.rollback_error is not None:
            raise self.rollback_error
        if applied.rollback_token is None:
            raise StaleVersionError("no rollback token", reason="bad_rollback_token")
        self.state["properties"]["model"] = json.loads(applied.rollback_token)
        self._etag_n += 1
        self.state["etag"] = f"etag-{self._etag_n}"
        return RollbackResult(
            target=applied.target, status="rolled_back", version_after=self.state["etag"]
        )


# -- faulty store -----------------------------------------------------------------------------


class FaultyStore:
    """Wraps the in-memory store; ``crash_when`` raises ``SimulatedCrash`` around a replace."""

    def __init__(self, inner: InMemoryIntentStore | None = None) -> None:
        self.inner = inner or InMemoryIntentStore()
        self.crash_when: Callable[[StoredIntent], bool] | None = None
        self.crash_after_write = False

    async def create(self, stored: StoredIntent) -> CreateOutcome:
        return await self.inner.create(stored)

    async def get(self, customer_id: str, domain_id: str, intent_id: str) -> StoredIntent | None:
        return await self.inner.get(customer_id, domain_id, intent_id)

    async def find_by_idempotency_key(
        self, principal_id: str, idempotency_key: str, *, customer_id: str
    ) -> StoredIntent | None:
        return await self.inner.find_by_idempotency_key(
            principal_id, idempotency_key, customer_id=customer_id
        )

    async def replace(self, stored: StoredIntent, *, if_match: str) -> StoredIntent:
        trigger = self.crash_when is not None and self.crash_when(stored)
        if trigger and not self.crash_after_write:
            self.crash_when = None
            raise SimulatedCrash("store: before write")
        saved = await self.inner.replace(stored, if_match=if_match)
        if trigger:
            self.crash_when = None
            raise SimulatedCrash("store: after write")
        return saved

    async def list(
        self,
        customer_id: str,
        domain_id: str,
        *,
        state: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[StoredIntent]:
        return await self.inner.list(
            customer_id, domain_id, state=state, cursor=cursor, limit=limit
        )

    async def list_in_states(
        self,
        states: Sequence[str],
        *,
        due_before: datetime | None = None,
        limit: int = 50,
    ) -> list[StoredIntent]:
        return await self.inner.list_in_states(states, due_before=due_before, limit=limit)


def phase_is(phase: str, **fields: Any) -> Callable[[StoredIntent], bool]:
    def match(stored: StoredIntent) -> bool:
        record = stored.execution
        if record is None or record.phase != phase:
            return False
        return all(getattr(record, k) == v for k, v in fields.items())

    return match


# -- harness ----------------------------------------------------------------------------------


@dataclass
class Harness:
    connector: CountingConnector = field(default_factory=CountingConnector)
    store: FaultyStore = field(default_factory=FaultyStore)
    auditor: RecordingActionAuditor = field(default_factory=RecordingActionAuditor)
    rechecker: GrantTablePermissionRechecker = field(default_factory=GrantTablePermissionRechecker)
    control: InMemoryExecutionControl = field(default_factory=InMemoryExecutionControl)
    clock: FakeClock = field(default_factory=FakeClock)
    registry: WriteTargetRegistry = field(default_factory=WriteTargetRegistry)
    service: ActionService = field(init=False)

    def __post_init__(self) -> None:
        self.service = ActionService(
            self.store,
            auditor=self.auditor,
            rechecker=self.rechecker,
            execution_control=self.control,
            clock=self.clock,
        )
        self.rechecker.grant(MAKER_ID, CUSTOMER, DOMAIN, "action.execute")
        if not self.connector.advisory:
            self.registry.register(self.connector)

    def executor(
        self,
        worker_id: str = "exec-1",
        *,
        canary: CanaryProbe | None = None,
        table: dict[str, str] | None = None,
    ) -> ActionExecutor:
        return ActionExecutor(
            self.service,
            self.registry,
            execution_control=self.control,
            worker_id=worker_id,
            action_connectors=table if table is not None else {ACTION_KIND: FAKE_CONNECTOR},
            canary=canary,
            clock=self.clock,
        )

    async def executing(self, request: DraftRequest | None = None) -> IntentKey:
        """Draft -> validated -> awaiting_confirmation -> executing (no approval needed)."""
        from neurosphere_contracts.actions.v1.action_intent import PrerequisiteResult

        who = maker()
        drafted = await self.service.draft(
            who, request or draft_request(), customer_id=CUSTOMER, domain_id=DOMAIN
        )
        check = PrerequisiteResult.model_validate(
            {
                "check_id": "actor_permission",
                "status": "passed",
                "detail": None,
                "evaluated_at": "2026-10-20T12:00:00Z",
                "evidence_ids": [],
            }
        )
        validated = await self.service.record_validation(drafted.stored.key, who, [check])
        presented = await self.service.present_confirmation(validated.key, who)
        bound = presented.intent.confirmation_hash
        assert bound is not None
        confirmed = await self.service.confirm(
            presented.key,
            who,
            confirmation_hash=bound.root,
            current_target_version=presented.intent.target_version,
            requires_approval=False,
            advisory=False,
        )
        assert confirmed.state == "executing"
        return confirmed.key

    async def current(self, key: IntentKey) -> StoredIntent:
        return await self.service.get(key)

    def exec_events(self, kind: str | None = None) -> list[tuple[str, str | None, str | None]]:
        """(kind, phase, reason) of executor phase audit records, in order."""
        return [
            (e.kind, e.phase, e.reason)
            for e in self.auditor.events
            if e.operation == "action.execute"
            and e.phase is not None
            and (kind is None or e.kind == kind)
        ]

    def denials(self) -> list[tuple[str, str | None]]:
        return [(e.operation, e.reason) for e in self.auditor.events if e.kind == "denied"]

    def final_transition(self) -> tuple[str | None, str | None, str | None]:
        last = [e for e in self.auditor.events if e.kind == "after" and e.to_state is not None]
        event = last[-1]
        return (event.from_state, event.to_state, event.reason)


# -- Foundry reference connector over httpx.MockTransport -------------------------------------

SUB = "00000000-1111-2222-3333-444444444444"
FOUNDRY_ACCOUNT = AccountRef(
    cloud=CloudName.COMMERCIAL,
    subscription_id=SUB,
    resource_group="rg-ai",
    account="acct1",
    location="eastus2",
)
FOUNDRY_SWAP_OPS: list[dict[str, Any]] = [
    {"op": "test", "path": "/properties/model/name", "value": "gpt-4o"},
    {"op": "replace", "path": "/properties/model/name", "value": "gpt-4.1"},
    {"op": "replace", "path": "/properties/model/version", "value": "2025-04-14"},
]


def _model_entry(name: str, version: str, caps: dict[str, str]) -> dict[str, Any]:
    return {
        "kind": "OpenAI",
        "skuName": "S0",
        "model": {
            "format": "OpenAI",
            "name": name,
            "version": version,
            "capabilities": caps,
            "lifecycleStatus": "GenerallyAvailable",
            "skus": [{"name": "Standard", "capacity": {"default": 1}}],
        },
    }


class FakeArm:
    """Scripted ARM for one deployment (``dep1``); counts PUTs; no network."""

    def __init__(self) -> None:
        self.state: dict[str, Any] = {
            "id": "/subscriptions/x/deployments/dep1",
            "name": "dep1",
            "type": "Microsoft.CognitiveServices/accounts/deployments",
            "etag": TARGET_VERSION,
            "sku": {"name": "Standard", "capacity": 3},
            "properties": {
                "model": {"format": "OpenAI", "name": "gpt-4o", "version": "2024-08-06"},
                "provisioningState": "Succeeded",
                "versionUpgradeOption": "NoAutoUpgrade",
                "raiPolicyName": "Microsoft.Default",
                "capabilities": {"chatCompletion": "true"},
            },
        }
        self.models = [
            _model_entry("gpt-4o", "2024-08-06", {"chatCompletion": "true"}),
            _model_entry("gpt-4.1", "2025-04-14", {"chatCompletion": "true", "agents": "true"}),
        ]
        self.requests: list[httpx.Request] = []
        self.fail_put_number: int | None = None
        self._etag_n = 1

    @property
    def puts(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == "PUT"]

    def model(self) -> dict[str, Any]:
        return self.state["properties"]["model"]

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/models"):
            return httpx.Response(200, json={"value": self.models})
        if path.endswith("/deployments/dep1"):
            if request.method == "PUT":
                if self.fail_put_number is not None and len(self.puts) == self.fail_put_number:
                    return httpx.Response(500, json={"error": {"code": "InternalServerError"}})
                body = json.loads(request.content)
                self._etag_n += 1
                self.state["etag"] = f"etag-{self._etag_n}"
                self.state["properties"]["model"] = body["properties"]["model"]
            return httpx.Response(200, json=self.state)
        return httpx.Response(404, json={"error": {"code": "NotFound"}})


class FakeCredential:
    async def get_token(self, *scopes: str, **_: Any) -> AccessToken:
        return AccessToken("fake-token-not-a-secret", 0)

    async def close(self) -> None:
        return None


async def _no_sleep(seconds: float) -> None:
    return None


def foundry_connector(arm: FakeArm) -> FoundryModelSwapConnector:
    return FoundryModelSwapConnector(
        FOUNDRY_ACCOUNT,
        ArmClient(FOUNDRY_ACCOUNT, FakeCredential(), client=arm.client()),  # type: ignore[arg-type]
        sleep=_no_sleep,
        clock=lambda: 0.0,
        today=lambda: date(2026, 10, 20),
    )
