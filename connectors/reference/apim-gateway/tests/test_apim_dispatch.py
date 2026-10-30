"""Default translators, the ``grant`` dispatcher and the item 10 follow-ups (PRP-34 item 10).

* ``grant`` requests route to the cap or the publication translator by diff grammar; a mixed or
  unrecognised diff is refused, never guessed;
* the cap edits the very fragment the publication created (aligned naming);
* an unpublish may delete only what the named publish apply record recorded ``created``;
* the diff grammar is tied to the action kind (``check_action``);
* the cap's before/after attribute diff is available through ``preview``.
"""

from __future__ import annotations

from typing import Any

import pytest
from apim_write_support import (  # pyright: ignore[reportMissingImports]
    GATEWAY,
    GATEWAY_ID,
    SERVICE_ETAG,
    mode_handler,
    request,
    upsert,
)
from neurosphere_connector.write import WriteRequest
from neurosphere_connector_apim_gateway import (
    ApimGatewayConnector,
    InMemoryApim,
    InMemoryApplyRecordStore,
    default_translators,
)
from neurosphere_connector_apim_gateway.cap import AttributeChange, BudgetCapTranslator
from neurosphere_connector_apim_gateway.dispatch import (
    GRANT_DIFF_AMBIGUOUS,
    GRANT_DIFF_UNRECOGNISED,
    GrantDispatchTranslator,
    grant_diff_family,
)
from neurosphere_connector_apim_gateway.grants import (
    APPLY_RECORD_PATH,
    PUBLICATION_PATH,
    RESOURCES_PATH,
    VERSION_PUBLISHED,
    VERSION_UNPUBLISHED,
    GrantPublicationTranslator,
    publication_names,
)
from neurosphere_connector_apim_gateway.mcp import InMemoryApiPathIndex, McpServerTranslator
from neurosphere_connector_apim_gateway.swap import BackendSwapTranslator
from neurosphere_contracts.actions.v1.action_intent import PatchOperation, ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_core.errors import CapabilityUnavailableError, InvalidSchemaError

GRANT_ID = "commercial:cust1:neurosphere:grant:g1"
OTHER_GRANT = "commercial:cust1:neurosphere:grant:g2"
OID = "11111111-2222-4333-8444-555555555555"
NAMES = publication_names(GRANT_ID)
MCP_ID = "commercial:cust1:neurosphere:mcp_server:tools"


def _diff(*ops: PatchOperation) -> ProposedDiff:
    return ProposedDiff(format="json_patch", operations=list(ops))


def grant_request(*ops: PatchOperation, version: str, grant: str = GRANT_ID) -> WriteRequest:
    return WriteRequest(
        target=TargetRef(canonical_id=grant, entity_type="grant"),
        target_version=version,
        proposed_diff=_diff(*ops),
    )


def publish_ops(**over: Any) -> list[PatchOperation]:
    value: dict[str, Any] = {
        "gateway_id": GATEWAY_ID,
        "api_id": "llm",
        "access": "subscription",
        "principal_kind": "application",
        "principal_object_id": OID,
        "tokens_per_minute": 5000,
    }
    value.update(over)
    return [PatchOperation(op="add", path=PUBLICATION_PATH, value=value)]


def unpublish_ops(names: list[str], record: str | None) -> list[PatchOperation]:
    ops = [PatchOperation(op="test", path="/publication/gateway_id", value=GATEWAY_ID)]
    if record is not None:
        ops.append(PatchOperation(op="test", path=APPLY_RECORD_PATH, value=record))
    ops += [
        PatchOperation(op="test", path=RESOURCES_PATH, value=names),
        PatchOperation(op="remove", path=PUBLICATION_PATH),
    ]
    return ops


def cap_ops(tpm: int = 8000) -> list[PatchOperation]:
    return [
        PatchOperation(op="test", path="/target/kind", value="model_api"),
        PatchOperation(op="test", path="/counter_key", value="subscription"),
        PatchOperation(op="replace", path="/limits/tokens_per_minute", value=tpm),
    ]


def make(
    *, records: InMemoryApplyRecordStore | None = None
) -> tuple[ApimGatewayConnector, InMemoryApim, InMemoryApplyRecordStore]:
    apim = InMemoryApim(service_etag=SERVICE_ETAG)
    apim.seed("apis/llm", {"displayName": "LLM", "path": "llm"})
    store = records if records is not None else InMemoryApplyRecordStore()
    counter = iter(range(1, 100))
    conn = ApimGatewayConnector(
        GATEWAY,
        apim,
        records=store,
        mode=mode_handler(apim),
        translators=default_translators(records=store, paths=InMemoryApiPathIndex(apim)),
        id_factory=lambda: f"apply-{next(counter)}",
    )
    return conn, apim, store


async def reviewed(conn: ApimGatewayConnector, req: WriteRequest) -> WriteRequest:
    result = await conn.dry_run(req)
    return req.model_copy(update={"proposed_diff": result.planned_diff})


async def published(conn: ApimGatewayConnector) -> str:
    """Publish the grant; returns the publish apply record id."""
    result = await conn.apply(
        await reviewed(conn, grant_request(*publish_ops(), version=VERSION_UNPUBLISHED))
    )
    assert result.rollback_token is not None
    return result.rollback_token


# -- default composition ---------------------------------------------------------------------


def test_default_translators_cover_every_apim_target_kind() -> None:
    records = InMemoryApplyRecordStore()
    translators = default_translators(records=records, paths=None)
    kinds = [t.entity_types for t in translators]
    assert kinds == [frozenset({"apim_backend"}), frozenset({"grant"}), frozenset({"mcp_server"})]
    swap, grant, mcp = translators
    assert isinstance(swap, BackendSwapTranslator)
    assert isinstance(grant, GrantDispatchTranslator)
    assert isinstance(grant.cap, BudgetCapTranslator)
    assert isinstance(grant.publication, GrantPublicationTranslator)
    assert isinstance(mcp, McpServerTranslator)


# -- dispatch --------------------------------------------------------------------------------


def test_grant_diffs_route_by_grammar() -> None:
    dispatcher = GrantDispatchTranslator()
    digest = PatchOperation(op="test", path="/plan_digest", value="0" * 64)
    cap = grant_request(digest, *cap_ops(), version="e")
    publish = grant_request(digest, *publish_ops(), version=VERSION_UNPUBLISHED)
    unpublish = grant_request(*unpublish_ops([NAMES.product], "r"), version=VERSION_PUBLISHED)
    assert grant_diff_family(cap) == "cap"
    assert dispatcher.route(cap) is dispatcher.cap
    assert grant_diff_family(publish) == "publication"
    assert dispatcher.route(publish) is dispatcher.publication
    assert dispatcher.route(unpublish) is dispatcher.publication


@pytest.mark.parametrize(
    ("ops", "reason"),
    [
        ([*cap_ops(), *publish_ops()], GRANT_DIFF_AMBIGUOUS),
        (
            [
                PatchOperation(op="test", path="/counter_key", value="subscription"),
                PatchOperation(op="remove", path=PUBLICATION_PATH),
            ],
            GRANT_DIFF_AMBIGUOUS,
        ),
        ([PatchOperation(op="replace", path="/enabled", value=False)], GRANT_DIFF_UNRECOGNISED),
        ([*cap_ops(), PatchOperation(op="add", path="/notes", value="x")], GRANT_DIFF_UNRECOGNISED),
        ([PatchOperation(op="test", path="/plan_digest", value="0" * 64)], GRANT_DIFF_UNRECOGNISED),
    ],
)
async def test_ambiguous_or_unrecognised_grant_diffs_are_refused(
    ops: list[PatchOperation], reason: str
) -> None:
    conn, apim, _ = make()
    with pytest.raises(InvalidSchemaError) as caught:
        await conn.dry_run(grant_request(*ops, version="e"))
    assert caught.value.reason == reason
    assert apim.writes() == []


async def test_cap_routed_through_the_dispatcher_edits_the_publication_fragment() -> None:
    conn, apim, _ = make()
    await published(conn)
    etag = apim.etag_of(NAMES.fragment)
    assert etag is not None
    cap = grant_request(*cap_ops(8000), version=etag)
    changes = await conn.preview(cap)
    assert changes == [AttributeChange("tokens-per-minute", "5000", "8000")]
    result = await conn.apply(await reviewed(conn, cap))
    puts = [c.path for c in apim.writes() if c.method == "PUT"]
    assert puts[-1] == NAMES.fragment  # the very fragment the publication created
    assert 'tokens-per-minute="8000"' in str(apim.resources[NAMES.fragment][0]["value"])
    description = apim.resources[NAMES.fragment][0]["description"]
    assert description == "NeuroSphere grant " + NAMES.fragment.split("/")[1]
    assert result.rollback_token is not None


async def test_publication_routed_through_the_dispatcher_and_preview_is_empty() -> None:
    conn, apim, _ = make()
    req = grant_request(*publish_ops(), version=VERSION_UNPUBLISHED)
    assert await conn.preview(req) == []
    assert apim.writes() == []
    await published(conn)
    assert NAMES.product in apim.resources


# -- unpublish ownership (item 5 review follow-up) ----------------------------------------------


async def test_unpublish_of_created_resources_named_by_the_record_runs() -> None:
    conn, apim, _ = make()
    record = await published(conn)
    created = [NAMES.subscription, NAMES.link("llm"), NAMES.product_policy, NAMES.product]
    req = grant_request(*unpublish_ops(created, record), version=VERSION_PUBLISHED)
    await conn.apply(await reviewed(conn, req))
    assert set(apim.resources) == {"apis/llm", NAMES.fragment}


async def test_unpublish_listing_a_found_resource_is_refused_not_deleted() -> None:
    conn, apim, _ = make()
    apim.seed(NAMES.product, {"displayName": "pre-existing", "state": "published"})
    result = await conn.apply(
        await reviewed(conn, grant_request(*publish_ops(), version=VERSION_PUBLISHED))
    )
    assert result.rollback_token is not None
    req = grant_request(
        *unpublish_ops([NAMES.product_policy, NAMES.product], result.rollback_token),
        version=VERSION_PUBLISHED,
    )
    writes = len(apim.writes())
    with pytest.raises(InvalidSchemaError) as caught:
        await conn.dry_run(req)
    assert caught.value.reason == "resource_not_created"
    with pytest.raises(InvalidSchemaError):
        await conn.apply(req)
    assert NAMES.product in apim.resources
    assert len(apim.writes()) == writes


async def test_unpublish_needs_a_matching_succeeded_record() -> None:
    conn, apim, records = make()
    record = await published(conn)
    listed = [NAMES.product]
    with pytest.raises(InvalidSchemaError) as missing:
        await conn.dry_run(grant_request(*unpublish_ops(listed, None), version=VERSION_PUBLISHED))
    assert missing.value.reason == "apply_record_required"
    with pytest.raises(InvalidSchemaError) as unknown:
        await conn.dry_run(
            grant_request(*unpublish_ops(listed, "apply-99"), version=VERSION_PUBLISHED)
        )
    assert unknown.value.reason == "ownership_record_mismatch"
    # A record of another grant cannot vouch for this grant's resources.
    other = publication_names(OTHER_GRANT)
    await conn.apply(
        await reviewed(
            conn, grant_request(*publish_ops(), version=VERSION_UNPUBLISHED, grant=OTHER_GRANT)
        )
    )
    other_record = "apply-2"
    assert (await records.latest(other_record)) is not None
    with pytest.raises(InvalidSchemaError) as foreign:
        await conn.dry_run(
            grant_request(*unpublish_ops(listed, other_record), version=VERSION_PUBLISHED)
        )
    assert foreign.value.reason == "ownership_record_mismatch"
    assert other.product in apim.resources
    # A rolled-back publish vouches for nothing.
    latest = await records.latest(record)
    assert latest is not None
    await records.append(latest.model_copy(update={"status": "rolled_back"}))
    with pytest.raises(InvalidSchemaError) as rolled:
        await conn.dry_run(grant_request(*unpublish_ops(listed, record), version=VERSION_PUBLISHED))
    assert rolled.value.reason == "ownership_record_mismatch"


async def test_unpublish_without_a_record_store_is_refused() -> None:
    apim = InMemoryApim(service_etag=SERVICE_ETAG)
    apim.seed(NAMES.product, {"displayName": "x"})
    conn = ApimGatewayConnector(
        GATEWAY,
        apim,
        records=InMemoryApplyRecordStore(),
        mode=mode_handler(apim),
        translators=[GrantPublicationTranslator()],
    )
    with pytest.raises(CapabilityUnavailableError) as caught:
        await conn.dry_run(
            grant_request(*unpublish_ops([NAMES.product], "apply-1"), version=VERSION_PUBLISHED)
        )
    assert caught.value.reason == "ownership_unverifiable"
    assert apim.writes() == []


# -- action kind tie (item 5 review follow-up) ---------------------------------------------------


def _mcp(stage: str) -> WriteRequest:
    return WriteRequest(
        target=TargetRef(canonical_id=MCP_ID, entity_type="mcp_server"),
        target_version="mcp-denied",
        proposed_diff=_diff(
            PatchOperation(
                op="replace",
                path=PUBLICATION_PATH,
                value={"stage": stage, "gateway_id": GATEWAY_ID},
            )
        ),
    )


def _mode() -> WriteRequest:
    return WriteRequest(
        target=TargetRef(
            canonical_id=f"commercial:cust1:apim:apim_gateway_mode:{GATEWAY_ID}",
            entity_type="apim_gateway_mode",
        ),
        target_version="mode-r0-observe",
        proposed_diff=_diff(PatchOperation(op="replace", path="/mode", value="manage")),
    )


@pytest.mark.parametrize(
    ("kind", "req"),
    [
        ("grant_publish", grant_request(*publish_ops(), version=VERSION_UNPUBLISHED)),
        ("grant_unpublish", grant_request(*unpublish_ops(["x"], "r"), version=VERSION_PUBLISHED)),
        ("budget_cap_change", grant_request(*cap_ops(), version="e")),
        ("mcp_server_publish", _mcp("change")),
        ("mcp_server_publish", _mcp("deny")),
        ("mcp_server_unpublish", _mcp("deny")),
        ("mcp_server_unpublish", _mcp("remove")),
        ("gateway_mode_change", _mode()),
    ],
)
def test_matching_kind_and_grammar_pass(kind: str, req: WriteRequest) -> None:
    conn, _, _ = make()
    conn.check_action(kind, req)


@pytest.mark.parametrize(
    ("kind", "req"),
    [
        ("grant_unpublish", grant_request(*publish_ops(), version=VERSION_UNPUBLISHED)),
        ("grant_publish", grant_request(*unpublish_ops(["x"], "r"), version=VERSION_PUBLISHED)),
        ("grant_publish", grant_request(*cap_ops(), version="e")),
        ("budget_cap_change", grant_request(*publish_ops(), version=VERSION_UNPUBLISHED)),
        ("mcp_server_publish", _mcp("remove")),
        ("mcp_server_unpublish", _mcp("change")),
        ("mcp_server_unpublish", _mcp("publish")),
        ("grant_publish", _mcp("publish")),
        ("grant_publish", _mode()),
        ("gateway_mode_change", grant_request(*publish_ops(), version=VERSION_UNPUBLISHED)),
    ],
)
def test_a_grammar_under_another_kind_is_refused(kind: str, req: WriteRequest) -> None:
    conn, _, _ = make()
    with pytest.raises(InvalidSchemaError) as caught:
        conn.check_action(kind, req)
    assert caught.value.reason == "action_kind_mismatch"


def test_the_generic_gateway_target_has_no_kind_grammar() -> None:
    conn, _, _ = make()
    conn.check_action("grant_publish", request(upsert("products/p1", {"displayName": "p"})))
