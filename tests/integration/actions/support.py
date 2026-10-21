"""Builders for the PRP-17 item 7a in-process vertical slice. No network, no emulator.

The REAL stack end to end, with in-memory stores at the edges:

* ``create_app`` with the dev-issuer JWT validator, the policy-derived ``IdentityScope`` and the
  routers from the default registry (``/api/v1/actions``, ``/api/v1/review``);
* ``configure_action_plane`` over in-memory intent, HITL and audit stores, a
  ``PolicyPermissionRechecker`` reading the SAME in-memory policy repository the API derives
  scope from, and ``RecheckerReviewerAuthorizer``;
* the REAL item 5 ``FoundryModelSwapConnector`` over its ``httpx.MockTransport`` fake ARM
  (loaded by file path from ``connectors/reference/foundry-actions/tests``: that directory is
  not a package and its module name would collide with nothing else in a single pytest session);
* the REAL ``ActionExecutor`` with the review-item completion hook.

People (customer ``contoso``): ALICE steward (maker), BOB steward (checker), CAROL viewer,
DAVE admin (kill switch).
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
from neurosphere_api.actions import PREFIX, ActionApiSettings, configure_action_plane
from neurosphere_api.hitl import PREFIX as REVIEW_PREFIX
from neurosphere_api.hitl import RecheckerReviewerAuthorizer
from neurosphere_connector.write import WriteConnector, WriteTargetRegistry
from neurosphere_connector_foundry_actions import (
    AccountRef,
    FoundryModelSwapConnector,
    create_swap_connector,
)
from neurosphere_core.actions import (
    ActionService,
    AuditRepositoryActionAuditor,
    InMemoryExecutionControl,
    InMemoryIntentStore,
    IntentKey,
)
from neurosphere_core.actions.audit import action_audit_chain_id
from neurosphere_core.actions.recheck import PolicyPermissionRechecker
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope import PrincipalPolicy, Role
from neurosphere_core.cloud import CloudName
from neurosphere_core.hitl import (
    DecisionLog,
    HitlService,
    InMemoryDecisionStore,
    InMemoryHitlStore,
    ReviewPolicyRegistry,
)
from neurosphere_workers.actions import ActionExecutor, ExecutionReport, ReviewItemCompletion

ALICE: Final[str] = helpers.ALICE
BOB: Final[str] = helpers.BOB
CAROL: Final[str] = helpers.CAROL
DAVE: Final[str] = helpers.NOBODY
FINANCE: Final[str] = helpers.FINANCE
CUSTOMER: Final[str] = helpers.CUSTOMER
CHAIN: Final[str] = action_audit_chain_id(CUSTOMER, FINANCE)

KIND: Final = "model_deployment_swap"
TARGET_ID: Final = f"commercial:{CUSTOMER}:foundry:model_deployment:dep1"
GOV_TARGET_ID: Final = f"government:{CUSTOMER}:foundry:model_deployment:dep1"
TARGET_VERSION: Final = "etag-1"
SWAP_OPERATIONS: Final = [
    {"op": "test", "path": "/properties/model/name", "value": "gpt-4o"},
    {"op": "replace", "path": "/properties/model/name", "value": "gpt-4.1"},
    {"op": "replace", "path": "/properties/model/version", "value": "2025-04-14"},
]

_FAKES_PATH: Final = (
    Path(__file__).resolve().parents[3]
    / "connectors"
    / "reference"
    / "foundry-actions"
    / "tests"
    / "foundry_swap_fakes.py"
)
_FAKES_NAME: Final = "ns_slice_foundry_swap_fakes"


def load_foundry_fakes() -> ModuleType:
    """The item 5 fake ARM module, loaded by path (no sys.path edit, no name collision)."""
    existing = sys.modules.get(_FAKES_NAME)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(_FAKES_NAME, _FAKES_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - path is in the repo
        raise ImportError(f"cannot load {_FAKES_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_FAKES_NAME] = module
    spec.loader.exec_module(module)
    return module


FAKES = load_foundry_fakes()
ACCOUNT: AccountRef = FAKES.ACCOUNT


class MismatchingArm(FAKES.FakeArm):  # type: ignore[misc, name-defined]
    """After the FIRST PUT the deployment reports another model version than was written."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.mismatch_after_first_put = False

    def _put(self, request: Any) -> Any:
        response = super()._put(request)
        if self.mismatch_after_first_put and len(self.puts) == 1:
            self.state["properties"]["model"]["version"] = "1999-01-01"
        return response


class SetRevocation:
    """In-memory revocation list: the deriver and the rechecker consult the SAME one."""

    def __init__(self) -> None:
        self.revoked: set[str] = set()

    async def is_revoked(self, principal_id: str, issued_at: datetime) -> bool:
        return principal_id in self.revoked


def principal(object_id: str) -> str:
    return str(helpers.principal_id_for(object_id))


def swap_body(
    key: str = "idem-2026-10-20-dep1-swap-0001",
    *,
    target_id: str = TARGET_ID,
    channel: str = "rest",
) -> dict[str, Any]:
    return {
        "action_kind": KIND,
        "target": {"canonical_id": target_id, "entity_type": "model_deployment"},
        "target_version": TARGET_VERSION,
        "proposed_diff": {"format": "json_patch", "operations": SWAP_OPERATIONS},
        "evidence": [],
        "idempotency_key": key,
        "channel": channel,
    }


def problem(response: Any) -> dict[str, Any]:
    assert response.headers["content-type"].startswith("application/problem+json"), response.text
    return response.json()


def run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


@dataclass
class Slice:
    h: Any
    arm: Any
    connector: WriteConnector
    registry: WriteTargetRegistry
    intents: InMemoryIntentStore
    audit: AuditRepository
    hitl: HitlService
    control: InMemoryExecutionControl
    revocation: SetRevocation
    service: ActionService
    executor: ActionExecutor
    policies: dict[str, PrincipalPolicy] = field(default_factory=dict[str, PrincipalPolicy])
    advisory: bool = False

    # -- HTTP --------------------------------------------------------------------------------

    def call(self, method: str, who: str | None, path: str, **kwargs: Any) -> Any:
        headers = self.h.auth(who) if who else {}
        return self.h.client.request(method, f"{PREFIX}{path}", headers=headers, **kwargs)

    def review(self, method: str, who: str | None, path: str, **kwargs: Any) -> Any:
        headers = self.h.auth(who) if who else {}
        return self.h.client.request(method, f"{REVIEW_PREFIX}{path}", headers=headers, **kwargs)

    def step(self, who: str, intent_id: str, verb: str, body: Any = None) -> Any:
        return self.call("POST", who, f"/domains/{FINANCE}/intents/{intent_id}/{verb}", json=body)

    def intent(self, intent_id: str, who: str = CAROL) -> dict[str, Any]:
        response = self.call("GET", who, f"/domains/{FINANCE}/intents/{intent_id}")
        assert response.status_code == 200, response.text
        return response.json()

    def draft(self, who: str = ALICE, body: dict[str, Any] | None = None) -> Any:
        return self.call("POST", who, f"/domains/{FINANCE}/intents", json=body or swap_body())

    # -- lifecycle shortcuts -----------------------------------------------------------------

    def presented(self, body: dict[str, Any] | None = None) -> dict[str, Any]:
        drafted = self.draft(body=body)
        assert drafted.status_code == 201, drafted.text
        intent_id = drafted.json()["intent"]["intent_id"]
        validated = self.step(ALICE, intent_id, "validate")
        assert validated.status_code == 200, validated.text
        presented = self.step(ALICE, intent_id, "confirmation")
        assert presented.status_code == 200, presented.text
        return presented.json()

    def awaiting_approval(self, body: dict[str, Any] | None = None) -> dict[str, Any]:
        view = self.presented(body)
        confirmed = self.step(
            ALICE,
            view["intent"]["intent_id"],
            "confirm",
            {"confirmation_hash": view["intent"]["confirmation_hash"]},
        )
        assert confirmed.status_code == 200, confirmed.text
        return confirmed.json()

    def approve(self, view: dict[str, Any], who: str = BOB) -> Any:
        return self.step(
            who,
            view["intent"]["intent_id"],
            "decisions",
            {
                "decision": "approved",
                "reason": "checked the diff",
                "confirmation_hash": view["intent"]["confirmation_hash"],
            },
        )

    def executing(self, body: dict[str, Any] | None = None) -> dict[str, Any]:
        view = self.awaiting_approval(body)
        approved = self.approve(view)
        assert approved.status_code == 200, approved.text
        assert approved.json()["intent"]["state"] == "executing"
        return view

    # -- worker ------------------------------------------------------------------------------

    def key(self, view: dict[str, Any]) -> IntentKey:
        return IntentKey(CUSTOMER, FINANCE, view["intent"]["intent_id"])

    def execute(self, view: dict[str, Any]) -> ExecutionReport:
        return run(self.executor.execute(self.key(view)))

    def review_state(self, view: dict[str, Any]) -> str:
        item = run(self.hitl.get(view["review_item_id"]))
        assert item is not None
        return item.state_name

    def audit_records(self) -> list[Any]:
        return run(self.audit.read_range(CHAIN, limit=500))

    def revoke_maker(self) -> None:
        """Remove ALICE's steward role from the live policy (what the rechecker reads)."""
        current = self.policies[ALICE]
        stripped = current.model_copy(update={"role_assignments": ()})
        self.h.repo.put_principal(stripped)


def _clock_for(h: Any) -> Any:
    return lambda: datetime.fromtimestamp(h.clock(), UTC)


def make_slice(
    *,
    permissions: dict[str, Any] | None = None,
    arm: Any = None,
    account: AccountRef | None = None,
    settings: ActionApiSettings | None = None,
) -> Slice:
    """Build the whole stack. ``permissions``: ARM permissions answer (READ_PERMS = advisory)."""
    fake_arm: Any = arm if arm is not None else MismatchingArm(put_state="Succeeded")
    if permissions is not None:
        fake_arm.permissions = permissions
    policies = {
        ALICE: helpers.policy(ALICE, helpers.role(Role.DOMAIN_STEWARD, FINANCE)),
        BOB: helpers.policy(BOB, helpers.role(Role.DOMAIN_STEWARD, FINANCE)),
        CAROL: helpers.policy(CAROL, helpers.role(Role.VIEWER, FINANCE)),
        DAVE: helpers.policy(DAVE, helpers.role(Role.ADMIN, FINANCE)),
    }
    revocation = SetRevocation()
    h = helpers.harness(*policies.values(), routers={}, revocation_checker=revocation)
    clock = _clock_for(h)

    rechecker = PolicyPermissionRechecker(
        cloud=CloudName.COMMERCIAL,
        policy_repository=h.repo,
        revocation_checker=revocation,
        clock=clock,
    )
    audit = AuditRepository(InMemoryAuditStore())
    intents = InMemoryIntentStore()
    control = InMemoryExecutionControl()
    service = ActionService(
        intents,
        auditor=AuditRepositoryActionAuditor(audit),
        rechecker=rechecker,
        execution_control=control,
        clock=clock,
    )
    review_policies = ReviewPolicyRegistry()
    hitl = HitlService(
        InMemoryHitlStore(),
        DecisionLog(audit, InMemoryDecisionStore()),
        audit,
        review_policies,
        RecheckerReviewerAuthorizer(rechecker),
    )

    connector = run(
        create_swap_connector(
            account or ACCOUNT,
            FAKES.FakeCredential(),
            client=fake_arm.client(),
            sleep=_no_sleep,
            clock=lambda: 0.0,
            today=lambda: date(2026, 10, 20),
        )
    )
    registry = WriteTargetRegistry()
    advisory = connector.advisory
    if not advisory:
        assert isinstance(connector, FoundryModelSwapConnector)
        registry.register(connector)

    configure_action_plane(
        h.app,
        action_service=service,
        intent_store=intents,
        hitl_service=hitl,
        review_policies=review_policies,
        write_targets=registry,
        permission_rechecker=rechecker,
        execution_control=control,
        audit_repository=audit,
        settings=settings,
        clock=clock,
    )
    executor = ActionExecutor(
        service,
        registry,
        execution_control=control,
        worker_id="slice-worker-1",
        clock=clock,
        on_finished=ReviewItemCompletion(
            hitl, auditor=AuditRepositoryActionAuditor(audit), clock=clock
        ),
    )
    return Slice(
        h=h,
        arm=fake_arm,
        connector=connector,
        registry=registry,
        intents=intents,
        audit=audit,
        hitl=hitl,
        control=control,
        revocation=revocation,
        service=service,
        executor=executor,
        policies=policies,
        advisory=advisory,
    )


async def _no_sleep(seconds: float) -> None:
    return None


__all__ = [
    "ACCOUNT",
    "ALICE",
    "BOB",
    "CAROL",
    "CHAIN",
    "CUSTOMER",
    "DAVE",
    "FAKES",
    "FINANCE",
    "GOV_TARGET_ID",
    "KIND",
    "TARGET_ID",
    "TARGET_VERSION",
    "MismatchingArm",
    "Slice",
    "make_slice",
    "principal",
    "problem",
    "run",
    "swap_body",
]
