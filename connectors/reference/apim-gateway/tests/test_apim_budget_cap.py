"""PRP-34 item 4: ``budget_cap_change`` against a ``grant`` target (in-memory APIM double)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import pytest
from apim_write_support import GATEWAY, make  # pyright: ignore[reportMissingImports]
from neurosphere_connector.write import WriteRequest
from neurosphere_connector_apim_gateway import (
    ApimGatewayConnector,
    InMemoryApim,
    InMemoryApplyRecordStore,
    IntentTranslator,
    ResourceType,
)
from neurosphere_connector_apim_gateway.cap import (
    LIMIT_ATTRIBUTES,
    MCP_GRANT_TOKEN_LIMIT,
    AttributeChange,
    BudgetCapTranslator,
    attribute_diff,
    grant_fragment_id,
    limit_attributes,
    parse_cap_diff,
    parse_grant_fragment,
)
from neurosphere_connector_apim_gateway.policies import (
    COUNTER_KEYS,
    GrantLimits,
    McpEnforcement,
    fragment_payload,
    load_template,
    render_grant_fragment,
    render_mcp_enforcement_fragment,
)
from neurosphere_contracts.actions.v1.action_intent import PatchOperation, ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_core.errors import InvalidSchemaError, StaleVersionError

GRANT_ID = "commercial:cust1:catalog:grant:g1"
FRAGMENT = "policyFragments/" + grant_fragment_id(GRANT_ID)
PRIOR = GrantLimits(counter_key="subscription", tokens_per_minute=5000)
PRIOR_XML = render_grant_fragment(PRIOR)
DIMENSIONS = ["API ID", "Subscription ID", "x-ns-cost-center"]

Op = tuple[str, str, Any]


def _parse(xml: str) -> ET.Element:
    return ET.fromstring(xml)  # noqa: S314 - our own rendered text


def grant_target(cloud: str = "commercial") -> TargetRef:
    return TargetRef(canonical_id=GRANT_ID.replace("commercial", cloud, 1), entity_type="grant")


def facts(kind: str = "model_api", counter: str = "subscription") -> list[Op]:
    return [("test", "/target/kind", kind), ("test", "/counter_key", counter)]


def cap_request(
    *ops: Op, version: str, kind: str = "model_api", counter: str = "subscription"
) -> WriteRequest:
    return WriteRequest(
        target=grant_target(),
        target_version=version,
        proposed_diff=ProposedDiff(
            format="json_patch",
            operations=[
                PatchOperation(op=o, path=p, value=v)  # type: ignore[arg-type]
                for o, p, v in [*facts(kind, counter), *ops]
            ],
        ),
    )


def setup(
    xml: str = PRIOR_XML,
) -> tuple[ApimGatewayConnector, InMemoryApim, InMemoryApplyRecordStore, str]:
    conn, apim, records = make()
    conn.register_translator(BudgetCapTranslator())
    etag = apim.seed(FRAGMENT, fragment_payload(xml, description="grant g1"))
    return conn, apim, records, etag


def raise_tpm(etag: str, value: int = 8000) -> WriteRequest:
    return cap_request(("replace", "/limits/tokens_per_minute", value), version=etag)


async def reviewed(conn: ApimGatewayConnector, req: WriteRequest) -> WriteRequest:
    result = await conn.dry_run(req)
    return req.model_copy(update={"proposed_diff": result.planned_diff})


def live_xml(apim: InMemoryApim) -> str:
    value = apim.resources[FRAGMENT][0]["value"]
    assert isinstance(value, str)
    return value


# -- seam ----------------------------------------------------------------------------------


def test_translator_fits_the_seam_and_names_a_policy_fragment() -> None:
    translator = BudgetCapTranslator()
    assert isinstance(translator, IntentTranslator)
    assert translator.entity_types == frozenset({"grant"})
    specs = translator.specs(GATEWAY, raise_tpm('"x"'))
    assert [(s.resource_type, s.name, s.operation) for s in specs] == [
        (ResourceType.POLICY_FRAGMENT, FRAGMENT, "upsert")
    ]
    assert specs[0].payload is not None and specs[0].payload["format"] == "rawxml"
    # Constructed explicitly: the default connector does not handle grants until wired.
    assert grant_fragment_id(GRANT_ID).startswith("ns-grant-")
    custom = BudgetCapTranslator(fragment_id=lambda gid: "ns-grant-g1")
    assert custom.fragment_path(GATEWAY, raise_tpm('"x"')) == "policyFragments/ns-grant-g1"


# -- dry run -------------------------------------------------------------------------------


async def test_dry_run_renders_the_fragment_and_diffs_attributes_without_writing() -> None:
    conn, apim, _, etag = setup()
    req = raise_tpm(etag)
    result = await conn.dry_run(req)
    assert result.would_change is True
    assert result.planned_diff.operations[0].path == "/plan_digest"
    assert apim.writes() == []
    plan = await conn.plan(req)
    assert [(s.name, s.expected, s.changes) for s in plan.steps] == [(FRAGMENT, "found", True)]

    changes = await BudgetCapTranslator().preview(apim, GATEWAY, req)
    assert changes == [AttributeChange("tokens-per-minute", "5000", "8000")]


async def test_same_cap_is_a_no_op_plan() -> None:
    conn, _, _, etag = setup()
    result = await conn.dry_run(raise_tpm(etag, 5000))
    assert result.would_change is False


def test_attribute_diff_covers_quota_and_period() -> None:
    after = render_grant_fragment(
        GrantLimits(
            counter_key="subscription",
            token_quota=100000,
            token_quota_period="Daily",  # noqa: S106
        )
    )
    assert attribute_diff(PRIOR_XML, after) == [
        AttributeChange("tokens-per-minute", "5000", None),
        AttributeChange("token-quota", None, "100000"),
        AttributeChange("token-quota-period", None, "Daily"),
    ]
    assert set(limit_attributes(after)) <= set(LIMIT_ATTRIBUTES)


# -- apply / verify / rollback ---------------------------------------------------------------


async def test_apply_puts_the_fragment_with_if_match_from_the_read() -> None:
    conn, apim, records, etag = setup()
    req = await reviewed(conn, raise_tpm(etag))
    applied = await conn.apply(req)
    puts = [c for c in apim.writes() if c.method == "PUT"]
    assert [(c.path, c.if_match) for c in puts] == [(FRAGMENT, etag)]
    assert parse_grant_fragment(live_xml(apim)).tokens_per_minute == 8000
    assert applied.version_before == etag
    assert applied.version_after == apim.etag_of(FRAGMENT) != etag
    record = await records.latest(applied.rollback_token or "")
    assert record is not None and record.status == "succeeded"
    assert [(s.ownership.value, s.wrote) for s in record.steps] == [("found", True)]


async def test_verify_reads_the_fragment_back_and_detects_a_mismatch() -> None:
    conn, apim, _, etag = setup()
    req = await reviewed(conn, raise_tpm(etag))
    await conn.apply(req)
    assert (await conn.verify(req)).matched is True

    apim.reformat_policies = True  # APIM re-indents on save; still a match
    tampered = render_grant_fragment(GrantLimits(counter_key="subscription", tokens_per_minute=1))
    apim.seed(FRAGMENT, fragment_payload(tampered))
    result = await conn.verify(req)
    assert result.matched is False
    assert len(result.mismatched_paths) == 1
    assert "<" not in repr(result.observed_state)


async def test_rollback_restores_the_captured_prior_fragment() -> None:
    conn, apim, _, etag = setup()
    before = apim.snapshot()
    applied = await conn.apply(await reviewed(conn, raise_tpm(etag)))
    assert apim.snapshot() != before
    result = await conn.rollback(applied)
    assert result.status == "rolled_back"
    assert apim.snapshot() == before
    assert parse_grant_fragment(live_xml(apim)) == PRIOR
    assert (await conn.rollback(applied)).status == "not_needed"


async def test_quota_change_with_period_mapping_round_trips() -> None:
    conn, apim, _, etag = setup()
    req = cap_request(
        ("remove", "/limits/tokens_per_minute", None),
        ("add", "/limits/token_quota", 250000),
        ("add", "/limits/quota_period", "month"),
        version=etag,
    )
    await conn.apply(await reviewed(conn, req))
    live = parse_grant_fragment(live_xml(apim))
    assert (live.tokens_per_minute, live.token_quota, live.token_quota_period) == (
        None,
        250000,
        "Monthly",
    )


# -- refusals ------------------------------------------------------------------------------


async def test_mcp_target_grant_refuses_token_limits() -> None:
    conn, apim, _, etag = setup()
    req = cap_request(("replace", "/limits/tokens_per_minute", 10), version=etag, kind="mcp_server")
    with pytest.raises(InvalidSchemaError) as err:
        await conn.dry_run(req)
    assert err.value.reason == MCP_GRANT_TOKEN_LIMIT
    assert apim.writes() == []


async def test_mcp_enforcement_fragment_is_refused_even_if_the_diff_says_model() -> None:
    mcp = render_mcp_enforcement_fragment(
        McpEnforcement(
            tenant_named_value="ns-tenant",
            audience_named_value="ns-audience",
            calls=60,
            renewal_period_seconds=60,
        )
    )
    conn, apim, _, etag = setup(mcp)
    with pytest.raises(InvalidSchemaError) as err:
        await conn.dry_run(raise_tpm(etag))
    assert err.value.reason == MCP_GRANT_TOKEN_LIMIT
    assert apim.writes() == []


async def test_stale_etag_is_stale_version() -> None:
    conn, apim, _, etag = setup()
    apim.seed(FRAGMENT, fragment_payload(PRIOR_XML))  # someone saved the fragment again
    with pytest.raises(StaleVersionError) as err:
        await conn.dry_run(raise_tpm(etag))
    assert err.value.reason == "target_version_changed"


async def test_concurrent_change_before_the_put_is_a_412_and_nothing_is_overwritten() -> None:
    conn, apim, _, etag = setup()
    req = await reviewed(conn, raise_tpm(etag))
    concurrent = render_grant_fragment(GrantLimits(counter_key="subscription", tokens_per_minute=7))

    def race(method: str, path: str) -> None:
        if method == "PUT" and path == FRAGMENT and apim.before is not None:
            apim.before = None
            apim.seed(FRAGMENT, fragment_payload(concurrent))

    apim.before = race
    with pytest.raises(StaleVersionError) as err:
        await conn.apply(req)
    assert err.value.reason == "etag_mismatch"
    assert live_xml(apim) == concurrent


@pytest.mark.parametrize(
    ("ops", "reason"),
    [
        # The live token-per-minute limit is neither replaced nor removed.
        ([("add", "/limits/token_quota", 5), ("add", "/limits/quota_period", "day")], None),
        ([("replace", "/limits/tokens_per_minute", 0)], "bad_limits"),
        ([("replace", "/limits/tokens_per_minute", True)], "bad_limits"),
        ([("replace", "/limits/token_quota", 5)], "bad_limits"),
        (
            [
                ("replace", "/limits/tokens_per_minute", 5),
                ("add", "/limits/token_quota", 5),
                ("add", "/limits/quota_period", "minute"),
            ],
            "unsupported_quota_period",
        ),
        ([("remove", "/limits/tokens_per_minute", None)], "bad_limits"),
        ([("replace", "/limits/requests_per_minute", 5)], "unsupported_operation"),
        ([("move", "/limits/tokens_per_minute", 5)], "unsupported_operation"),
        (
            [("replace", "/limits/tokens_per_minute", 5)] * 2,
            "duplicate_operation",
        ),
    ],
)
async def test_bad_cap_diffs_are_refused(ops: list[Op], reason: str | None) -> None:
    conn, apim, _, etag = setup()
    with pytest.raises(InvalidSchemaError) as err:
        await conn.dry_run(cap_request(*ops, version=etag))
    assert err.value.reason == (reason or "cap_diff_incomplete")
    assert apim.writes() == []


async def test_counter_key_never_moves_and_facts_are_required() -> None:
    conn, _, _, etag = setup()
    with pytest.raises(InvalidSchemaError) as err:
        await conn.dry_run(
            cap_request(("replace", "/limits/tokens_per_minute", 9), version=etag, counter="oid")
        )
    assert err.value.reason == "counter_key_mismatch"
    bare = WriteRequest(
        target=grant_target(),
        target_version=etag,
        proposed_diff=ProposedDiff(
            format="json_patch",
            operations=[PatchOperation(op="replace", path="/limits/tokens_per_minute", value=9)],
        ),
    )
    with pytest.raises(InvalidSchemaError) as err:
        await conn.dry_run(bare)
    assert err.value.reason == "grant_target_kind_required"


async def test_foreign_fragment_content_is_never_overwritten() -> None:
    foreign = PRIOR_XML.replace(
        "</fragment>", '\t<set-header name="x-owner" exists-action="override" />\n</fragment>'
    )
    conn, apim, _, etag = setup(foreign)
    with pytest.raises(InvalidSchemaError) as err:
        await conn.dry_run(raise_tpm(etag))
    assert err.value.reason == "grant_fragment_unrecognised"
    with pytest.raises(InvalidSchemaError):
        parse_grant_fragment('<!DOCTYPE x [<!ENTITY a "b">]><fragment>&a;</fragment>')
    assert apim.writes() == []


async def test_unpublished_grant_and_wrong_cloud_are_refused() -> None:
    conn, apim, _, _ = setup()
    del apim.resources[FRAGMENT]
    with pytest.raises(InvalidSchemaError) as err:
        await conn.dry_run(raise_tpm('"etag-1"'))
    assert err.value.reason == "grant_not_published"
    gov = raise_tpm('"etag-1"').model_copy(update={"target": grant_target("government")})
    with pytest.raises(InvalidSchemaError) as err:
        await conn.dry_run(gov)
    assert err.value.reason == "cloud_mismatch"


# -- policy template: metric dimensions and XML ------------------------------------------------


def _dimensions(xml: str) -> list[ET.Element]:
    metric = _parse(xml).find("llm-emit-token-metric")
    assert metric is not None
    return metric.findall("dimension")


@pytest.mark.parametrize(
    "limits",
    [
        PRIOR,
        GrantLimits(counter_key="oid", token_quota=10, token_quota_period="Yearly"),  # noqa: S106
        GrantLimits(
            counter_key="oid",
            tokens_per_minute=1,
            token_quota=2,
            token_quota_period="Hourly",  # noqa: S106
            metric_namespace="ns-custom",
        ),
    ],
)
def test_rendered_grant_fragment_parses_and_carries_the_cost_center_dimension(
    limits: GrantLimits,
) -> None:
    xml = render_grant_fragment(limits)
    root = _parse(xml)
    assert root.tag == "fragment"
    limit = root.find("llm-token-limit")
    assert limit is not None and limit.get("counter-key") == COUNTER_KEYS[limits.counter_key]
    dims = _dimensions(xml)
    assert [d.get("name") for d in dims] == DIMENSIONS
    assert len(dims) <= 5  # llm-emit-token-metric allows at most 5 dimensions
    cost = dims[2].get("value") or ""
    assert '"x-ns-cost-center"' in cost and '"N/A"' in cost
    assert parse_grant_fragment(xml) == limits


def test_template_text_declares_the_dimensions() -> None:
    text = load_template("grant-product.xml")
    for name in DIMENSIONS:
        assert f'<dimension name="{name}"' in text


def test_diff_parser_maps_contract_periods() -> None:
    intent = parse_cap_diff(
        ProposedDiff(
            format="json_patch",
            operations=[
                PatchOperation(op="test", path="/target/kind", value="model_deployment"),
                PatchOperation(op="test", path="/counter_key", value="oid"),
                PatchOperation(op="add", path="/limits/token_quota", value=7),
                PatchOperation(op="add", path="/limits/quota_period", value="week"),
            ],
        )
    )
    assert intent.limits.token_quota_period == "Weekly"  # noqa: S105
    assert intent.named == frozenset({"token_quota", "quota_period"})
