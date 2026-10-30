"""Grant publish and unpublish through the APIM write connector (PRP-34 item 5)."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any

import pytest
from apim_write_support import (  # pyright: ignore[reportMissingImports]
    ARM_ID,
    GATEWAY,
    GATEWAY_ID,
    SERVICE_ETAG,
    mode_handler,
)
from neurosphere_connector.write import WriteRequest
from neurosphere_connector_apim_gateway import (
    ApimGatewayConnector,
    InMemoryApim,
    InMemoryApplyRecordStore,
    StepOwnership,
)
from neurosphere_connector_apim_gateway.grants import (
    PUBLICATION_PATH,
    RESOURCES_PATH,
    VERSION_PUBLISHED,
    VERSION_UNPUBLISHED,
    GrantPublicationTranslator,
    publication_names,
)
from neurosphere_contracts.actions.v1.action_intent import PatchOperation, ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    InvalidSchemaError,
    StaleVersionError,
)

GRANT_ID = "commercial:cust1:neurosphere:grant:g1"
OID = "11111111-2222-4333-8444-555555555555"
NAMES = publication_names(GRANT_ID)


def _target() -> TargetRef:
    return TargetRef(canonical_id=GRANT_ID, entity_type="grant")


def publish_request(version: str = VERSION_UNPUBLISHED, **over: Any) -> WriteRequest:
    value: dict[str, Any] = {
        "gateway_id": GATEWAY_ID,
        "api_id": "llm",
        "access": "subscription",
        "principal_kind": "application",
        "principal_object_id": OID,
        "tokens_per_minute": 5000,
    }
    value.update(over)
    return WriteRequest(
        target=_target(),
        target_version=version,
        proposed_diff=ProposedDiff(
            format="json_patch",
            operations=[PatchOperation(op="add", path=PUBLICATION_PATH, value=value)],
        ),
    )


def unpublish_request(names: list[str], version: str = VERSION_PUBLISHED) -> WriteRequest:
    return WriteRequest(
        target=_target(),
        target_version=version,
        proposed_diff=ProposedDiff(
            format="json_patch",
            operations=[
                PatchOperation(op="test", path="/publication/gateway_id", value=GATEWAY_ID),
                PatchOperation(op="test", path=RESOURCES_PATH, value=names),
                PatchOperation(op="remove", path=PUBLICATION_PATH),
            ],
        ),
    )


def make() -> tuple[ApimGatewayConnector, InMemoryApim, InMemoryApplyRecordStore]:
    apim = InMemoryApim(service_etag=SERVICE_ETAG)
    apim.seed("apis/llm", {"displayName": "LLM", "path": "llm"})
    records = InMemoryApplyRecordStore()
    counter = iter(range(1, 100))
    conn = ApimGatewayConnector(
        GATEWAY,
        apim,
        records=records,
        mode=mode_handler(apim),
        translators=[GrantPublicationTranslator()],
        id_factory=lambda: f"apply-{next(counter)}",
    )
    return conn, apim, records


async def reviewed(conn: ApimGatewayConnector, req: WriteRequest) -> WriteRequest:
    result = await conn.dry_run(req)
    return req.model_copy(update={"proposed_diff": result.planned_diff})


def _policy(apim: InMemoryApim, path: str) -> str:
    return str(apim.resources[path][0]["value"])


async def test_subscription_publish_builds_product_fragment_link_subscription() -> None:
    conn, apim, records = make()
    req = await reviewed(conn, publish_request())
    result = await conn.apply(req)
    expected = {
        NAMES.fragment,
        NAMES.product,
        NAMES.product_policy,
        NAMES.link("llm"),
        NAMES.subscription,
        "apis/llm",
    }
    assert set(apim.resources) == expected
    # Dependency order on the wire.
    puts = [c.path for c in apim.writes() if c.method == "PUT"]
    assert puts == [
        NAMES.fragment,
        NAMES.product,
        NAMES.product_policy,
        NAMES.link("llm"),
        NAMES.subscription,
    ]
    fragment = _policy(apim, NAMES.fragment)
    assert "llm-token-limit" in fragment
    assert "llm-emit-token-metric" in fragment
    assert 'tokens-per-minute="5000"' in fragment
    assert "context.Subscription.Id" in fragment
    ET.fromstring(fragment)  # noqa: S314
    product_policy = _policy(apim, NAMES.product_policy)
    assert "validate-azure-ad-token" not in product_policy
    assert NAMES.fragment.split("/", 1)[1] in product_policy
    assert apim.resources[NAMES.product][0]["subscriptionRequired"] is True
    assert apim.resources[NAMES.link("llm")][0]["apiId"] == f"{ARM_ID}/apis/llm"
    record = await records.latest(result.rollback_token or "")
    assert record is not None
    assert {s.name for s in record.steps if s.ownership is StepOwnership.CREATED} == (
        expected - {"apis/llm"}
    )


async def test_publish_never_reads_or_returns_the_subscription_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    conn, apim, _ = make()
    caplog.set_level(logging.DEBUG)
    req = await reviewed(conn, publish_request())
    result = await conn.apply(req)
    verified = await conn.verify(req)
    assert verified.checks
    blob = result.model_dump_json() + verified.model_dump_json() + caplog.text
    assert "pk-generated-secret" not in blob
    assert "sk-generated-secret" not in blob
    assert "listSecrets" not in " ".join(c.path for c in apim.calls)
    assert all(c.method in ("GET", "PUT", "DELETE") for c in apim.calls)
    assert "primaryKey" not in apim.writes()[-1].path


async def test_verify_matches_after_publish_and_reports_drift() -> None:
    conn, apim, _ = make()
    req = await reviewed(conn, publish_request())
    await conn.apply(req)
    assert all(c.matched for c in (await conn.verify(req)).checks)
    del apim.resources[NAMES.product_policy]
    after = await conn.verify(req)
    assert any(not c.matched for c in after.checks)


@pytest.mark.parametrize(
    ("kind", "claim", "match"),
    [("application", "oid", "all"), ("user", "oid", "all"), ("entra_group", "groups", "any")],
)
async def test_entra_publish_validates_the_principal_claim(
    kind: str, claim: str, match: str
) -> None:
    conn, apim, _ = make()
    req = await reviewed(conn, publish_request(access="entra", principal_kind=kind))
    await conn.apply(req)
    assert NAMES.subscription not in apim.resources
    assert apim.resources[NAMES.product][0]["subscriptionRequired"] is False
    xml = _policy(apim, NAMES.product_policy)
    root = ET.fromstring(xml)  # noqa: S314
    token = root.find("./inbound/validate-azure-ad-token")
    assert token is not None
    claim_el = token.find("./required-claims/claim")
    assert claim_el is not None
    assert claim_el.get("name") == claim
    assert claim_el.get("match") == match
    value = claim_el.find("value")
    assert value is not None and value.text == OID
    # Named values are referenced by name only; the include follows the validation.
    assert "{{ns-tenant-id}}" in xml
    inbound_el = root.find("./inbound")
    assert inbound_el is not None
    inbound = [child.tag for child in inbound_el]
    assert inbound == ["base", "validate-azure-ad-token", "include-fragment"]
    # Counter key is the caller oid.
    assert "oid" in _policy(apim, NAMES.fragment)
    assert "Subscription.Id" not in _policy(apim, NAMES.fragment)


async def test_publish_refuses_missing_api_other_gateway_and_no_limit() -> None:
    conn, _, _ = make()
    with pytest.raises(CapabilityUnavailableError) as missing:
        await conn.dry_run(publish_request(api_id="nope"))
    assert missing.value.reason == "target_api_missing"
    with pytest.raises(InvalidSchemaError) as other:
        await conn.dry_run(publish_request(gateway_id="gw-" + "b" * 32))
    assert other.value.reason == "wrong_entity"
    with pytest.raises(InvalidSchemaError) as nolimit:
        await conn.dry_run(publish_request(tokens_per_minute=None))
    assert nolimit.value.reason == "grant_needs_token_limit"
    with pytest.raises(InvalidSchemaError) as junk:
        await conn.dry_run(publish_request(tenant_named_value="x}}<evil/>"))
    assert junk.value.reason == "bad_payload"


async def test_published_grant_is_stale_to_publish_again() -> None:
    conn, _, _ = make()
    req = await reviewed(conn, publish_request())
    await conn.apply(req)
    with pytest.raises(StaleVersionError):
        await conn.dry_run(publish_request())


async def test_unpublish_deletes_only_the_named_owned_resources() -> None:
    conn, apim, _ = make()
    await conn.apply(await reviewed(conn, publish_request()))
    created = [NAMES.subscription, NAMES.link("llm"), NAMES.product_policy, NAMES.product]
    req = await reviewed(conn, unpublish_request(created))
    await conn.apply(req)
    # The fragment was not listed (not recorded created): it stays; the API is untouched.
    assert set(apim.resources) == {"apis/llm", NAMES.fragment}
    deletes = [c.path for c in apim.writes() if c.method == "DELETE"]
    assert deletes == created  # reverse dependency order


async def test_unpublish_refuses_resources_outside_the_grant_namespace() -> None:
    conn, _, _ = make()
    await conn.apply(await reviewed(conn, publish_request()))
    other = publication_names("commercial:cust1:neurosphere:grant:other")
    for bad in (["apis/llm"], [other.product], [NAMES.product, NAMES.product]):
        with pytest.raises(InvalidSchemaError):
            await conn.dry_run(unpublish_request(bad))


async def test_rollback_of_a_publish_deletes_only_created() -> None:
    conn, apim, _ = make()
    # A pre-existing product with the grant name is found, not created, so rollback keeps it.
    apim.seed(NAMES.product, {"displayName": "pre-existing", "state": "published"})
    result = await conn.apply(await reviewed(conn, publish_request(version=VERSION_PUBLISHED)))
    await conn.rollback(result)
    assert set(apim.resources) == {"apis/llm", NAMES.product}
    assert apim.resources[NAMES.product][0]["displayName"] == "pre-existing"


def test_names_are_namespaced_and_collision_safe() -> None:
    a = publication_names("commercial:c:s:grant:a/b")
    b = publication_names("commercial:c:s:grant:a-b")
    assert a.product != b.product
    assert a.product.startswith("products/ns-grant-")
    assert len(a.product.split("/")[1]) <= 80
