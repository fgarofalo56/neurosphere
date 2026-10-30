"""Catalog MCP server publish/unpublish drafts and the publication record (PRP-34 item 6).

Offline: the REAL authz stack and app, the real ``ActionService`` over in-memory stores, the
in-memory catalog repository and gateway store, and the REAL APIM write connector with the
``mcp_server`` translator over ``InMemoryApim``. The routes only draft; the tests play the
executor (dry run, apply, verify against the in-memory gateway, then mark the intent succeeded)
so the publication record is proven against a real gateway change.

People (customer ``contoso``): STEWARD (domain steward of FINANCE: ``action.propose``), VIEWER
(viewer of FINANCE), OUTSIDER (domain steward of OPERATIONS only).

This directory has no ``__init__.py``: import by module name.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

_TESTS = Path(__file__).resolve().parents[1]
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

import authz.authz_helpers as helpers  # noqa: E402  # pyright: ignore[reportMissingImports]
import httpx  # noqa: E402
import pytest  # noqa: E402
from neurosphere_api.actions import configure_action_plane  # noqa: E402
from neurosphere_api.catalog import (  # noqa: E402
    get_clock,
    get_repository,
    mcp_publish,
)
from neurosphere_api.gateway import (  # noqa: E402
    GatewayPlane,
    GatewaySettings,
    configure_gateway_plane,
)
from neurosphere_api.hitl import RecheckerReviewerAuthorizer  # noqa: E402
from neurosphere_connector.write import WriteRequest, WriteTargetRegistry  # noqa: E402
from neurosphere_connector_apim_gateway import (  # noqa: E402
    ApimGatewayConnector,
    GatewayRef,
    InMemoryApim,
    InMemoryApplyRecordStore,
)
from neurosphere_connector_apim_gateway import mcp as connector_mcp  # noqa: E402
from neurosphere_contracts.actions.v1.action_intent import ActionIntent  # noqa: E402
from neurosphere_core.actions import (  # noqa: E402
    ActionService,
    ExecutionRecord,
    GrantTablePermissionRechecker,
    InMemoryExecutionControl,
    InMemoryIntentStore,
    RecordingActionAuditor,
    intent_to_wire,
)
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore  # noqa: E402
from neurosphere_core.auth.scope import Role  # noqa: E402
from neurosphere_core.catalog import CatalogEntity  # noqa: E402
from neurosphere_core.catalog.repo import InMemoryCatalogRepository  # noqa: E402
from neurosphere_core.catalog.repo.documents import parse_entity  # noqa: E402
from neurosphere_core.cloud import CloudProfile  # noqa: E402
from neurosphere_core.cloud.profile import CloudName  # noqa: E402
from neurosphere_core.gateway import (  # noqa: E402
    GatewayRegistration,
    InMemoryGatewayStore,
    gateway_id_for,
)
from neurosphere_core.gateway.mode import evaluate_permissions  # noqa: E402
from neurosphere_core.hitl import (  # noqa: E402
    DecisionLog,
    HitlService,
    InMemoryDecisionStore,
    InMemoryHitlStore,
    ReviewPolicyRegistry,
)

STEWARD: Final = helpers.ALICE
VIEWER: Final = helpers.BOB
OUTSIDER: Final = helpers.CAROL
SEEDER: Final = helpers.NOBODY
FINANCE: Final[str] = helpers.FINANCE
OPERATIONS: Final[str] = helpers.OPERATIONS
CUSTOMER: Final[str] = helpers.CUSTOMER
RID: Final = (
    "/subscriptions/00000000-1111-2222-3333-444444444444/resourceGroups/rg-ai"
    "/providers/Microsoft.ApiManagement/service/apim-demo"
)
GATEWAY_ID: Final = gateway_id_for(CUSTOMER, FINANCE, RID)
SERVER_ID: Final = "commercial:contoso:neurosphere:mcp_server:finance/ledger-tools"
BASE: Final = "/api/v1/catalog/mcp-servers"
T0: Final = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
USER_OID: Final = "11111111-2222-4333-8444-555555555555"
_EXAMPLES = Path(__file__).resolve().parents[4] / "packages/contracts/schemas/catalog/v1/examples"
_counter = itertools.count(1)


def _example(name: str) -> dict[str, Any]:
    return json.loads((_EXAMPLES / "valid" / name).read_text(encoding="utf-8"))


def server_doc(**update: Any) -> dict[str, Any]:
    raw = _example("mcp_server.entra-streamable-http.json")
    raw.update(domain_id=FINANCE, owner_id=None)
    raw.update(update)
    return raw


def grant_doc(
    name: str, *, kind: str, oid: str, calls: int | None, **update: Any
) -> dict[str, Any]:
    raw = _example("grant.entra-group-mcp-calls.json")
    raw.update(
        id=f"commercial:contoso:neurosphere:grant:finance/{name}",
        domain_id=FINANCE,
        principal={"kind": kind, "object_id": oid, "display": None if kind == "user" else name},
        limits={"mcp_calls_per_minute": calls},
    )
    raw.update(update)
    return raw


def _ids(prefix: str) -> Callable[[], str]:
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter):012d}"


@dataclass
class Env:
    h: Any
    repo: InMemoryCatalogRepository
    intents: InMemoryIntentStore
    apim: InMemoryApim
    connector: ApimGatewayConnector
    gateways: InMemoryGatewayStore

    def call(self, method: str, who: str | None, path: str, **kw: Any) -> httpx.Response:
        headers = {} if who is None else self.h.auth(who)
        return self.h.client.request(method, path, headers=headers, **kw)

    def publish(self, who: str | None = STEWARD, **body: Any) -> httpx.Response:
        payload = {"idempotency_key": f"idem-mcp-publish-{next(_counter):06d}", **body}
        return self.call("POST", who, f"{BASE}/{SERVER_ID}/publish", json=payload)

    def unpublish(self, who: str | None = STEWARD) -> httpx.Response:
        payload = {"idempotency_key": f"idem-mcp-unpub-{next(_counter):06d}"}
        return self.call("POST", who, f"{BASE}/{SERVER_ID}/unpublish", json=payload)

    def record(self, intent_id: str, who: str | None = STEWARD) -> httpx.Response:
        return self.call(
            "POST",
            who,
            f"{BASE}/{SERVER_ID}/publication-record",
            json={"intent_id": intent_id},
        )

    def seed(self, *docs: dict[str, Any]) -> list[CatalogEntity]:
        async def run() -> list[CatalogEntity]:
            claims = await self.h.validator.authenticate(self.h.auth(SEEDER)["Authorization"])
            scope = (await self.h.deriver.derive(claims)).scope
            return [await self.repo.create_entity(scope, parse_entity(d)) for d in docs]

        return asyncio.run(run())

    def stored_server(self) -> dict[str, Any]:
        async def run() -> dict[str, Any]:
            claims = await self.h.validator.authenticate(self.h.auth(SEEDER)["Authorization"])
            scope = (await self.h.deriver.derive(claims)).scope
            entity = await self.repo.get_entity(scope, SERVER_ID)
            assert entity is not None
            return entity.model_dump(mode="json")

        return asyncio.run(run())

    def execute(self, intent_id: str) -> None:
        """Play the executor: dry run, apply and verify on the gateway, then mark succeeded."""

        async def run() -> None:
            stored = await self.intents.get(CUSTOMER, FINANCE, intent_id)
            assert stored is not None and stored.etag is not None
            intent = stored.intent
            req = WriteRequest(
                target=intent.target,
                target_version=intent.target_version,
                proposed_diff=intent.proposed_diff,
            )
            planned = await self.connector.dry_run(req)
            reviewed = req.model_copy(update={"proposed_diff": planned.planned_diff})
            await self.connector.apply(reviewed)
            assert (await self.connector.verify(reviewed)).matched is True
            wire = intent_to_wire(intent)
            wire["state"] = "succeeded"
            finished = datetime.fromtimestamp(self.h.clock(), UTC)
            done = stored.model_copy(
                update={
                    "intent": ActionIntent.model_validate(wire),
                    "execution": ExecutionRecord(
                        phase="done", verify_matched=True, apply_finished_at=finished
                    ),
                    "due_at": None,
                }
            )
            await self.intents.replace(done, if_match=stored.etag)

        asyncio.run(run())
        self.h.clock.advance(60)


def registration() -> GatewayRegistration:
    allowed = [{"actions": ["Microsoft.ApiManagement/service/*"], "notActions": []}]
    return GatewayRegistration(
        id=GATEWAY_ID,
        customer_id=CUSTOMER,
        domain_id=FINANCE,
        cloud="commercial",
        arm_resource_id=RID,
        name="apim-demo",
        tier="standard_v2",
        created_at=T0,
        updated_at=T0,
        registered_by="pn-admin",
        mode="manage",
        mode_changed_by="pn-earlier",
        mode_changed_at=T0,
        mode_revision=1,
        preflight=evaluate_permissions(allowed, now=T0),
    )


@pytest.fixture
def env() -> Env:
    return make_env()


def make_env(server: dict[str, Any] | None = None) -> Env:
    h = helpers.harness(
        helpers.policy(STEWARD, helpers.role(Role.DOMAIN_STEWARD, FINANCE)),
        helpers.policy(VIEWER, helpers.role(Role.VIEWER, FINANCE)),
        helpers.policy(OUTSIDER, helpers.role(Role.DOMAIN_STEWARD, OPERATIONS)),
        helpers.policy(SEEDER, helpers.role(Role.DOMAIN_STEWARD, FINANCE, OPERATIONS)),
    )

    def clock() -> datetime:
        return datetime.fromtimestamp(h.clock(), UTC)

    audit = AuditRepository(InMemoryAuditStore(), id_factory=_ids("33333333-3333-4333-8333"))
    rechecker = GrantTablePermissionRechecker()
    rechecker.grant(str(helpers.principal_id_for(STEWARD)), CUSTOMER, FINANCE, "action.propose")
    intents = InMemoryIntentStore()
    control = InMemoryExecutionControl()
    actions = ActionService(
        intents,
        auditor=RecordingActionAuditor(),
        rechecker=rechecker,
        execution_control=control,
        clock=clock,
        id_factory=_ids("00000000-0000-4000-8000"),
    )
    policies = ReviewPolicyRegistry()
    hitl = HitlService(
        InMemoryHitlStore(),
        DecisionLog(audit, InMemoryDecisionStore()),
        audit,
        policies,
        RecheckerReviewerAuthorizer(rechecker),
        id_factory=_ids("22222222-2222-4222-8222"),
    )
    apim = InMemoryApim()
    for name in (
        connector_mcp.TENANT_NAMED_VALUE,
        f"{mcp_publish.publication_prefix(SERVER_ID)}-audience",
    ):
        apim.seed(
            f"namedValues/{name}",
            {
                "displayName": name,
                "secret": True,
                "keyVault": {"secretIdentifier": "https://kv.vault.azure.net/secrets/" + name},
            },
        )
    gateway = GatewayRef(gateway_id=GATEWAY_ID, cloud=CloudName.COMMERCIAL, arm_resource_id=RID)
    connector = ApimGatewayConnector(
        gateway,
        apim,
        records=InMemoryApplyRecordStore(),
        translators=[
            connector_mcp.McpServerTranslator(paths=connector_mcp.InMemoryApiPathIndex(apim))
        ],
    )
    registry = WriteTargetRegistry()
    registry.register(connector)
    configure_action_plane(
        h.app,
        action_service=actions,
        intent_store=intents,
        hitl_service=hitl,
        review_policies=policies,
        write_targets=registry,
        permission_rechecker=rechecker,
        execution_control=control,
        audit_repository=audit,
        clock=clock,
    )
    store = InMemoryGatewayStore()
    asyncio.run(store.create(registration()))

    def factory(profile: CloudProfile) -> httpx.AsyncClient:
        raise AssertionError("the publish API never calls ARM")

    configure_gateway_plane(
        h.app,
        GatewayPlane(store=store, audit=audit, arm_factory=factory, settings=GatewaySettings()),
    )
    repo = InMemoryCatalogRepository()
    h.app.state.audit_repository = audit
    h.app.dependency_overrides[get_repository] = lambda: repo
    h.app.dependency_overrides[get_clock] = lambda: clock
    out = Env(h=h, repo=repo, intents=intents, apim=apim, connector=connector, gateways=store)
    out.seed(
        server if server is not None else server_doc(),
        grant_doc("user-grant", kind="user", oid=USER_OID, calls=30),
        grant_doc(
            "group-grant", kind="entra_group", oid="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", calls=60
        ),
        grant_doc(
            "disabled",
            kind="user",
            oid="22222222-2222-4333-8444-555555555555",
            calls=5,
            enabled=False,
        ),
    )
    return out


def _problem(response: httpx.Response) -> dict[str, Any]:
    assert response.headers["content-type"].startswith("application/problem+json"), response.text
    return response.json()


def _publication(view: dict[str, Any]) -> dict[str, Any]:
    ops = view["action"]["intent"]["proposed_diff"]["operations"]
    assert [op["path"] for op in ops] == ["/publication"]
    return ops[0]["value"]


# -- authorization ------------------------------------------------------------------------


def test_drafting_needs_action_propose_on_the_servers_domain(env: Env) -> None:
    assert env.publish(None, gateway_id=GATEWAY_ID, api_path="ledger").status_code == 401
    assert env.publish(VIEWER, gateway_id=GATEWAY_ID, api_path="ledger").status_code == 403
    assert env.publish(OUTSIDER, gateway_id=GATEWAY_ID, api_path="ledger").status_code == 403
    assert env.unpublish(VIEWER).status_code == 403
    assert env.unpublish(OUTSIDER).status_code == 403
    assert env.record("00000000-0000-4000-8000-000000000001", VIEWER).status_code == 403
    assert env.record("00000000-0000-4000-8000-000000000001", OUTSIDER).status_code == 403
    # Nothing was drafted by any refused caller.
    page = asyncio.run(env.intents.list(CUSTOMER, FINANCE))
    assert list(page.items) == []


def test_status_needs_data_read_and_states_zero_body_bytes(env: Env) -> None:
    assert env.call("GET", OUTSIDER, f"{BASE}/{SERVER_ID}/publication").status_code == 403
    response = env.call("GET", VIEWER, f"{BASE}/{SERVER_ID}/publication")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "unpublished" and body["next_publish_stage"] == "publish"
    assert body["next_unpublish_stage"] is None
    assert any("zero body bytes" in note for note in body["diagnostics"])


# -- drafting -----------------------------------------------------------------------------


def test_publish_drafts_an_intent_through_the_action_flow(env: Env) -> None:
    response = env.publish(gateway_id=GATEWAY_ID, api_path="ledger")
    assert response.status_code == 201, response.text
    view = response.json()
    intent = view["action"]["intent"]
    assert intent["action_kind"] == "mcp_server_publish"
    assert intent["state"] == "drafted"
    assert intent["target"] == {"canonical_id": SERVER_ID, "entity_type": "mcp_server"}
    assert intent["target_version"] == "mcp-absent"
    assert view["action"]["advisory"] is False
    pub = _publication(view)
    assert pub["stage"] == "publish" and pub["gateway_id"] == GATEWAY_ID
    assert pub["url"] == "https://ledger-tools.contoso.example/mcp"
    assert pub["audience"] == "api://ledger-tools"
    # Only the enabled direct grant; the group grant is reported, the disabled one dropped.
    assert pub["grants"] == [{"oid": USER_OID, "calls_per_minute": 30}]
    notes = " ".join(view["diagnostics"])
    assert "zero body bytes" in notes and "group grant" in notes
    # The drafted intent is the one the action API serves (same durable store).
    stored = asyncio.run(env.intents.get(CUSTOMER, FINANCE, intent["intent_id"]))
    assert stored is not None and stored.intent.action_kind == "mcp_server_publish"


def test_the_drafted_intent_validates_through_the_apim_connector_plan(env: Env) -> None:
    intent_id = env.publish(gateway_id=GATEWAY_ID, api_path="ledger").json()["action"]["intent"][
        "intent_id"
    ]
    validated = env.call(
        "POST", STEWARD, f"/api/v1/actions/domains/{FINANCE}/intents/{intent_id}/validate"
    )
    assert validated.status_code == 200, validated.text
    checks = {c["check_id"]: c for c in validated.json()["intent"]["prerequisite_results"]}
    assert checks["write_connector_supported"]["status"] == "passed"
    assert checks["target_dry_run"]["status"] == "passed", checks["target_dry_run"]
    assert env.apim.writes() == []  # the API only plans


def test_publish_refusals(env: Env) -> None:
    missing = env.publish(api_path="ledger")
    assert missing.status_code == 422 and _problem(missing)["reason"] == "gateway_required"
    other = env.publish(gateway_id="gw-" + "c" * 32, api_path="ledger")
    assert _problem(other)["reason"] == "gateway_not_registered"
    no_path = env.publish(gateway_id=GATEWAY_ID)
    assert _problem(no_path)["reason"] == "api_path_required"


@pytest.mark.parametrize(
    ("update", "status", "reason"),
    [
        ({"transport": "sse", "publishable": False}, 409, "mcp_sse_unsupported"),
        (
            {"auth": {"kind": "api_key", "audience": None}, "publishable": False},
            409,
            "mcp_api_key_upstream",
        ),
        ({"auth": {"kind": "entra", "audience": None}}, 422, "mcp_audience_missing"),
        ({"publishable": False}, 409, "mcp_not_publishable"),
    ],
)
def test_unpublishable_servers_are_refused_with_reason(
    update: dict[str, Any], status: int, reason: str
) -> None:
    response = make_env(server_doc(**update)).publish(gateway_id=GATEWAY_ID, api_path="ledger")
    assert response.status_code == status, response.text
    assert _problem(response)["reason"] == reason


def test_unpublish_of_an_unpublished_server_is_refused(env: Env) -> None:
    response = env.unpublish()
    assert response.status_code == 422 and _problem(response)["reason"] == "mcp_not_published"


# -- full cycle: publish, record, deny, remove --------------------------------------------


def _draft_and_run(env: Env, response: httpx.Response) -> str:
    assert response.status_code == 201, response.text
    intent_id = response.json()["action"]["intent"]["intent_id"]
    env.execute(intent_id)
    return intent_id


def test_publication_is_recorded_after_a_real_gateway_change(env: Env) -> None:
    names = connector_mcp.resource_names(SERVER_ID)
    intent_id = _draft_and_run(env, env.publish(gateway_id=GATEWAY_ID, api_path="ledger"))
    for name in names.per_server:
        assert name in env.apim.resources

    recorded = env.record(intent_id)
    assert recorded.status_code == 200, recorded.text
    assert recorded.headers["ETag"]
    doc = env.stored_server()
    assert doc["provenance"]["source_id"] == f"apim-gateway.{GATEWAY_ID}"
    assert doc["provenance"]["method"] == "declared"
    attrs = doc["attributes"]
    assert attrs["mcp_publication_state"] == "published"
    assert attrs["mcp_publication_gateway_id"] == GATEWAY_ID
    assert attrs["mcp_publication_api_path"] == "ledger"
    assert attrs["mcp_publication_intent_id"] == intent_id
    # Ownership recorded matches what the connector created on the gateway.
    assert attrs["mcp_publication_created"].split(",") == list(names.per_server)
    assert attrs["mcp_publication_shared"].split(",") == list(names.shared)
    # Replaying the same record is refused (the state moved on).
    again = env.record(intent_id)
    assert again.status_code == 409 and _problem(again)["reason"] == "publication_state_changed"

    status = env.call("GET", VIEWER, f"{BASE}/{SERVER_ID}/publication").json()
    assert status["state"] == "published" and status["next_unpublish_stage"] == "deny"
    assert status["created_resources"] == list(names.per_server)

    # Unpublish: deny first, recorded, then remove.
    deny = env.unpublish()
    assert deny.json()["stage"] == "deny"
    assert _publication(deny.json()) == {"stage": "deny", "gateway_id": GATEWAY_ID}
    deny_id = _draft_and_run(env, deny)
    assert env.record(deny_id).status_code == 200
    assert env.stored_server()["attributes"]["mcp_publication_state"] == "denied"

    remove = env.unpublish()
    assert remove.json()["stage"] == "remove"
    assert remove.json()["action"]["intent"]["action_kind"] == "mcp_server_unpublish"
    remove_id = _draft_and_run(env, remove)
    assert env.record(remove_id).status_code == 200
    final = env.stored_server()["attributes"]
    assert final["mcp_publication_state"] == "unpublished"
    assert "mcp_publication_created" not in final
    for name in names.per_server:
        assert name not in env.apim.resources
    for name in names.shared:
        assert name in env.apim.resources


def test_a_published_server_is_changed_only_after_a_deny(env: Env) -> None:
    first = _draft_and_run(env, env.publish(gateway_id=GATEWAY_ID, api_path="ledger"))
    assert env.record(first).status_code == 200
    deny = env.publish()
    assert deny.json()["stage"] == "deny"
    assert env.record(_draft_and_run(env, deny)).status_code == 200
    change = env.publish()
    assert change.json()["stage"] == "change"
    assert change.json()["action"]["intent"]["target_version"] == "mcp-denied"
    assert env.record(_draft_and_run(env, change)).status_code == 200
    assert env.stored_server()["attributes"]["mcp_publication_state"] == "published"
    elsewhere = env.publish(gateway_id="gw-" + "d" * 32)
    assert _problem(elsewhere)["reason"] == "mcp_published_elsewhere"


def test_an_intent_applied_before_the_last_record_is_not_recorded_again(env: Env) -> None:
    first = _draft_and_run(env, env.publish(gateway_id=GATEWAY_ID, api_path="ledger"))
    assert env.record(first).status_code == 200
    assert env.record(_draft_and_run(env, env.unpublish())).status_code == 200
    assert env.record(_draft_and_run(env, env.unpublish())).status_code == 200
    # The catalog is back to unpublished (version mcp-absent, as the first intent was drafted),
    # but the first publication was applied before the last record: replaying it is refused.
    replay = env.record(first)
    assert replay.status_code == 409 and _problem(replay)["reason"] == "stale_intent"
    assert env.stored_server()["attributes"]["mcp_publication_state"] == "unpublished"


def test_record_refuses_an_intent_that_did_not_succeed(env: Env) -> None:
    response = env.publish(gateway_id=GATEWAY_ID, api_path="ledger")
    intent_id = response.json()["action"]["intent"]["intent_id"]
    refused = env.record(intent_id)
    assert refused.status_code == 422 and _problem(refused)["reason"] == "intent_not_succeeded"
    missing = env.record("00000000-0000-4000-8000-0000000000ff")
    assert _problem(missing)["reason"] == "intent_not_found"
    assert "mcp_publication_state" not in (env.stored_server().get("attributes") or {})


def test_api_naming_and_stage_versions_match_the_connector() -> None:
    created, shared = mcp_publish.publication_resources(SERVER_ID)
    names = connector_mcp.resource_names(SERVER_ID)
    assert created == names.per_server and shared == names.shared
    assert mcp_publish.publication_prefix(SERVER_ID) == connector_mcp.publication_prefix(SERVER_ID)
    assert dict(mcp_publish.STAGE_VERSIONS) == dict(connector_mcp.STAGE_VERSIONS)
    assert mcp_publish.METADATA_API == connector_mcp.METADATA_API
    assert mcp_publish.TENANT_NAMED_VALUE == connector_mcp.TENANT_NAMED_VALUE
