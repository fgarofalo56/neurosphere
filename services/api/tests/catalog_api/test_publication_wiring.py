"""PRP-34 item 10 wiring on the API side. Offline (fake Cosmos container, in-memory APIM).

* ``app.state.apim_apply_records`` from the PRODUCTION gateway builder reads the very apply
  records the executor's Cosmos store writes (same container, same partition), so a recorded
  publication carries its ownership and the unpublish is drafted and checked against it;
* the record route ties the diff grammar to the action kind;
* the planning view refuses a grammar under another action kind before any plan.
"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from fastapi import FastAPI
from gateway_mode_harness import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    GATEWAY_ID,
    OPERATOR,
    STEWARD,
    manage_fields,
    problem,
    registration,
)
from grant_publish_harness import (  # pyright: ignore[reportMissingImports]
    GRANT_ID,
    make_grant_env,
)
from neurosphere_api.runtime.builders import ComponentUnavailableError
from neurosphere_api.runtime.builders import gateway as gateway_builder
from neurosphere_connector_apim_gateway.grants import publication_names
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.cloud import Settings
from neurosphere_core.gateway import InMemoryGatewayStore
from neurosphere_workers.actions.apim import apim_record_store
from neurosphere_workers.publication import CosmosApplyRecordLookup, InMemoryApplyRecordLookup

NAMES = publication_names(GRANT_ID)
DATABASE = "nsdb"


class FakeContainer:
    """Just enough of an aio ``ContainerProxy`` for the gateway and apply-record stores."""

    def __init__(self) -> None:
        self.docs: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.counter = 0

    def _stamp(self, body: Mapping[str, Any]) -> dict[str, Any]:
        self.counter += 1
        return {**copy.deepcopy(dict(body)), "_etag": f'"{self.counter}"'}

    @staticmethod
    def _key(body: Mapping[str, Any]) -> tuple[str, str, str]:
        return (str(body["customer_id"]), str(body["domain_id"]), str(body["id"]))

    async def create_item(self, body: dict[str, Any]) -> dict[str, Any]:
        key = self._key(body)
        if key in self.docs:
            raise CosmosResourceExistsError(message="exists")
        self.docs[key] = self._stamp(body)
        return self.docs[key]

    async def read_item(self, item: str, partition_key: list[str]) -> dict[str, Any]:
        found = self.docs.get((partition_key[0], partition_key[1], item))
        if found is None:
            raise CosmosResourceNotFoundError(message="missing")
        return copy.deepcopy(found)

    async def replace_item(
        self, item: str, body: dict[str, Any], etag: str, match_condition: object
    ) -> dict[str, Any]:
        key = self._key(body)
        current = self.docs.get(key)
        if current is None or current["_etag"] != etag:
            raise CosmosAccessConditionFailedError(message="precondition")
        self.docs[key] = self._stamp(body)
        return self.docs[key]

    async def query_items(
        self, sql: str, parameters: list[dict[str, Any]], partition_key: list[str]
    ) -> AsyncIterator[dict[str, Any]]:
        params = {p["name"]: p["value"] for p in parameters}
        rows = [
            copy.deepcopy(doc)
            for (customer, domain, _), doc in self.docs.items()
            if [customer, domain] == partition_key and doc.get("doc_type") == params["@doc_type"]
        ]
        if "@gateway" in params:
            rows = [
                r
                for r in rows
                if r["gateway_id"] == params["@gateway"] and r["status"] == params["@status"]
            ][:1]
        for row in rows:
            yield row


@dataclass
class FakeCosmos:
    container: FakeContainer = field(default_factory=FakeContainer)
    opened: list[tuple[str, str]] = field(default_factory=list)

    def get_database_client(self, database: str) -> Any:
        def container_client(name: str) -> FakeContainer:
            self.opened.append((database, name))
            return self.container

        return SimpleNamespace(get_container_client=container_client)


@dataclass
class FakeContext:
    """The slice of ``BuildContext`` the gateway builder uses."""

    app: FastAPI
    cosmos: FakeCosmos
    backends: dict[str, object] = field(default_factory=dict)
    environ: dict[str, str] = field(default_factory=dict)
    settings: Settings = field(default_factory=Settings)
    status: dict[str, str] = field(default_factory=dict)

    @property
    def overrides(self) -> FakeContext:
        return self

    def backend(self, name: str) -> object | None:
        return self.backends.get(name)

    def shared(self, key: Any) -> AuditRepository:
        return AuditRepository(InMemoryAuditStore())

    def cosmos_client(self) -> FakeCosmos:
        return self.cosmos

    def store_settings(self) -> Any:
        return SimpleNamespace(database=DATABASE)

    def on_shutdown(self, hook: Any) -> None:
        return None

    def attempt(self, name: str, fn: Any) -> Any:
        try:
            value = fn()
        except ComponentUnavailableError as exc:
            self.status[name] = exc.reason
            return None
        self.status[name] = "ok"
        return value

    def failed(self, name: str, reason: str) -> None:
        self.status[name] = reason


def _no_arm(profile: Any) -> Any:
    raise AssertionError("no ARM call in this test")


def _compose(cosmos: FakeCosmos, **backends: object) -> FastAPI:
    app = FastAPI()
    ctx = FakeContext(app, cosmos, {"gateway_arm_factory": _no_arm, **backends})
    gateway_builder.build(ctx)  # type: ignore[arg-type]
    assert ctx.status == {"gateway_plane": "ok"}, ctx.status
    return app


# -- production composition ----------------------------------------------------------------------


def test_the_gateway_builder_binds_apply_records_to_the_gateway_container() -> None:
    cosmos = FakeCosmos()
    app = _compose(cosmos)
    lookup = app.state.apim_apply_records
    assert isinstance(lookup, CosmosApplyRecordLookup)
    assert (lookup.database, lookup.container) == (DATABASE, "gateways")
    memory = _compose(FakeCosmos(), gateway_store=InMemoryGatewayStore())
    assert isinstance(memory.state.apim_apply_records, InMemoryApplyRecordLookup)
    custom = InMemoryApplyRecordLookup()
    assert _compose(FakeCosmos(), apim_apply_records=custom).state.apim_apply_records is custom
    bad = FakeContext(FastAPI(), FakeCosmos(), {"apim_apply_records": object()})
    gateway_builder.build(bad)  # type: ignore[arg-type]
    assert bad.status == {"gateway_plane": "apim_apply_records_override_invalid"}


def test_unpublish_ownership_resolves_through_the_production_composition() -> None:
    cosmos = FakeCosmos()
    # The executor's durable store (worker composition) over the shared container...
    worker_records = apim_record_store(
        cosmos,  # type: ignore[arg-type]
        database=DATABASE,
        registration=registration(**manage_fields()),
        container="gateways",
    )
    g = make_grant_env(records=worker_records, wire_records=False)
    # ...and the API's lookup exactly as the production gateway builder composes it.
    g.env.h.app.state.apim_apply_records = _compose(cosmos).state.apim_apply_records
    drafted = g.publish(STEWARD)
    assert drafted.status_code == 201, drafted.text
    publish_id = drafted.json()["intent"]["intent_id"]
    g.execute(publish_id)
    recorded = g.record(STEWARD, publish_id)
    assert recorded.status_code == 200, recorded.text
    attrs = recorded.json()["attributes"]
    assert attrs["apim_ownership"] == "recorded"
    assert NAMES.product in attrs["apim_created"].split(",")
    record_id = attrs["apim_apply_record"]
    assert record_id
    # The unpublish names that record and the connector re-checks ownership against it.
    unpublish = g.unpublish(STEWARD)
    assert unpublish.status_code == 201, unpublish.text
    ops = {op["path"]: op for op in unpublish.json()["intent"]["proposed_diff"]["operations"]}
    assert ops["/publication/apply_record"]["value"] == record_id
    g.execute(unpublish.json()["intent"]["intent_id"])
    assert set(g.env.apim.resources) == {"apis/llm"}


def test_without_wired_records_ownership_is_unrecorded_and_unpublish_refused() -> None:
    g = make_grant_env(wire_records=False)
    publish_id = g.publish(STEWARD).json()["intent"]["intent_id"]
    g.execute(publish_id)
    assert g.record(STEWARD, publish_id).json()["attributes"]["apim_ownership"] == "unrecorded"
    assert problem(g.unpublish(STEWARD))["reason"] == "ownership_unrecorded"


# -- kind / grammar tie ----------------------------------------------------------------------------


def test_record_refuses_a_publish_intent_carrying_an_unpublish_diff() -> None:
    g = make_grant_env()
    publish_id = g.publish(STEWARD).json()["intent"]["intent_id"]
    g.execute(publish_id)

    async def tamper() -> None:
        stored = await g.env.intents.get("contoso", FINANCE, publish_id)
        assert stored is not None and stored.etag is not None
        removal = stored.intent.proposed_diff.model_validate(
            {
                "format": "json_patch",
                "operations": [
                    {"op": "test", "path": "/publication/gateway_id", "value": GATEWAY_ID},
                    {"op": "test", "path": "/publication/resources", "value": [NAMES.product]},
                    {"op": "remove", "path": "/publication"},
                ],
            }
        )
        intent = stored.intent.model_copy(update={"proposed_diff": removal})
        await g.env.intents.replace(
            stored.model_copy(update={"intent": intent}), if_match=stored.etag
        )

    asyncio.run(tamper())
    refused = g.record(STEWARD, publish_id)
    assert refused.status_code == 422, refused.text
    assert problem(refused)["reason"] == "action_kind_mismatch"
    assert "apim_published" not in (g.stored().model_dump(mode="json").get("attributes") or {})


def test_the_planning_view_refuses_a_grammar_under_another_kind() -> None:
    g = make_grant_env()
    body = {
        "action_kind": "grant_publish",
        "target": {"canonical_id": GRANT_ID, "entity_type": "grant"},
        "target_version": "grant-published",
        "proposed_diff": {
            "format": "json_patch",
            "operations": [
                {"op": "test", "path": "/publication/gateway_id", "value": GATEWAY_ID},
                {"op": "test", "path": "/publication/apply_record", "value": "apply-x"},
                {"op": "test", "path": "/publication/resources", "value": [NAMES.product]},
                {"op": "remove", "path": "/publication"},
            ],
        },
        "idempotency_key": "idem-kind-mismatch-0001",
        "channel": "rest",
    }
    drafted = g.env.draft_intent(body)
    assert drafted.status_code == 201, drafted.text
    intent_id = drafted.json()["intent"]["intent_id"]
    view = g.env.step(OPERATOR, intent_id, "validate")
    assert view.status_code == 200, view.text
    checks = {c["check_id"]: c for c in view.json()["intent"]["prerequisite_results"]}
    assert checks["target_dry_run"]["status"] == "failed"
    assert checks["target_dry_run"]["detail"] == "action_kind_mismatch"
    assert g.env.apim.calls == []  # refused before any plan read the gateway
