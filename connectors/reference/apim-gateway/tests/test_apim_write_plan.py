"""Planning: dependency order, create/found expectations, digest binding and refusals."""

from __future__ import annotations

import pytest
from apim_write_support import (  # pyright: ignore[reportMissingImports]
    EXPECTED_ORDER,
    GATEWAY_ID,
    PUBLICATION,
    SERVICE_ETAG,
    make,
    publication_ops,
    remove,
    request,
    reviewed,
    upsert,
)
from neurosphere_connector_apim_gateway import (
    DEPENDENCY_ORDER,
    PLAN_DIGEST_PATH,
    PublishPlan,
    ResourceSpec,
    ResourceType,
)
from neurosphere_connector_apim_gateway.planner import check_plan_integrity
from neurosphere_core.errors import InvalidSchemaError, StaleVersionError


def test_dependency_order_is_the_load_bearing_sequence() -> None:
    assert [t.value for t in DEPENDENCY_ORDER] == [
        "named_value",
        "backend",
        "policy_fragment",
        "api",
        "api_operation",
        "api_policy",
        "product",
        "product_policy",
        "product_api_link",
        "subscription",
    ]


async def test_dry_run_orders_steps_and_writes_nothing() -> None:
    conn, apim, _ = make()
    req = request(*publication_ops(reverse=True))
    plan = await conn.plan(req)
    assert [s.name for s in plan.steps] == EXPECTED_ORDER
    assert [s.index for s in plan.steps] == list(range(len(EXPECTED_ORDER)))
    assert all(s.expected == "create" and s.changes for s in plan.steps)
    assert all(s.payload_digest and len(s.payload_digest) == 64 for s in plan.steps)
    assert len(plan.digest) == 64
    assert plan.gateway_id == GATEWAY_ID
    assert plan.target_version == SERVICE_ETAG

    result = await conn.dry_run(req)
    assert result.would_change is True
    first = result.planned_diff.operations[0]
    assert (first.op, first.path, first.value) == ("test", PLAN_DIGEST_PATH, plan.digest)
    assert apim.writes() == []


async def test_input_order_does_not_change_the_plan() -> None:
    conn, _, _ = make()
    a = await conn.plan(request(*publication_ops(reverse=True)))
    b = await conn.plan(request(*publication_ops(reverse=False)))
    assert a == b


async def test_existing_resources_are_expected_found_and_unchanged_ones_write_nothing() -> None:
    conn, apim, _ = make()
    apim.seed("backends/foundry", PUBLICATION["backends/foundry"])
    apim.seed("apis/llm", {**PUBLICATION["apis/llm"], "isCurrent": True})
    plan = await conn.plan(request(*publication_ops()))
    by_name = {s.name: s for s in plan.steps}
    assert by_name["backends/foundry"].expected == "found"
    assert by_name["backends/foundry"].changes is False
    assert by_name["apis/llm"].expected == "found"  # ARM-added fields are ignored
    assert by_name["apis/llm"].changes is False
    assert by_name["products/ns-grant-g1"].expected == "create"


async def test_rerun_of_identical_publication_would_not_change() -> None:
    conn, apim, _ = make()
    for name, props in PUBLICATION.items():
        apim.seed(name, props)
    apim.reformat_policies = True  # stored XML differs in whitespace only
    for name in ("policyFragments/ns-grant-g1", "apis/llm/policies/policy"):
        props = dict(PUBLICATION[name])
        props["value"] = str(props["value"]).replace("><", ">\n  <")
        apim.seed(name, props)
    result = await conn.dry_run(request(*publication_ops()))
    assert result.would_change is False


async def test_digest_changes_when_payload_or_gateway_state_changes() -> None:
    conn, apim, _ = make()
    base = await conn.plan(request(*publication_ops()))
    changed = dict(PUBLICATION["backends/foundry"], url="https://other.openai.azure.com/openai")
    swapped = upsert("backends/foundry", changed)
    ops = [swapped if o[1] == swapped[1] else o for o in publication_ops()]
    other = await conn.plan(request(*ops))
    assert other.digest != base.digest
    apim.seed("products/ns-grant-g1", {"displayName": "someone else"})
    appeared = await conn.plan(request(*publication_ops()))
    assert appeared.digest != base.digest


async def test_dry_run_refuses_a_reviewed_digest_that_no_longer_matches() -> None:
    conn, apim, _ = make()
    req = await reviewed(conn, request(*publication_ops()))
    apim.seed("apis/llm", {"displayName": "concurrent"})
    with pytest.raises(StaleVersionError) as err:
        await conn.dry_run(req)
    assert err.value.reason == "plan_digest_mismatch"


async def test_stale_target_version_is_refused() -> None:
    conn, _, _ = make()
    with pytest.raises(StaleVersionError) as err:
        await conn.dry_run(request(*publication_ops(), version='"svc-0"'))
    assert err.value.reason == "target_version_changed"


@pytest.mark.parametrize(
    ("ops", "reason"),
    [
        # Named value without a key-authenticated backend in the plan.
        (
            [upsert("namedValues/foundry-key", PUBLICATION["namedValues/foundry-key"])],
            "named_value_without_key_backend",
        ),
        # Named value carrying a literal value instead of a Key Vault reference.
        (
            [upsert("namedValues/k", {"displayName": "k", "value": "s3cret", "secret": True})],
            "secret_in_payload",
        ),
        (
            [upsert("namedValues/k", {"displayName": "k", "secret": False})],
            "named_value_requires_key_vault",
        ),
        # Backend with a literal credential.
        (
            [
                upsert(
                    "backends/b",
                    {"url": "https://x", "credentials": {"header": {"api-key": ["abc"]}}},
                )
            ],
            "literal_credential",
        ),
        # Subscription keys are never written.
        (
            [upsert("subscriptions/s", {"scope": "/products/p", "primaryKey": "k"})],
            "secret_in_payload",
        ),
        # Secret-listing action and foreign paths.
        ([upsert("subscriptions/s/listSecrets", {})], "forbidden_path"),
        ([upsert("namedValues/n/listValue", {})], "forbidden_path"),
        ([("add", "/resources/..~1..~1providers", {})], "bad_path"),
        ([("add", "/resources/backends~1b/url", "https://x")], "unsupported_operation"),
        ([("move", "/resources/backends~1b", None)], "unsupported_operation"),
        ([("add", "/resources/backends~1b", "not-an-object")], "bad_payload"),
    ],
)
async def test_unsafe_or_malformed_specs_are_refused(ops: list, reason: str) -> None:  # type: ignore[type-arg]
    conn, apim, _ = make()
    with pytest.raises(InvalidSchemaError) as err:
        await conn.dry_run(request(*ops))
    assert err.value.reason == reason
    assert apim.writes() == []


async def test_named_value_for_a_key_backend_is_planned() -> None:
    conn, _, _ = make()
    plan = await conn.plan(
        request(
            upsert("namedValues/foundry-key", PUBLICATION["namedValues/foundry-key"]),
            upsert("backends/foundry", PUBLICATION["backends/foundry"]),
        )
    )
    assert [s.resource_type for s in plan.steps] == [ResourceType.NAMED_VALUE, ResourceType.BACKEND]


async def test_deletes_run_after_upserts_in_reverse_dependency_order() -> None:
    conn, apim, _ = make()
    for name, props in PUBLICATION.items():
        apim.seed(name, props)
    deny = dict(
        PUBLICATION["apis/llm/policies/policy"],
        value="<policies><inbound><base /></inbound></policies>",
    )
    plan = await conn.plan(
        request(
            remove("backends/foundry"),
            remove("subscriptions/ns-grant-g1-team"),
            remove("products/ns-grant-g1/apiLinks/llm"),
            upsert("apis/llm/policies/policy", deny),
        )
    )
    assert [(s.operation, s.name) for s in plan.steps] == [
        ("upsert", "apis/llm/policies/policy"),
        ("delete", "subscriptions/ns-grant-g1-team"),
        ("delete", "products/ns-grant-g1/apiLinks/llm"),
        ("delete", "backends/foundry"),
    ]
    assert all(s.expected == "found" for s in plan.steps)


async def test_delete_of_absent_resource_is_omitted() -> None:
    conn, _, _ = make()
    plan = await conn.plan(
        request(remove("backends/gone"), upsert("apis/llm", PUBLICATION["apis/llm"]))
    )
    assert [s.name for s in plan.steps] == ["apis/llm"]


def _specs() -> list[ResourceSpec]:
    return [
        ResourceSpec(
            resource_type=ResourceType.BACKEND, name="backends/foundry", payload={"url": "u"}
        ),
        ResourceSpec(resource_type=ResourceType.API, name="apis/llm", payload={"path": "llm"}),
    ]


async def _plan() -> PublishPlan:
    conn, _, _ = make()
    return await conn.plan(
        request(upsert("backends/foundry", {"url": "u"}), upsert("apis/llm", {"path": "llm"}))
    )


async def test_integrity_check_refuses_tampered_digest_order_or_payload() -> None:
    plan = await _plan()
    assert set(check_plan_integrity(plan, _specs())) == {0, 1}

    bad_digest = plan.model_copy(update={"digest": "0" * 64})
    with pytest.raises(StaleVersionError) as err:
        check_plan_integrity(bad_digest, _specs())
    assert err.value.reason == "plan_digest_mismatch"

    # Reordered steps with a recomputed digest still fail the order check.
    from neurosphere_connector_apim_gateway.digest import plan_digest

    swapped = (
        plan.steps[1].model_copy(update={"index": 0}),
        plan.steps[0].model_copy(update={"index": 1}),
    )
    reordered = plan.model_copy(
        update={
            "steps": swapped,
            "digest": plan_digest(
                gateway_id=plan.gateway_id,
                target=plan.target,
                target_version=plan.target_version,
                steps=swapped,
            ),
        }
    )
    with pytest.raises(StaleVersionError):
        check_plan_integrity(reordered, _specs())

    changed = [_specs()[0], _specs()[1].model_copy(update={"payload": {"path": "other"}})]
    with pytest.raises(StaleVersionError):
        check_plan_integrity(plan, changed)
