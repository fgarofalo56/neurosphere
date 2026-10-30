"""PRP-34 item 10 on the executor side: default translators, the kind/grammar tie at resolution,
and the post-success catalog hand-off (outside every executor phase).

* ``build_apim_gateway_connector`` registers the default translators (swap, the ``grant``
  dispatcher with the connector's own apply records, MCP with the gateway's API path index);
* a diff whose grammar is not its action kind's fails at resolution, before any connector call;
* ``PublicationRecordingExecutor`` records a succeeded, verified Grant publication on the catalog
  Grant through ``CatalogPublicationRecorder`` (idempotent), never for dry runs, other connectors
  or unverified intents, and a recording failure is audited and surfaced without touching the
  intent or the gateway.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
from neurosphere_connector.write import WriteRequest
from neurosphere_connector_apim_gateway import ApimGatewayConnector, GrantDispatchTranslator
from neurosphere_connector_apim_gateway.grants import (
    VERSION_PUBLISHED,
    VERSION_UNPUBLISHED,
    GrantPublicationTranslator,
    publication_names,
)
from neurosphere_connector_apim_gateway.mcp import (
    HttpApiPathIndex,
    InMemoryApiPathIndex,
    McpServerTranslator,
)
from neurosphere_connector_apim_gateway.swap import BackendSwapTranslator
from neurosphere_contracts.actions.v1.action_intent import ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.actions import DraftRequest, StoredIntent
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.catalog import CatalogEntity
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.catalog.repo.documents import dump, parse_entity
from neurosphere_core.cloud.profile import CloudName, profile_for
from neurosphere_core.errors import DependencyTransientError, ForbiddenError, InvalidSchemaError
from neurosphere_core.scope import IdentityScope
from neurosphere_workers.actions import DEFAULT_ACTION_CONNECTORS
from neurosphere_workers.actions.apim import (
    PUBLICATION_RECORD_FAILED,
    PUBLICATION_RECORD_OPERATION,
    PublicationRecordingExecutor,
    build_apim_gateway_connector,
    build_http_apim_gateway_connector,
    recordable_publication,
)
from neurosphere_workers.publication import CatalogPublicationRecorder

from .apim_support import GW, ApimWorld, apim_world
from .executor_support import CUSTOMER, DOMAIN, START, CountingConnector, Harness, draft_request

TABLE: Final = dict(DEFAULT_ACTION_CONNECTORS)
_EXAMPLE: Final = (
    Path(__file__).resolve().parents[4]
    / "packages/contracts/schemas/catalog/v1/examples/valid"
    / "grant.user-model-deployment-token-limits.json"
)
GRANT_ID: Final = "commercial:contoso:neurosphere:grant:finance/analyst-gpt-4o"
NAMES: Final = publication_names(GRANT_ID)
OID: Final = "11111111-2222-4333-8444-555555555555"


# -- fixtures ------------------------------------------------------------------------------


def make_scope(role: str = "domain_steward", domains: tuple[str, ...] = (DOMAIN,)) -> IdentityScope:
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "principal": {
            "principal_id": f"commercial:{CUSTOMER}:entra:principal:svc-executor",
            "principal_pseudonym": "svc-executor",
            "principal_kind": "service_principal",
        },
        "roles": [{"role": role, "domain_ids": list(domains)}],
        "allowed_domains": list(domains),
        "allowed_resources": [],
        "policy_version": "v1",
        "derived_at": "2026-10-20T00:00:00Z",
        "scope_hash": "sha256:" + hashlib.sha256(b"svc-executor").hexdigest(),
    }
    return IdentityScope._from_verified_contract(ContractScope.model_validate(payload))  # pyright: ignore[reportPrivateUsage]


class FixedScope:
    def __init__(self, scope: IdentityScope) -> None:
        self.scope = scope

    async def get(self) -> IdentityScope:
        return self.scope


class OneLookup:
    """``ApplyRecordLookup`` over the world's single gateway partition."""

    def __init__(self, world: ApimWorld) -> None:
        self.world = world
        self.asked: list[tuple[str, str]] = []

    def for_domain(self, customer_id: str, domain_id: str) -> Any:
        self.asked.append((customer_id, domain_id))
        return self.world.records


class FakeRecorder:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[StoredIntent] = []

    async def record(self, stored: StoredIntent) -> object:
        self.calls.append(stored)
        if self.error is not None:
            raise self.error
        return None


async def catalog(scope: IdentityScope) -> InMemoryCatalogRepository:
    repo = InMemoryCatalogRepository()
    doc = json.loads(_EXAMPLE.read_text(encoding="utf-8"))
    doc.update(domain_id=DOMAIN)
    await repo.create_entity(scope, parse_entity(doc))
    return repo


async def grant_world() -> ApimWorld:
    world = await apim_world(backends={})
    world.apim.seed("apis/llm", {"displayName": "LLM", "path": "llm"})
    return world


def grant_target() -> TargetRef:
    return TargetRef(canonical_id=GRANT_ID, entity_type="grant")


async def publish_draft(world: ApimWorld, *, key: str = "idem-grant-publish-0001") -> DraftRequest:
    request = WriteRequest(
        target=grant_target(),
        target_version=VERSION_UNPUBLISHED,
        proposed_diff=ProposedDiff.model_validate(
            {
                "format": "json_patch",
                "operations": [
                    {
                        "op": "add",
                        "path": "/publication",
                        "value": {
                            "gateway_id": GW,
                            "api_id": "llm",
                            "access": "subscription",
                            "principal_kind": "user",
                            "principal_object_id": OID,
                            "tokens_per_minute": 20000,
                        },
                    }
                ],
            }
        ),
    )
    planned = await world.connector.dry_run(request)
    world.apim.calls.clear()
    return _draft("grant_publish", request.target_version, planned.planned_diff, key)


def _draft(
    kind: str, version: str, diff: ProposedDiff, key: str, *, dry_run: bool = False
) -> DraftRequest:
    return DraftRequest.model_validate(
        {
            "action_kind": kind,
            "target": grant_target().model_dump(mode="json"),
            "target_version": version,
            "proposed_diff": diff.model_dump(mode="json", by_alias=True, exclude_unset=True),
            "evidence": [],
            "idempotency_key": key,
            "channel": "rest",
            "dry_run": dry_run,
        }
    )


def _executor(
    h: Harness, world: ApimWorld, recorder: Any, **options: Any
) -> PublicationRecordingExecutor:
    return PublicationRecordingExecutor(
        h.service,
        h.registry,
        recorder=recorder,
        auditor=h.auditor,
        execution_control=h.control,
        worker_id="exec-1",
        action_connectors=TABLE,
        clock=h.clock,
        gateways=world.store,
        **options,
    )


def _harness(world: ApimWorld) -> Harness:
    h = Harness(connector=CountingConnector("foundry-model-swap"))
    h.registry.register(world.connector)
    return h


def _attributes(entity: CatalogEntity | None) -> dict[str, Any]:
    assert entity is not None
    return dict(dump(entity).get("attributes") or {})


# -- default composition --------------------------------------------------------------------------


def _translators(connector: object) -> dict[str, Any]:
    assert isinstance(connector, ApimGatewayConnector)
    return dict(connector._translators)  # pyright: ignore[reportPrivateUsage]


async def test_composition_registers_the_default_translators() -> None:
    world = await grant_world()
    translators = _translators(world.connector)
    assert set(translators) == {"apim_gateway", "apim_backend", "grant", "mcp_server"}
    grant = translators["grant"]
    assert isinstance(grant, GrantDispatchTranslator)
    assert isinstance(grant.publication, GrantPublicationTranslator)
    assert grant.publication._records is world.records  # pyright: ignore[reportPrivateUsage]
    assert isinstance(translators["apim_backend"], BackendSwapTranslator)
    mcp = translators["mcp_server"]
    assert isinstance(mcp, McpServerTranslator)
    assert mcp._paths is None  # pyright: ignore[reportPrivateUsage]  # no index: publish refused

    paths = InMemoryApiPathIndex(world.apim)
    with_paths = build_apim_gateway_connector(
        world.registration,
        world.apim,
        store=world.store,
        records=world.records,
        api_paths=paths,
    )
    assert _translators(with_paths)["mcp_server"]._paths is paths  # pyright: ignore[reportPrivateUsage]


async def test_http_composition_lists_api_paths_over_the_same_client() -> None:
    world = await grant_world()
    client = httpx.AsyncClient(base_url="https://management.azure.com")
    try:
        connector = build_http_apim_gateway_connector(
            world.registration,
            client,
            profile=profile_for(CloudName.COMMERCIAL),
            store=world.store,
            records=world.records,
        )
        index = _translators(connector)["mcp_server"]._paths  # pyright: ignore[reportPrivateUsage]
        assert isinstance(index, HttpApiPathIndex)
        assert index._client is client  # pyright: ignore[reportPrivateUsage]
    finally:
        await client.aclose()


# -- kind / grammar tie at resolution --------------------------------------------------------


async def test_a_publish_kind_carrying_an_unpublish_diff_fails_before_any_call() -> None:
    world = await grant_world()
    h = _harness(world)
    removal = ProposedDiff.model_validate(
        {
            "format": "json_patch",
            "operations": [
                {"op": "test", "path": "/publication/gateway_id", "value": GW},
                {"op": "test", "path": "/publication/apply_record", "value": "apply-x"},
                {"op": "test", "path": "/publication/resources", "value": [NAMES.product]},
                {"op": "remove", "path": "/publication"},
            ],
        }
    )
    key = await h.executing(_draft("grant_publish", VERSION_PUBLISHED, removal, "idem-mismatch-01"))
    recorder = FakeRecorder()
    report = await _executor(h, world, recorder).execute(key)
    assert (report.outcome, report.reason) == ("failed", "action_kind_mismatch")
    assert world.apim.calls == []
    assert recorder.calls == []


# -- post-success recording ---------------------------------------------------------------------


async def test_a_verified_publish_is_recorded_on_the_grant() -> None:
    world = await grant_world()
    h = _harness(world)
    scope = make_scope()
    repo = await catalog(scope)
    audit = AuditRepository(InMemoryAuditStore())
    lookup = OneLookup(world)
    recorder = CatalogPublicationRecorder(
        repo, audit, FixedScope(scope), records=lookup, clock=lambda: START
    )
    key = await h.executing(await publish_draft(world))
    report = await _executor(h, world, recorder).execute(key)
    assert (report.outcome, report.reason) == ("succeeded", None)
    assert NAMES.product in world.apim.resources  # the real change
    entity = await repo.get_entity(scope, GRANT_ID)
    attrs = _attributes(entity)
    assert attrs["apim_published"] is True
    assert attrs["apim_gateway_id"] == GW
    assert attrs["apim_intent_id"] == key.intent_id
    assert attrs["apim_ownership"] == "recorded"
    assert NAMES.product in attrs["apim_created"].split(",")
    assert attrs["apim_apply_record"]
    assert entity is not None and dump(entity)["provenance"]["source_id"] == GW
    assert lookup.asked == [(CUSTOMER, DOMAIN)]
    # Audited before and after on the domain chain, as the worker identity.
    chain = f"{CUSTOMER}.{DOMAIN.rsplit(':', 1)[-1]}"
    records = list(await audit.read_range(chain, limit=10))
    assert [r.kind for r in records] == ["before", "after"]
    # Idempotent: recording the same intent again writes nothing.
    stored = await h.service.get(key)
    again = await recorder.record(stored)
    assert entity is not None and again.etag.root == entity.etag.root
    assert len(list(await audit.read_range(chain, limit=10))) == 2


async def test_a_recording_failure_is_audited_and_surfaced_but_the_change_stands() -> None:
    world = await grant_world()
    h = _harness(world)
    recorder = FakeRecorder(DependencyTransientError("down", reason="catalog_store_unavailable"))
    key = await h.executing(await publish_draft(world))
    report = await _executor(h, world, recorder).execute(key)
    assert (report.outcome, report.state) == ("succeeded", "succeeded")
    assert report.reason == PUBLICATION_RECORD_FAILED
    assert len(recorder.calls) == 1
    assert (await h.service.get(key)).state == "succeeded"
    assert NAMES.product in world.apim.resources  # nothing undone
    failures = [e for e in h.auditor.events if e.operation == PUBLICATION_RECORD_OPERATION]
    assert [(e.kind, e.result, e.reason) for e in failures] == [
        ("after", "failed", "catalog_store_unavailable")
    ]
    assert failures[0].intent_id == key.intent_id


async def test_nothing_is_recorded_for_dry_runs_other_connectors_or_failures() -> None:
    world = await grant_world()
    h = _harness(world)
    recorder = FakeRecorder()
    executor = _executor(h, world, recorder)
    # A dry run of a publication: succeeds without apply, never recorded.
    draft = await publish_draft(world, key="idem-grant-dryrun-0001")
    dry = await h.executing(draft.model_copy(update={"dry_run": True}))
    assert (await executor.execute(dry)).outcome == "succeeded"
    # Another connector (the Foundry swap): succeeded, not a publication.
    foundry = await h.executing(draft_request(key="idem-foundry-0001"))
    assert (await executor.execute(foundry)).outcome == "succeeded"
    # A publication that fails (gateway moved since the review): not recorded.
    stale = await h.executing(await publish_draft(world, key="idem-grant-stale-0001"))
    world.apim.seed(NAMES.product, {"displayName": "someone else"})
    assert (await executor.execute(stale)).outcome == "failed"
    assert recorder.calls == []


async def test_recordable_requires_a_verified_apim_publication() -> None:
    world = await grant_world()
    h = _harness(world)
    key = await h.executing(await publish_draft(world))
    report = await _executor(h, world, FakeRecorder()).execute(key)
    assert report.outcome == "succeeded"
    stored = await h.service.get(key)
    assert recordable_publication(stored)
    assert stored.execution is not None
    unverified = stored.model_copy(
        update={"execution": stored.execution.model_copy(update={"verify_matched": False})}
    )
    assert not recordable_publication(unverified)
    other_table = {**TABLE, "grant_publish": "foundry-model-swap"}
    assert recordable_publication(stored, other_table)  # target kind still routes to APIM
    swap = stored.model_copy(
        update={"intent": stored.intent.model_copy(update={"action_kind": "budget_cap_change"})}
    )
    assert not recordable_publication(swap)


async def test_the_recorder_refuses_without_curate_rights_or_verification() -> None:
    world = await grant_world()
    h = _harness(world)
    key = await h.executing(await publish_draft(world))
    await _executor(h, world, FakeRecorder()).execute(key)
    stored = await h.service.get(key)
    steward = make_scope()
    repo = await catalog(steward)
    audit = AuditRepository(InMemoryAuditStore())
    viewer = CatalogPublicationRecorder(
        repo, audit, FixedScope(make_scope("viewer")), clock=lambda: START
    )
    with pytest.raises(ForbiddenError):
        await viewer.record(stored)
    recorder = CatalogPublicationRecorder(repo, audit, FixedScope(steward), clock=lambda: START)
    assert stored.execution is not None
    unverified = stored.model_copy(
        update={"execution": stored.execution.model_copy(update={"verify_matched": None})}
    )
    with pytest.raises(InvalidSchemaError) as caught:
        await recorder.record(unverified)
    assert caught.value.reason == "intent_not_verified"
    assert "apim_published" not in _attributes(await repo.get_entity(steward, GRANT_ID))
    # Without an apply-record lookup the publication is recorded, ownership "unrecorded".
    await recorder.record(stored)
    assert _attributes(await repo.get_entity(steward, GRANT_ID))["apim_ownership"] == "unrecorded"


async def test_the_recording_executor_needs_a_recorder() -> None:
    world = await grant_world()
    h = _harness(world)
    with pytest.raises(TypeError):
        PublicationRecordingExecutor(
            h.service,
            h.registry,
            recorder=object(),  # type: ignore[arg-type]
            auditor=h.auditor,
            execution_control=h.control,
            worker_id="exec-1",
        )
    with pytest.raises(TypeError):
        PublicationRecordingExecutor(  # type: ignore[call-arg]
            h.service,
            h.registry,
            recorder=FakeRecorder(),
            execution_control=h.control,
            worker_id="exec-1",
        )


_MCP_EXAMPLE: Final = _EXAMPLE.with_name("mcp_server.entra-streamable-http.json")
MCP_ID: Final = "commercial:contoso:neurosphere:mcp_server:finance/ledger-tools"


def _mcp_diff(publication: dict[str, Any]) -> ProposedDiff:
    return ProposedDiff.model_validate(
        {
            "format": "json_patch",
            "operations": [{"op": "replace", "path": "/publication", "value": publication}],
        }
    )


async def test_a_verified_mcp_stage_is_recorded_once_and_a_wrong_stage_is_refused() -> None:
    world = await grant_world()
    h = _harness(world)
    key = await h.executing(await publish_draft(world))
    await _executor(h, world, FakeRecorder()).execute(key)
    grant = await h.service.get(key)
    assert grant.execution is not None
    scope = make_scope()
    repo = InMemoryCatalogRepository()
    doc = json.loads(_MCP_EXAMPLE.read_text(encoding="utf-8"))
    doc.update(domain_id=DOMAIN)
    await repo.create_entity(scope, parse_entity(doc))
    # A succeeded, verified ``publish`` stage of the server (shaped like a real execution).
    intent = grant.intent.model_copy(
        update={
            "action_kind": "mcp_server_publish",
            "target": TargetRef(canonical_id=MCP_ID, entity_type="mcp_server"),
            "target_version": "mcp-absent",
            "proposed_diff": _mcp_diff(
                {"stage": "publish", "gateway_id": GW, "api_path": "ledger"}
            ),
        }
    )
    stored = grant.model_copy(
        update={
            "intent": intent,
            "execution": grant.execution.model_copy(update={"apply_finished_at": START}),
        }
    )
    recorder = CatalogPublicationRecorder(
        repo, AuditRepository(InMemoryAuditStore()), FixedScope(scope), clock=lambda: START
    )
    # ``remove`` never rides on a publish kind.
    removal = stored.model_copy(
        update={
            "intent": intent.model_copy(
                update={"proposed_diff": _mcp_diff({"stage": "remove", "gateway_id": GW})}
            )
        }
    )
    with pytest.raises(InvalidSchemaError) as caught:
        await recorder.record(removal)
    assert caught.value.reason == "intent_mismatch"
    recorded = await recorder.record(stored)
    attrs = dict(dump(recorded).get("attributes") or {})
    assert attrs["mcp_publication_state"] == "published"
    assert attrs["mcp_publication_gateway_id"] == GW
    assert attrs["mcp_publication_api_path"] == "ledger"
    assert dump(recorded)["provenance"]["source_id"] == f"apim-gateway.{GW}"
    again = await recorder.record(stored)  # the state moved on, yet the replay is a no-op
    assert again.etag.root == recorded.etag.root
