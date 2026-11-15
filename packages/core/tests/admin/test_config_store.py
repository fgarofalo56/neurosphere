"""The ``admin_config`` store (PRP-65 item 3): kind validation, versions, If-Match, retire.

In-memory twin and the Cosmos repository over a fake container; the emulator twin is
``test_config_store_cosmos.py`` (``integration``).
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from azure.core import MatchConditions
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from neurosphere_core.admin import (
    ADMIN_CONFIG_CHAIN_SUFFIX,
    ADMIN_CONFIG_CONTAINER,
    ADMIN_CONFIG_PARTITION_KEY_PATH,
    ADMIN_KIND_MODELS,
    ADMIN_KINDS,
    AdminConfigRepository,
    CosmosAdminConfigRepository,
    InMemoryAdminConfigRepository,
    admin_config_chain_id,
    cosmos_item_id,
    validate_admin_body,
)
from neurosphere_core.admin.store import AdminConfigStoreBase
from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
    NotFoundError,
    RateLimitedError,
    StaleVersionError,
)
from neurosphere_core.stores import container_spec, export_document

EXAMPLES = (
    Path(__file__).resolve().parents[4] / "packages" / "contracts" / "schemas" / "admin" / "v1"
)
EXAMPLES = EXAMPLES / "examples"
KIND_BY_STEM = {
    "producer-record": "producer",
    "connector-config": "connector_config",
    "domain-definition": "domain",
    "budget": "budget",
    "price-sheet-upload": "price_sheet",
    "review-policy-document": "review_policy",
    "system-setting": "system_setting",
}
CUSTOMER = "contoso"
ACTOR = "commercial:contoso:entra:person:p-" + "0c" * 32
OTHER_ACTOR = "commercial:contoso:entra:person:p-" + "1d" * 32


def _examples(kind_dir: str) -> list[tuple[str, str, str, dict[str, Any]]]:
    out = []
    for path in sorted((EXAMPLES / kind_dir).glob("*.json")):
        stem = path.name.split(".")[0]
        if stem in KIND_BY_STEM:
            cloud = "government" if "government" in path.name else "commercial"
            body = json.loads(path.read_text(encoding="utf-8"))
            out.append((path.name, KIND_BY_STEM[stem], cloud, body))
    return out


def _load(name: str) -> dict[str, Any]:
    return json.loads((EXAMPLES / "valid" / name).read_text(encoding="utf-8"))


DOMAIN = _load("domain-definition.finance.json")


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


# ---------------------------------------------------------------------------- kind models


def test_every_admin_kind_has_exactly_one_model() -> None:
    assert set(ADMIN_KIND_MODELS) == ADMIN_KINDS
    union = AdminConfigDocument.model_fields["body"].annotation
    assert set(ADMIN_KIND_MODELS.values()) == set(union.__args__)  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("name", "kind", "cloud", "body"), _examples("valid"), ids=lambda v: str(v)[:60]
)
def test_valid_contract_examples_validate_by_kind(
    name: str, kind: str, cloud: str, body: dict[str, Any]
) -> None:
    customer = "agency-a" if cloud == "government" else CUSTOMER
    model = validate_admin_body(kind, body, customer_id=customer, cloud=cloud)  # type: ignore[arg-type]
    assert isinstance(model, ADMIN_KIND_MODELS[kind]), name


@pytest.mark.parametrize(
    ("name", "kind", "cloud", "body"), _examples("invalid"), ids=lambda v: str(v)[:60]
)
def test_invalid_contract_examples_are_invalid_schema(
    name: str, kind: str, cloud: str, body: dict[str, Any]
) -> None:
    """Every invalid example, including the rules the generated models cannot express."""
    customer = "agency-a" if cloud == "government" else CUSTOMER
    with pytest.raises(InvalidSchemaError) as info:
        validate_admin_body(kind, body, customer_id=customer, cloud=cloud)  # type: ignore[arg-type]
    assert all(i.pointer.startswith("/body") for i in info.value.errors or ()), name


def test_a_body_of_the_wrong_kind_is_invalid_schema() -> None:
    with pytest.raises(InvalidSchemaError):
        validate_admin_body("budget", DOMAIN, customer_id=CUSTOMER)
    with pytest.raises(InvalidSchemaError) as info:
        validate_admin_body("tenant", DOMAIN, customer_id=CUSTOMER)
    assert info.value.reason == "unknown_admin_kind"


def test_cross_customer_and_cross_cloud_ids_are_refused() -> None:
    with pytest.raises(InvalidSchemaError) as info:
        validate_admin_body("domain", DOMAIN, customer_id="fabrikam")
    assert info.value.reason == "cross_customer"
    with pytest.raises(InvalidSchemaError) as info:
        validate_admin_body("domain", DOMAIN, customer_id=CUSTOMER, cloud="government")
    assert info.value.reason == "cross_cloud"


def test_credential_reference_rules_are_enforced_inside_bodies() -> None:
    base = _load("connector-config.gateway-poll.json")
    assert base["credential"] is not None
    mi_with_uri = copy.deepcopy(base)
    mi_with_uri["credential"] = {
        "kind": "managed_identity",
        "managed_identity_client_id": "6f1c2b9e-0d4a-4c1e-9b7a-3e5f8d2c1a07",
        "secret_uri": "https://kv-ns-contoso.vault.azure.net/secrets/gw",
    }
    bare = copy.deepcopy(base)
    bare["credential"] = {"kind": "key_vault_secret"}
    gov_vault = copy.deepcopy(base)
    gov_vault["credential"] = {
        "kind": "key_vault_secret",
        "secret_uri": "https://kv-ns-contoso.vault.usgovcloudapi.net/secrets/gw",
    }
    for body in (mi_with_uri, bare, gov_vault):
        with pytest.raises(InvalidSchemaError) as info:
            validate_admin_body("connector_config", body, customer_id=CUSTOMER, cloud="commercial")
        rendered = info.value.to_problem_details("c").model_dump_json()
        assert "kv-ns-contoso" not in rendered  # no secret URI echoed


def test_validation_errors_never_echo_values() -> None:
    producer = _load("producer-record.active.json")
    producer["secret_sha256"] = "plaintext-shared-secret-value"  # noqa: S105 - test fixture
    with pytest.raises(InvalidSchemaError) as info:
        validate_admin_body("producer", producer, customer_id=CUSTOMER)
    assert "plaintext" not in info.value.to_problem_details("c").model_dump_json()


def test_chain_and_container_names() -> None:
    assert admin_config_chain_id(CUSTOMER) == f"contoso.{ADMIN_CONFIG_CHAIN_SUFFIX}"
    assert admin_config_chain_id("agency-a") == "agency-a.admin-config"
    for bad in ("", "Contoso", "a.b", "x" * 130):
        with pytest.raises(InvalidSchemaError):
            admin_config_chain_id(bad)
    spec = container_spec(ADMIN_CONFIG_CONTAINER)
    assert ADMIN_CONFIG_CONTAINER == "admin_config"
    assert spec.partition_key_paths == (ADMIN_CONFIG_PARTITION_KEY_PATH,) == ("/customer_id",)
    assert spec.owner == "neurosphere_core.admin.cosmos_store"
    assert spec.default_ttl is None
    exported = {c["name"] for c in export_document()["containers"]}
    assert ADMIN_CONFIG_CONTAINER in exported


# ---------------------------------------------------------------------------- store behaviour


class FakeContainer:
    """The slice of ``ContainerProxy`` the Cosmos store uses, with Cosmos ETag semantics."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}
        self.n = 0
        self.fail: Exception | None = None
        self.queries: list[tuple[str, list[dict[str, Any]], str]] = []

    def _stamp(self, body: dict[str, Any]) -> dict[str, Any]:
        self.n += 1
        row = copy.deepcopy(body) | {"_etag": f'"cos-{self.n}"', "_ts": self.n}
        self.rows[(body["customer_id"], body["id"])] = row
        return copy.deepcopy(row)

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        if self.fail is not None:
            raise self.fail
        row = self.rows.get((partition_key, item))
        if row is None:
            raise CosmosResourceNotFoundError(message="nf", response=None)
        return copy.deepcopy(row)

    async def create_item(self, *, body: dict[str, Any]) -> dict[str, Any]:
        if self.fail is not None:
            raise self.fail
        if (body["customer_id"], body["id"]) in self.rows:
            raise CosmosResourceExistsError(message="exists", response=None)
        return self._stamp(body)

    async def replace_item(
        self, *, item: str, body: dict[str, Any], etag: str, match_condition: MatchConditions
    ) -> dict[str, Any]:
        if self.fail is not None:
            raise self.fail
        assert match_condition is MatchConditions.IfNotModified and item == body["id"]
        current = self.rows.get((body["customer_id"], item))
        if current is None:
            raise CosmosResourceNotFoundError(message="nf", response=None)
        if current["_etag"] != etag:
            raise CosmosAccessConditionFailedError(message="412", response=None)
        return self._stamp(body)

    def query_items(self, sql: str, *, parameters: list[dict[str, Any]], partition_key: str):  # type: ignore[no-untyped-def]
        if self.fail is not None:
            raise self.fail
        self.queries.append((sql, parameters, partition_key))
        values = {p["name"]: p["value"] for p in parameters}
        rows = [
            copy.deepcopy(r)
            for (pk, _), r in sorted(self.rows.items())
            if pk == partition_key
            and r["doc_type"] == values["@doc_type"]
            and r["kind"] == values["@kind"]
            and ("@status" not in values or r["status"] == values["@status"])
        ][: values["@limit"]]

        async def gen():  # type: ignore[no-untyped-def]
            for r in rows:
                yield r

        return gen()


def _memory() -> InMemoryAdminConfigRepository:
    return InMemoryAdminConfigRepository(cloud="commercial", clock=Clock())


def _cosmos() -> CosmosAdminConfigRepository:
    return CosmosAdminConfigRepository(FakeContainer(), cloud="commercial", clock=Clock())  # type: ignore[arg-type]


STORES = [pytest.param(_memory, id="memory"), pytest.param(_cosmos, id="cosmos-fake")]


@pytest.mark.parametrize("factory", STORES)
def test_both_twins_satisfy_the_protocol(factory: Any) -> None:
    assert isinstance(factory(), AdminConfigRepository)


@pytest.mark.parametrize("factory", STORES)
async def test_create_get_replace_retire_lifecycle(factory: Any) -> None:
    store: AdminConfigStoreBase = factory()
    created = await store.create(CUSTOMER, "domain", "finance", DOMAIN, updated_by=ACTOR)
    assert (created.version.root, created.status, created.kind.root) == (1, "active", "domain")
    assert created.updated_by.root == ACTOR and created.updated_at.root.endswith("Z")
    assert await store.get(CUSTOMER, "domain", "finance") == created
    assert await store.get(CUSTOMER, "budget", "finance") is None  # kinds do not collide

    renamed = DOMAIN | {"display_name": "Finance and Planning"}
    v2 = await store.replace(
        CUSTOMER, "domain", "finance", renamed, if_match=created.etag.root, updated_by=OTHER_ACTOR
    )
    assert v2.version.root == 2 and v2.etag != created.etag
    assert v2.updated_by.root == OTHER_ACTOR and v2.updated_at.root > created.updated_at.root
    assert v2.body.model_dump(mode="json")["display_name"] == "Finance and Planning"

    v3 = await store.replace(
        CUSTOMER, "domain", "finance", DOMAIN, if_match=v2.etag.root, updated_by=ACTOR
    )
    assert v3.version.root == 3

    retired = await store.retire(
        CUSTOMER, "domain", "finance", if_match=v3.etag.root, updated_by=ACTOR
    )
    assert (retired.version.root, retired.status) == (4, "retired")
    assert retired.body == v3.body
    still = await store.get(CUSTOMER, "domain", "finance")
    assert still is not None and still.status == "retired"  # readable for audit

    with pytest.raises(StaleVersionError) as info:
        await store.replace(
            CUSTOMER, "domain", "finance", DOMAIN, if_match=retired.etag.root, updated_by=ACTOR
        )
    assert info.value.reason == "admin_config_retired"
    with pytest.raises(StaleVersionError):
        await store.retire(
            CUSTOMER, "domain", "finance", if_match=retired.etag.root, updated_by=ACTOR
        )
    with pytest.raises(StaleVersionError) as info:  # ids are never reused
        await store.create(CUSTOMER, "domain", "finance", DOMAIN, updated_by=ACTOR)
    assert info.value.reason == "admin_config_exists"


@pytest.mark.parametrize("factory", STORES)
async def test_if_match_mismatch_is_stale_version_and_writes_nothing(factory: Any) -> None:
    store: AdminConfigStoreBase = factory()
    created = await store.create(CUSTOMER, "domain", "finance", DOMAIN, updated_by=ACTOR)
    await store.replace(
        CUSTOMER, "domain", "finance", DOMAIN, if_match=created.etag.root, updated_by=ACTOR
    )
    with pytest.raises(StaleVersionError) as info:
        await store.replace(
            CUSTOMER, "domain", "finance", DOMAIN, if_match=created.etag.root, updated_by=ACTOR
        )
    assert (info.value.code, info.value.reason) == ("stale_version", "admin_config_modified")
    with pytest.raises(StaleVersionError):
        await store.retire(
            CUSTOMER, "domain", "finance", if_match=created.etag.root, updated_by=ACTOR
        )
    current = await store.get(CUSTOMER, "domain", "finance")
    assert current is not None and current.version.root == 2 and current.status == "active"


@pytest.mark.parametrize("factory", STORES)
async def test_missing_documents_are_not_found(factory: Any) -> None:
    store: AdminConfigStoreBase = factory()
    with pytest.raises(NotFoundError):
        await store.replace(CUSTOMER, "domain", "finance", DOMAIN, if_match='"x"', updated_by=ACTOR)
    with pytest.raises(NotFoundError):
        await store.retire(CUSTOMER, "domain", "finance", if_match='"x"', updated_by=ACTOR)


@pytest.mark.parametrize("factory", STORES)
async def test_invalid_body_or_actor_writes_nothing(factory: Any) -> None:
    store: AdminConfigStoreBase = factory()
    with pytest.raises(InvalidSchemaError):
        await store.create(CUSTOMER, "budget", "finance", DOMAIN, updated_by=ACTOR)
    with pytest.raises(InvalidSchemaError):
        await store.create(CUSTOMER, "domain", "finance", DOMAIN, updated_by="alice@contoso.com")
    with pytest.raises(InvalidSchemaError) as info:
        await store.create(
            CUSTOMER,
            "domain",
            "finance",
            DOMAIN,
            updated_by="commercial:fabrikam:entra:person:p-" + "0c" * 32,
        )
    assert info.value.reason == "cross_customer"
    with pytest.raises(InvalidSchemaError):
        await store.create(CUSTOMER, "domain", "bad/id", DOMAIN, updated_by=ACTOR)
    assert await store.list_by_kind(CUSTOMER, "domain", include_retired=True) == []

    created = await store.create(CUSTOMER, "domain", "finance", DOMAIN, updated_by=ACTOR)
    with pytest.raises(InvalidSchemaError):
        await store.replace(
            CUSTOMER,
            "domain",
            "finance",
            DOMAIN | {"classification": "top-secret"},
            if_match=created.etag.root,
            updated_by=ACTOR,
        )
    assert await store.get(CUSTOMER, "domain", "finance") == created


@pytest.mark.parametrize("factory", STORES)
async def test_list_by_kind_is_per_customer_kind_and_status(factory: Any) -> None:
    store: AdminConfigStoreBase = factory()
    ops = DOMAIN | {"domain_id": "commercial:contoso:neurosphere:domain:ops", "display_name": "Ops"}
    a = await store.create(CUSTOMER, "domain", "finance", DOMAIN, updated_by=ACTOR)
    await store.create(CUSTOMER, "domain", "ops", ops, updated_by=ACTOR)
    budget = _load("budget.annual-unfiltered.json")
    await store.create(CUSTOMER, "budget", budget["budget_id"], budget, updated_by=ACTOR)
    await store.retire(CUSTOMER, "domain", "finance", if_match=a.etag.root, updated_by=ACTOR)

    active = await store.list_by_kind(CUSTOMER, "domain")
    assert [d.id.root for d in active] == ["ops"]
    every = await store.list_by_kind(CUSTOMER, "domain", include_retired=True)
    assert [d.id.root for d in every] == ["finance", "ops"]
    assert len(await store.list_by_kind(CUSTOMER, "domain", include_retired=True, limit=1)) == 1
    assert await store.list_by_kind("fabrikam", "domain", include_retired=True) == []
    assert [d.kind.root for d in await store.list_by_kind(CUSTOMER, "budget")] == ["budget"]
    for bad_limit in (0, 1001):
        with pytest.raises(InvalidSchemaError):
            await store.list_by_kind(CUSTOMER, "domain", limit=bad_limit)
    with pytest.raises(InvalidSchemaError):
        await store.list_by_kind(CUSTOMER, "tenant")


async def test_memory_outage_is_raised_unchanged() -> None:
    store = _memory()
    store.fail_with(DependencyTransientError("down", reason="admin_config_unavailable"))
    with pytest.raises(DependencyTransientError):
        await store.get(CUSTOMER, "domain", "finance")
    store.fail_with(None)
    assert await store.get(CUSTOMER, "domain", "finance") is None


async def test_cosmos_row_layout_and_partition() -> None:
    container = FakeContainer()
    store = CosmosAdminConfigRepository(container, cloud="commercial", clock=Clock())  # type: ignore[arg-type]
    created = await store.create(CUSTOMER, "domain", "finance", DOMAIN, updated_by=ACTOR)
    row = container.rows[(CUSTOMER, cosmos_item_id("domain", "finance"))]
    assert row["id"] == "domain:finance"
    assert (row["doc_type"], row["customer_id"], row["kind"], row["status"]) == (
        "admin_config",
        CUSTOMER,
        "domain",
        "active",
    )
    assert "etag" not in row["document"] and created.etag.root == row["_etag"]
    await store.list_by_kind(CUSTOMER, "domain")
    sql, params, partition = container.queries[-1]
    assert partition == CUSTOMER and "@kind" in sql and "@status" in sql
    assert all(p["name"].startswith("@") for p in params)


async def test_cosmos_failures_map_without_echo() -> None:
    container = FakeContainer()
    store = CosmosAdminConfigRepository(container, clock=Clock())  # type: ignore[arg-type]
    container.fail = RuntimeError("connection reset by https://acct.documents.azure.com")
    with pytest.raises(DependencyTransientError) as info:
        await store.get(CUSTOMER, "domain", "finance")
    assert "documents.azure.com" not in str(info.value)
    assert info.value.reason == "admin_config_unavailable"
    container.fail = CosmosHttpResponseError(status_code=429, message="throttled")
    with pytest.raises(RateLimitedError):
        await store.list_by_kind(CUSTOMER, "domain")


async def test_cosmos_tampered_row_is_upstream_invalid() -> None:
    container = FakeContainer()
    store = CosmosAdminConfigRepository(container, clock=Clock())  # type: ignore[arg-type]
    await store.create(CUSTOMER, "domain", "finance", DOMAIN, updated_by=ACTOR)
    row = container.rows[(CUSTOMER, "domain:finance")]
    row["document"]["customer_id"] = "fabrikam"
    with pytest.raises(DependencyTransientError) as info:
        await store.get(CUSTOMER, "domain", "finance")
    assert info.value.status == 502
    row["document"]["customer_id"] = CUSTOMER
    row["document"]["version"] = 0
    with pytest.raises(DependencyTransientError):
        await store.get(CUSTOMER, "domain", "finance")
