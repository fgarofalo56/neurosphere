"""PRP-104 item 2: the metadata explorer API and its builder (criterion 2).

Routes run over the PRP-06 authz harness (dev-issuer tokens, in-memory policy store) with an
:class:`InMemoryInteractionStore` holding synthetic records; builder tests drive the
``interactions`` and ``interaction_explorer`` builders over a hand-made ``CompositionState``.
Synthetic data only: every canary is generated at runtime.
"""

from __future__ import annotations

import asyncio
import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
import pytest
from fastapi import FastAPI
from neurosphere_api.admin.system.stored import STORED_SETTINGS
from neurosphere_api.interactions import (
    PREFIX,
    InteractionExplorer,
    build_router,
    configure_interaction_explorer,
)
from neurosphere_api.runtime.builders import (
    AUDIT_REPOSITORY,
    BuildContext,
    ComponentUnavailableError,
    CompositionState,
    default_builders,
    interaction_explorer,
    interactions,
)
from neurosphere_api.runtime.overrides import CompositionOverrides
from neurosphere_api.runtime.status import OPTIONAL_COMPONENTS, ComponentRegistry
from neurosphere_contracts.admin.v1.system_setting import SystemSetting
from neurosphere_contracts.interactions.v1.interaction_record import InteractionRecord
from neurosphere_contracts.interactions.v1.redacted_content import RedactedContent
from neurosphere_core.admin.runtime import StoredSetting, StoredSettingsSnapshot
from neurosphere_core.audit import (
    ALLOW_DETAIL,
    AuditRepository,
    InMemoryAuditStore,
    domain_audit_chain_id,
    sha256_digest,
)
from neurosphere_core.auth.scope import Role
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.crypto import LocalFileKeyWrapper
from neurosphere_core.interactions import (
    ENV_INTERACTION_LOCAL_KEY_FILE,
    MAX_QUERY_PAGE_SIZE,
    IndexPage,
    InMemoryInteractionStore,
    InteractionQuery,
)
from neurosphere_core.lifecycle.policy import PolicyState, load_policy

ALICE: str = helpers.ALICE  # viewer in FINANCE
BOB: str = helpers.BOB  # viewer in OPERATIONS only
CAROL: str = helpers.CAROL  # interaction investigator in FINANCE, no data.read
CUSTOMER: str = helpers.CUSTOMER
FINANCE: str = helpers.FINANCE
OPERATIONS: str = helpers.OPERATIONS
KEK_URI = "https://synthetic-kv.vault.azure.net/keys/ns-content-kek"
GOV_KEK_URI = "https://synthetic-kv.vault.usgovcloudapi.net/keys/ns-content-kek"
AGENT = f"commercial:{CUSTOMER}:foundry:agent:support-bot"
OTHER_AGENT = f"commercial:{CUSTOMER}:foundry:agent:hr-bot"
T0 = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
FIN_CHAIN = domain_audit_chain_id(CUSTOMER, FINANCE)
RECORD_FIELDS = set(InteractionRecord.model_fields)


def canary() -> str:
    return "NSCANARY-" + "".join(secrets.choice(string.ascii_lowercase) for _ in range(16))


def stamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def retention(*, opt_in: bool = True) -> PolicyState:
    return load_policy(
        {
            "policy_version": "v1",
            "rules": [
                {
                    "data_class": "telemetry_event",
                    "min_retention_days": 0,
                    "max_retention_days": 30,
                },
                {
                    "data_class": "interaction_content",
                    "min_retention_days": 0,
                    "max_retention_days": 90,
                },
            ],
            "retain_prompt_response_bodies": opt_in,
        }
    )


def record_doc(interaction_id: str, captured: datetime, **overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema_version": "1.2.0",
        "interaction_id": interaction_id,
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "domain_id": FINANCE,
        "source_id": "src-synthetic",
        "event_id": "evt-" + interaction_id[:8],
        "correlation_id": "corr-" + interaction_id[:8],
        "capture_source": "edge_push",
        "occurred_at": stamp(captured - timedelta(seconds=1)),
        "captured_at": stamp(captured),
        "agent_id": AGENT,
        "tool_id": None,
        "principal_id": None,
        "capture_policy_id": "support-capture",
        "capture_policy_version": 2,
        "detector_set_version": "detectors-1.0",
        "redaction_state": "redacted",
        "parts": [{"part": "prompt", "char_count": 40, "truncated": False}],
        "content_ref": None,
        "findings_summary": [{"category": "email_address", "count": 1, "action": "replaced"}],
        "sensitivity_categories": ["pii"],
        "data_asset_ids": [],
        "expires_at": stamp(captured + timedelta(days=30)),
    }
    doc.update(overrides)
    return doc


def content(interaction_id: str, text: str) -> RedactedContent:
    return RedactedContent.model_validate(
        {
            "schema_version": "1.0.0",
            "interaction_id": interaction_id,
            "redaction_state": "redacted",
            "detector_set_version": "detectors-1.0",
            "parts": [
                {
                    "part": "prompt",
                    "text": f"{text} [[ns-redacted:email_address]]",
                    "truncated": False,
                    "findings": [],
                }
            ],
        }
    )


class SpyStore(InMemoryInteractionStore):
    """The real in-memory store that also remembers every query and never decrypts."""

    def __init__(self, tmp_path: Path) -> None:
        super().__init__(
            LocalFileKeyWrapper(tmp_path / "kek.bin"), kek_uri=KEK_URI, policy=retention()
        )
        self.queries: list[InteractionQuery] = []
        self.content_reads = 0

    async def query_index(self, query: InteractionQuery) -> IndexPage:
        self.queries.append(query)
        return await super().query_index(query)

    async def read_content(self, *args: Any, **kwargs: Any) -> RedactedContent:
        self.content_reads += 1
        return await super().read_content(*args, **kwargs)


class ForeignStore(SpyStore):
    """A misbehaving index that hands back records of another cloud or customer."""

    def __init__(self, tmp_path: Path, foreign: list[InteractionRecord]) -> None:
        super().__init__(tmp_path)
        self.foreign = foreign

    async def query_index(self, query: InteractionQuery) -> IndexPage:
        self.queries.append(query)
        return IndexPage(items=tuple(self.foreign))

    async def get_metadata(
        self, customer_id: str, domain_id: str, interaction_id: str
    ) -> InteractionRecord | None:
        return next((r for r in self.foreign if r.interaction_id.root == interaction_id), None)


class Api:
    def __init__(self, store: SpyStore | None, *, explorer: bool = True) -> None:
        self.denials = helpers.RecordingDenials()
        investigator = helpers.role(
            Role.INTERACTION_INVESTIGATOR, FINANCE, expires_in=3 * 24 * 3600
        )
        self.h = helpers.harness(
            helpers.policy(ALICE, helpers.role(Role.VIEWER, FINANCE)),
            helpers.policy(BOB, helpers.role(Role.VIEWER, OPERATIONS)),
            helpers.policy(CAROL, investigator),
            routers={PREFIX: build_router()},
            denials=self.denials,
        )
        self.audit = AuditRepository(InMemoryAuditStore())
        self.h.app.state.audit_repository = self.audit
        if explorer and store is not None:
            configure_interaction_explorer(
                self.h.app,
                InteractionExplorer(
                    store=store, audit=self.audit, cloud="commercial", customer_id=CUSTOMER
                ),
            )

    def search(self, who: str, domain: str = FINANCE, **params: Any) -> Any:
        return self.h.client.get(
            f"{PREFIX}/{domain}/interactions", params=params or None, headers=self.h.auth(who)
        )

    def read(self, who: str, interaction_id: str, domain: str = FINANCE) -> Any:
        return self.h.client.get(
            f"{PREFIX}/{domain}/interactions/{interaction_id}", headers=self.h.auth(who)
        )

    def records(self, chain: str = FIN_CHAIN) -> list[Any]:
        return list(asyncio.run(self.audit.read_range(chain, start=0, limit=100)))


def seed(store: SpyStore, *docs: dict[str, Any]) -> list[str]:
    """Store each record with a canary-bearing redacted body; returns the canaries."""
    marks: list[str] = []

    async def put_all() -> None:
        for doc in docs:
            mark = canary()
            marks.append(mark)
            record = InteractionRecord.model_validate(doc)
            await store.put(record, content(doc["interaction_id"], mark), capture_retention_days=30)

    asyncio.run(put_all())
    return marks


def new_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def store(tmp_path: Path) -> SpyStore:
    return SpyStore(tmp_path)


# --- search: allowed, metadata only, audited ------------------------------------------------------


def test_allowed_search_returns_metadata_only_with_an_allowed_read_record(store: SpyStore) -> None:
    ids = [new_id(), new_id()]
    marks = seed(
        store,
        record_doc(ids[0], T0),
        record_doc(ids[1], T0 + timedelta(minutes=1)),
    )
    api = Api(store)
    response = api.search(ALICE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items", "continuation"}
    assert [item["interaction_id"] for item in body["items"]] == [ids[1], ids[0]]
    for item in body["items"]:
        assert set(item) <= RECORD_FIELDS
        InteractionRecord.model_validate(item)  # the PRP-99 contract, nothing more
        assert item["findings_summary"] == [
            {"category": "email_address", "count": 1, "action": "replaced"}
        ]
        assert item["redaction_state"] == "redacted"
    for mark in marks:
        assert mark not in response.text
    assert store.content_reads == 0

    (record,) = api.records()
    assert record.operation == "interaction.search"
    assert record.outcome.detail == ALLOW_DETAIL
    assert record.subject.target.canonical_id == FINANCE
    assert record.subject.state_digest.root == sha256_digest(
        {"domain_ids": [FINANCE], "result_count": 2}
    )
    assert api.denials.attempts == []


def test_metadata_read_returns_the_record_with_an_allowed_read_record(store: SpyStore) -> None:
    interaction_id = new_id()
    (mark,) = seed(store, record_doc(interaction_id, T0))
    api = Api(store)
    response = api.read(ALICE, interaction_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) <= RECORD_FIELDS
    assert InteractionRecord.model_validate(body).interaction_id.root == interaction_id
    assert body["content_ref"] is not None  # an encrypted-object reference, never content
    assert mark not in response.text
    assert store.content_reads == 0
    (record,) = api.records()
    assert record.operation == "interaction.metadata_read"
    assert record.outcome.detail == ALLOW_DETAIL


def test_absent_interaction_is_404_without_an_allowed_record(store: SpyStore) -> None:
    api = Api(store)
    response = api.read(ALICE, new_id())
    assert response.status_code == 404
    assert response.json()["reason"] == "interaction_not_found"
    assert api.records() == []


# --- denials --------------------------------------------------------------------------------------


def test_caller_without_data_read_is_403_with_a_denial_record(store: SpyStore) -> None:
    interaction_id = new_id()
    seed(store, record_doc(interaction_id, T0))
    api = Api(store)
    # CAROL holds interaction.read/export in FINANCE but not data.read.
    for response in (api.search(CAROL), api.read(CAROL, interaction_id)):
        assert response.status_code == 403
        assert "findings_summary" not in response.text  # problem details only, no metadata
    assert [a.permission for a in api.denials.attempts] == ["data.read", "data.read"]
    assert {a.domain_id for a in api.denials.attempts} == {FINANCE}
    assert api.records() == []
    assert store.queries == []


def test_search_in_another_domain_is_403_with_a_denial_record(store: SpyStore) -> None:
    seed(store, record_doc(new_id(), T0))
    api = Api(store)
    response = api.search(BOB, FINANCE)  # BOB reads OPERATIONS only
    assert response.status_code == 403
    (attempt,) = api.denials.attempts
    assert (attempt.permission, attempt.domain_id) == ("data.read", FINANCE)
    assert store.queries == []
    # and ALICE cannot read OPERATIONS
    assert api.search(ALICE, OPERATIONS).status_code == 403


# --- filters and paging ---------------------------------------------------------------------------


def test_filters_map_to_the_core_query(store: SpyStore) -> None:
    api = Api(store)
    principal = "pp-" + "a1" * 8
    response = api.search(
        ALICE,
        agent_id=AGENT,
        principal_id=principal,
        tool_id=f"commercial:{CUSTOMER}:neurosphere:tool:lookup",
        data_asset_id=f"commercial:{CUSTOMER}:fabric:lakehouse:sales",
        detected_category="email_address",
        **{"from": "2026-11-20T10:00:00Z", "to": "2026-11-21T10:00:00Z"},
        page_size=7,
    )
    assert response.status_code == 200, response.text
    (query,) = store.queries
    assert query.customer_id == CUSTOMER  # from the server-derived scope
    assert query.domain_id == FINANCE
    assert query.agent_id == AGENT
    assert query.principal_id == principal
    assert query.tool_id == f"commercial:{CUSTOMER}:neurosphere:tool:lookup"
    assert query.data_asset_id == f"commercial:{CUSTOMER}:fabric:lakehouse:sales"
    assert query.detected_category == "email_address"
    assert query.captured_from == datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    assert query.captured_before == datetime(2026, 11, 21, 10, 0, tzinfo=UTC)
    assert query.page_size == 7
    assert query.continuation is None
    assert query.sensitivity_category is None


def test_customer_comes_from_scope_never_the_request(store: SpyStore) -> None:
    api = Api(store)
    response = api.search(ALICE, customer_id="fabrikam")
    assert response.status_code == 200
    (query,) = store.queries
    assert query.customer_id == CUSTOMER


def test_from_is_inclusive_and_to_is_exclusive(store: SpyStore) -> None:
    ids = [new_id() for _ in range(3)]
    seed(store, *(record_doc(i, T0 + timedelta(minutes=n)) for n, i in enumerate(ids)))
    api = Api(store)
    response = api.search(
        ALICE,
        **{"from": stamp(T0 + timedelta(minutes=1)), "to": stamp(T0 + timedelta(minutes=2))},
    )
    assert response.status_code == 200, response.text
    assert [item["interaction_id"] for item in response.json()["items"]] == [ids[1]]


def test_agent_and_category_filters_select_records(store: SpyStore) -> None:
    mine, other, clean = new_id(), new_id(), new_id()
    seed(
        store,
        record_doc(mine, T0),
        record_doc(other, T0 + timedelta(minutes=1), agent_id=OTHER_AGENT),
        record_doc(clean, T0 + timedelta(minutes=2), findings_summary=[]),
    )
    api = Api(store)
    by_agent = api.search(ALICE, agent_id=OTHER_AGENT).json()["items"]
    assert [item["interaction_id"] for item in by_agent] == [other]
    by_category = api.search(ALICE, detected_category="email_address").json()["items"]
    assert {item["interaction_id"] for item in by_category} == {mine, other}


def test_page_is_bounded_and_continues(store: SpyStore) -> None:
    ids = [new_id() for _ in range(3)]
    seed(store, *(record_doc(i, T0 + timedelta(minutes=n)) for n, i in enumerate(ids)))
    api = Api(store)
    first = api.search(ALICE, page_size=2).json()
    assert len(first["items"]) == 2
    assert first["continuation"]
    second = api.search(ALICE, page_size=2, continuation=first["continuation"]).json()
    assert len(second["items"]) == 1
    assert second["continuation"] is None
    seen = [i["interaction_id"] for i in first["items"] + second["items"]]
    assert sorted(seen) == sorted(ids)

    too_big = api.search(ALICE, page_size=MAX_QUERY_PAGE_SIZE + 1)
    assert too_big.status_code == 422
    assert api.search(ALICE, page_size=0).status_code == 422
    default = api.search(ALICE)
    assert default.status_code == 200
    assert store.queries[-1].page_size <= MAX_QUERY_PAGE_SIZE


def test_bad_continuation_and_naive_bounds_are_422(store: SpyStore) -> None:
    api = Api(store)
    bad = api.search(ALICE, continuation="nsq1.bm90LWEtY3Vyc29y")
    assert bad.status_code == 422
    assert bad.json()["reason"] == "invalid_query"
    naive = api.search(ALICE, **{"from": "2026-11-20T10:00:00"})
    assert naive.status_code == 422


# --- cloud and customer boundary ------------------------------------------------------------------


def test_record_of_another_cloud_or_customer_is_never_returned(tmp_path: Path) -> None:
    gov_id, other_customer_id, own_id = new_id(), new_id(), new_id()
    gov = InteractionRecord.model_validate(
        record_doc(
            gov_id,
            T0,
            cloud="government",
            domain_id=f"government:{CUSTOMER}:catalog:domain:finance",
            agent_id=f"government:{CUSTOMER}:foundry:agent:support-bot",
        )
    )
    fabrikam = InteractionRecord.model_validate(
        record_doc(
            other_customer_id,
            T0,
            customer_id="fabrikam",
            domain_id="commercial:fabrikam:catalog:domain:finance",
            agent_id="commercial:fabrikam:foundry:agent:support-bot",
        )
    )
    own = InteractionRecord.model_validate(record_doc(own_id, T0))
    store = ForeignStore(tmp_path, [gov, fabrikam, own])
    api = Api(store)
    response = api.search(ALICE)
    assert response.status_code == 200
    assert [item["interaction_id"] for item in response.json()["items"]] == [own_id]
    assert gov_id not in response.text
    assert other_customer_id not in response.text
    for hidden in (gov_id, other_customer_id):
        missing = api.read(ALICE, hidden)
        assert missing.status_code == 404
        assert missing.json()["reason"] == "interaction_not_found"
    assert api.read(ALICE, own_id).status_code == 200


def test_explorer_of_another_cloud_returns_nothing(store: SpyStore) -> None:
    interaction_id = new_id()
    seed(store, record_doc(interaction_id, T0))
    api = Api(store, explorer=False)
    configure_interaction_explorer(
        api.h.app,
        InteractionExplorer(store=store, audit=api.audit, cloud="government", customer_id=CUSTOMER),
    )
    assert api.search(ALICE).json()["items"] == []
    assert store.queries == []
    assert api.read(ALICE, interaction_id).status_code == 404


# --- not configured -------------------------------------------------------------------------------


def test_unconfigured_explorer_is_503_with_a_stable_reason() -> None:
    api = Api(None, explorer=False)
    for response in (api.search(ALICE), api.read(ALICE, new_id())):
        assert response.status_code == 503
        assert response.json()["reason"] == "interaction_explorer_unconfigured"
    # Authorization still comes first: no data.read is 403, not 503.
    assert api.search(BOB).status_code == 403


# --- builder --------------------------------------------------------------------------------------


def _account_id() -> str:
    return (
        f"/subscriptions/{uuid.uuid4()}/resourceGroups/rg-ns/providers/"
        "Microsoft.Storage/storageAccounts/stnscontent"
    )


def _snapshot(*, enabled: bool, **body: Any) -> StoredSettingsSnapshot:
    setting = SystemSetting.model_validate(
        {
            "schema_version": "1.0.0",
            "setting_key": "interaction_capture",
            "enabled": enabled,
            "interaction_capture": {
                "kek_provider": "local_development",
                "kek_uri": None,
                "content_storage_account_resource_id": _account_id(),
                "content_container": "interaction-content",
                "credential": {"kind": "managed_identity", "managed_identity_client_id": None},
                "shed_capture_at_queue_percent": 75,
                "max_content_chars_per_interaction": 4096,
                **body,
            },
        }
    )
    entry = StoredSetting(
        "interaction_capture",  # pyright: ignore[reportArgumentType]
        "system.interaction_capture",
        setting,
        1,
        '"etag-1"',
    )
    return StoredSettingsSnapshot(
        status="loaded", entries=MappingProxyType({"interaction_capture": entry})
    )


class IngestStub:
    def __init__(self) -> None:
        self.attached: list[object] = []

    def attach_capture(self, edge: object) -> None:
        self.attached.append(edge)


class Composition:
    """The interactions and explorer builders over one hand-made composition state."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        snapshot: StoredSettingsSnapshot | None,
        opt_in: bool = True,
        audit: bool = True,
        env: str = "local",
        backends: dict[str, object] | None = None,
    ) -> None:
        self.app = FastAPI()
        # Capture builds only over an ingest service; it attaches at startup (never, here: the
        # policy store is empty, so capture stays off with ``no_policy``).
        self.app.state.ingest_service = IngestStub()
        self.state = CompositionState(
            app=self.app,
            settings=Settings(env=env, cloud=CloudName.COMMERCIAL),  # type: ignore[arg-type]
            overrides=CompositionOverrides(
                backends=MappingProxyType(
                    {"retention_policy": retention(opt_in=opt_in), **(backends or {})}
                ),
                cosmos_client_factory=self._no_cosmos,
            ),
            registry=ComponentRegistry(),
            environ={ENV_INTERACTION_LOCAL_KEY_FILE: str(tmp_path / "kek.bin")},
            lifetime=ClientLifetime(),
        )
        if snapshot is not None:
            self.state.shared[STORED_SETTINGS.name] = snapshot
        if audit:
            self.state.shared[AUDIT_REPOSITORY.name] = AuditRepository(InMemoryAuditStore())
        interactions.build(BuildContext(self.state, interactions.BUILDER))
        interaction_explorer.build(BuildContext(self.state, interaction_explorer.BUILDER))

    @staticmethod
    def _no_cosmos() -> Any:
        raise ComponentUnavailableError("cosmos_unconfigured")

    @property
    def explorer(self) -> tuple[str, str | None]:
        return (
            self.state.registry.get("interaction_explorer").state,
            self.app.state.interaction_explorer_off_reason,
        )


@pytest.fixture
def _customer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_AUTH_CUSTOMER_ID", CUSTOMER)


def test_component_is_optional_and_runs_right_after_interactions() -> None:
    assert "interaction_explorer" in OPTIONAL_COMPONENTS
    names = [spec.name for spec in default_builders()]
    assert names.index("interactions") + 1 == names.index("interaction_explorer")
    assert interaction_explorer.BUILDER.components == ("interaction_explorer",)


@pytest.mark.usefixtures("_customer_env")
def test_explorer_is_configured_when_capture_is_present_but_disabled(tmp_path: Path) -> None:
    composed = Composition(tmp_path, snapshot=_snapshot(enabled=False))
    assert composed.app.state.interaction_capture_off_reason == "setting_off"
    assert composed.explorer == ("ok", None)
    explorer = composed.app.state.interaction_explorer
    assert isinstance(explorer, InteractionExplorer)
    assert isinstance(explorer.store, InMemoryInteractionStore)
    assert (explorer.cloud, explorer.customer_id) == ("commercial", CUSTOMER)
    assert not composed.state.registry.get("interaction_explorer").blocks_readiness


@pytest.mark.usefixtures("_customer_env")
def test_capture_and_explorer_share_one_store_instance(tmp_path: Path) -> None:
    composed = Composition(tmp_path, snapshot=_snapshot(enabled=True))
    assert composed.explorer == ("ok", None)
    shared = composed.state.shared[interactions.INTERACTION_STORE.name]
    assert composed.app.state.interaction_explorer.store is shared
    # The factory hands every later caller the memoized instance...
    ctx = BuildContext(composed.state, interactions.BUILDER)
    assert interactions.interaction_store(ctx) is shared

    async def start() -> None:
        for _name, hook in composed.state.startup:
            await hook()

    # ...and capture's pipeline was built over that same instance.
    asyncio.run(start())
    edge = composed.app.state.interaction_capture
    assert edge is not None
    assert edge.pipeline._store is shared  # pyright: ignore[reportPrivateUsage]


@pytest.mark.usefixtures("_customer_env")
@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"snapshot": None}, "setting_absent"),
        ({"snapshot": "disabled", "opt_in": False}, "retention_not_enabled"),
        ({"snapshot": "disabled", "audit": False}, "audit_unavailable"),
    ],
)
def test_explorer_off_reasons(tmp_path: Path, kwargs: dict[str, Any], reason: str) -> None:
    if kwargs.get("snapshot") == "disabled":
        kwargs = {**kwargs, "snapshot": _snapshot(enabled=False)}
    composed = Composition(tmp_path, **kwargs)
    assert composed.explorer == ("disabled", reason)
    assert composed.app.state.interaction_explorer is None
    assert not composed.state.registry.get("interaction_explorer").blocks_readiness


def test_explorer_without_a_customer_is_customer_unconfigured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prebuilt = SpyStore(tmp_path)  # the local key wrapper needs NS_ENV=local to construct
    monkeypatch.setenv("NS_ENV", "dev")
    monkeypatch.delenv("NS_AUTH_CUSTOMER_ID", raising=False)
    composed = Composition(
        tmp_path,
        snapshot=_snapshot(enabled=False, kek_provider="key_vault_key", kek_uri=KEK_URI),
        env="dev",
        backends={"interaction_store": prebuilt},
    )
    assert composed.explorer == ("disabled", "customer_unconfigured")
    assert composed.app.state.interaction_explorer is None


def test_store_configuration_failure_is_reported_as_the_explorer_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NS_ENV", "dev")
    monkeypatch.setenv("NS_AUTH_CUSTOMER_ID", CUSTOMER)
    # local_development key outside NS_ENV=local is refused by the store factory.
    composed = Composition(tmp_path, snapshot=_snapshot(enabled=False), env="dev")
    assert composed.explorer == ("disabled", "local_key_not_allowed")
