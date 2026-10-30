"""MCP server publication through the gateway (PRP-34 item 6), against the in-memory APIM double.

Covers the publish plan order, deny-first staging for change and unpublish (and that a failed
change or removal never restores the enforcement), every refusal, the enforcement policy content
(credential stripping, managed identity, per-grant rate limits, no body access), the PRM
operation on the shared metadata API and the blank-path conflict.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx
import pytest
from apim_write_support import (  # pyright: ignore[reportMissingImports]
    ARM_ID,
    GATEWAY,
    GATEWAY_ID,
    mode_handler,
)
from neurosphere_connector.write import WriteRequest
from neurosphere_connector_apim_gateway import (
    ApimGatewayConnector,
    InMemoryApim,
    InMemoryApplyRecordStore,
    RollbackFailedError,
    StepOwnership,
)
from neurosphere_connector_apim_gateway.arm import map_status
from neurosphere_connector_apim_gateway.mcp import (
    METADATA_API,
    PUBLICATION_PATH,
    TENANT_NAMED_VALUE,
    VERSION_ABSENT,
    VERSION_DENIED,
    VERSION_PUBLISHED,
    HttpApiPathIndex,
    InMemoryApiPathIndex,
    McpServerTranslator,
    resource_names,
)
from neurosphere_connector_apim_gateway.policies.mcp_publication import (
    MCP_TEMPLATE_NAMES,
    McpGrantLimit,
    load_mcp_template,
    render_mcp_api_policy,
    render_mcp_deny_policy,
    render_mcp_prm_policy,
    render_mcp_server_enforcement,
)
from neurosphere_contracts.actions.v1.action_intent import PatchOperation, ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    InvalidSchemaError,
    StaleVersionError,
)

SERVER_ID = "commercial:contoso:neurosphere:mcp_server:finance/ledger-tools"
NAMES = resource_names(SERVER_ID)
AUDIENCE_NV = f"{NAMES.prefix}-audience"
KV = "https://kv-demo.vault.azure.net/secrets/"
OID_A = "11111111-2222-4333-8444-555555555555"
OID_B = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
STRIPPED = ("Authorization", "Ocp-Apim-Subscription-Key", "api-key", "subscription-key")
PUBLISH_ORDER = [
    NAMES.backend,
    NAMES.fragment,
    NAMES.api,
    NAMES.metadata_api,
    NAMES.prm_operation,
    NAMES.api_policy,
    NAMES.metadata_policy,
]
_BODY_READ = re.compile(r"\.Body\b|context\.Request\.Body|context\.Response\.Body")


def _parse(xml: str) -> ET.Element:
    """Parse our own rendered templates (trusted text, no external entities)."""
    return ET.fromstring(xml)  # noqa: S314


def publication(stage: str = "publish", **update: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "stage": stage,
        "gateway_id": GATEWAY_ID,
        "url": "https://ledger-tools.contoso.example/tools/mcp",
        "transport": "streamable_http",
        "auth_kind": "entra",
        "audience": "api://ledger-tools",
        "api_path": "ledger-tools",
        "audience_named_value": AUDIENCE_NV,
        "grants": [{"oid": OID_A, "calls_per_minute": 30}],
    }
    base.update(update)
    return base


def request(pub: dict[str, Any], version: str) -> WriteRequest:
    return WriteRequest(
        target=TargetRef(canonical_id=SERVER_ID, entity_type="mcp_server"),
        target_version=version,
        proposed_diff=ProposedDiff(
            format="json_patch",
            operations=[PatchOperation(op="replace", path=PUBLICATION_PATH, value=pub)],
        ),
    )


def seed_named_values(apim: InMemoryApim) -> None:
    for name in (TENANT_NAMED_VALUE, AUDIENCE_NV):
        apim.seed(
            f"namedValues/{name}",
            {"displayName": name, "secret": True, "keyVault": {"secretIdentifier": KV + name}},
        )


def make(
    apim: InMemoryApim | None = None, *, paths: bool = True
) -> tuple[ApimGatewayConnector, InMemoryApim, InMemoryApplyRecordStore]:
    if apim is None:
        apim = InMemoryApim()
        seed_named_values(apim)
    records = InMemoryApplyRecordStore()
    counter = iter(range(1, 1000))
    translator = McpServerTranslator(paths=InMemoryApiPathIndex(apim) if paths else None)
    conn = ApimGatewayConnector(
        GATEWAY,
        apim,
        records=records,
        mode=mode_handler(apim),
        translators=[translator],
        id_factory=lambda: f"apply-{next(counter)}",
    )
    return conn, apim, records


async def reviewed(conn: ApimGatewayConnector, req: WriteRequest) -> WriteRequest:
    result = await conn.dry_run(req)
    return req.model_copy(update={"proposed_diff": result.planned_diff})


async def run(conn: ApimGatewayConnector, req: WriteRequest) -> Any:
    return await conn.apply(await reviewed(conn, req))


async def published() -> tuple[ApimGatewayConnector, InMemoryApim, InMemoryApplyRecordStore]:
    conn, apim, records = make()
    await run(conn, request(publication(), VERSION_ABSENT))
    return conn, apim, records


async def denied() -> tuple[ApimGatewayConnector, InMemoryApim, InMemoryApplyRecordStore]:
    conn, apim, records = await published()
    await run(conn, request(publication("deny"), VERSION_PUBLISHED))
    return conn, apim, records


def policy_xml(apim: InMemoryApim, name: str) -> str:
    return str(apim.resources[name][0]["value"])


# -- publish ------------------------------------------------------------------------------


async def test_publish_plan_writes_in_dependency_order_and_owns_what_it_creates() -> None:
    conn, apim, records = make()
    req = request(publication(), VERSION_ABSENT)
    plan = await conn.plan(req)
    assert [s.name for s in plan.steps] == PUBLISH_ORDER
    assert all(s.expected == "create" for s in plan.steps)

    result = await conn.apply(await reviewed(conn, req))
    assert [c.path for c in apim.writes()] == PUBLISH_ORDER
    assert all(c.method == "PUT" and c.if_match is None for c in apim.writes())
    record = await records.latest(result.rollback_token or "")
    assert record is not None and record.status == "succeeded"
    assert {s.ownership for s in record.steps} == {StepOwnership.CREATED}
    assert result.version_after == VERSION_PUBLISHED
    verify = await conn.verify(req)
    assert verify.matched is True


async def test_publish_backend_is_the_url_without_mcp_and_the_api_is_mcp_passthrough() -> None:
    _, apim, _ = await published()
    backend = apim.resources[NAMES.backend][0]
    assert backend["url"] == "https://ledger-tools.contoso.example/tools"
    assert "credentials" not in backend
    api = apim.resources[NAMES.api][0]
    assert api["type"] == "mcp"
    assert api["mcpProperties"] == {"transportType": "streamable"}
    assert api["subscriptionRequired"] is False
    # Routing only through the API policy: the API alone forwards nothing.
    assert "serviceUrl" not in api and "backendId" not in api
    root = _parse(policy_xml(apim, NAMES.api_policy))
    inbound = root.find("inbound")
    assert inbound is not None
    include = inbound.find("include-fragment")
    backend_el = inbound.find("set-backend-service")
    assert include is not None and include.get("fragment-id") == NAMES.fragment_id
    assert backend_el is not None and backend_el.get("backend-id") == NAMES.prefix
    forward = root.find("backend/forward-request")
    assert forward is not None
    assert forward.get("buffer-request-body") == "false"
    assert forward.get("buffer-response") == "false"


async def test_publish_adds_the_prm_operation_on_the_shared_blank_path_metadata_api() -> None:
    _, apim, _ = await published()
    meta = apim.resources[NAMES.metadata_api][0]
    assert meta["path"] == "" and meta["subscriptionRequired"] is False
    op = apim.resources[NAMES.prm_operation][0]
    assert op["method"] == "GET"
    assert op["urlTemplate"] == "/.well-known/oauth-protected-resource/ledger-tools/mcp"
    prm = policy_xml(apim, NAMES.metadata_policy)
    _parse(prm)
    assert "https://login.microsoftonline.com/{{ns-mcp-tenant-id}}/v2.0" in prm
    assert "context.Request.OriginalUrl" in prm


async def test_a_second_publication_reuses_the_shared_metadata_api_unchanged() -> None:
    conn, apim, _ = await published()
    other_id = "commercial:contoso:neurosphere:mcp_server:finance/other"
    other = resource_names(other_id)
    apim.seed(
        f"namedValues/{other.prefix}-audience",
        {"displayName": "x", "secret": True, "keyVault": {"secretIdentifier": KV + "x"}},
    )
    req = WriteRequest(
        target=TargetRef(canonical_id=other_id, entity_type="mcp_server"),
        target_version=VERSION_ABSENT,
        proposed_diff=request(
            publication(api_path="other", audience_named_value=f"{other.prefix}-audience"),
            VERSION_ABSENT,
        ).proposed_diff,
    )
    plan = await conn.plan(req)
    shared = {s.name: s for s in plan.steps if s.name in other.shared}
    assert {s.expected for s in shared.values()} == {"found"}
    assert not any(s.changes for s in shared.values())


async def test_publish_refuses_to_adopt_an_existing_resource() -> None:
    apim = InMemoryApim()
    seed_named_values(apim)
    apim.seed(NAMES.backend, {"url": "https://elsewhere.example", "protocol": "http"})
    conn, _, _ = make(apim)
    with pytest.raises(CapabilityUnavailableError) as caught:
        await conn.dry_run(request(publication(), VERSION_ABSENT))
    assert caught.value.reason == "mcp_resource_exists"


async def test_publish_refuses_when_another_api_owns_the_blank_path() -> None:
    apim = InMemoryApim()
    seed_named_values(apim)
    apim.seed("apis/root-api", {"displayName": "root", "path": "", "protocols": ["https"]})
    conn, _, _ = make(apim)
    with pytest.raises(CapabilityUnavailableError) as caught:
        await conn.dry_run(request(publication(), VERSION_ABSENT))
    assert caught.value.reason == "mcp_metadata_path_taken"
    assert apim.writes() == []


async def test_publish_refuses_when_another_api_owns_the_path() -> None:
    apim = InMemoryApim()
    seed_named_values(apim)
    apim.seed("apis/legacy", {"displayName": "legacy", "path": "ledger-tools"})
    conn, _, _ = make(apim)
    with pytest.raises(CapabilityUnavailableError) as caught:
        await conn.dry_run(request(publication(), VERSION_ABSENT))
    assert caught.value.reason == "mcp_api_path_taken"


async def test_publish_without_a_path_index_fails_closed() -> None:
    conn, apim, _ = make(paths=False)
    with pytest.raises(CapabilityUnavailableError) as caught:
        await conn.dry_run(request(publication(), VERSION_ABSENT))
    assert caught.value.reason == "mcp_api_paths_unreadable"
    assert apim.writes() == []


async def test_publish_refuses_a_missing_named_value() -> None:
    apim = InMemoryApim()
    conn, _, _ = make(apim)
    with pytest.raises(CapabilityUnavailableError) as caught:
        await conn.dry_run(request(publication(), VERSION_ABSENT))
    assert caught.value.reason == "mcp_named_value_missing"


@pytest.mark.parametrize(
    ("update", "error", "reason"),
    [
        ({"transport": "sse"}, CapabilityUnavailableError, "mcp_sse_unsupported"),
        ({"auth_kind": "api_key"}, CapabilityUnavailableError, "mcp_api_key_upstream"),
        ({"audience": None}, InvalidSchemaError, "mcp_audience_missing"),
        ({"audience": ""}, InvalidSchemaError, "mcp_audience_missing"),
        (
            {"url": "https://ledger-tools.contoso.example/mcp?code=1"},
            InvalidSchemaError,
            "mcp_url_query",
        ),
        (
            {"url": "https://ledger-tools.contoso.example/sse"},
            InvalidSchemaError,
            "mcp_url_not_mcp",
        ),
        ({"url": "http://ledger-tools.contoso.example/mcp"}, InvalidSchemaError, "mcp_url_invalid"),
        ({"api_path": None}, InvalidSchemaError, "mcp_publication_incomplete"),
        ({"gateway_id": "gw-" + "b" * 32}, InvalidSchemaError, "wrong_entity"),
    ],
)
async def test_publish_refusals(
    update: dict[str, Any], error: type[Exception], reason: str
) -> None:
    conn, apim, _ = make()
    req = request(publication(**update), VERSION_ABSENT)
    with pytest.raises(error) as caught:
        await conn.dry_run(req)
    assert getattr(caught.value, "reason", None) == reason
    with pytest.raises(error):
        await conn.apply(req)
    assert apim.writes() == []


async def test_a_diff_that_is_not_one_publication_is_refused() -> None:
    conn, _, _ = make()
    req = request(publication(), VERSION_ABSENT)
    stray = PatchOperation(op="replace", path="/resources/backends~1x", value={"url": "x"})
    extra = [*req.proposed_diff.operations, stray]
    bad = req.model_copy(
        update={"proposed_diff": ProposedDiff(format="json_patch", operations=extra)}
    )
    with pytest.raises(InvalidSchemaError) as caught:
        await conn.dry_run(bad)
    assert caught.value.reason == "unsupported_operation"
    dup = publication(grants=[{"oid": OID_A}, {"oid": OID_A, "calls_per_minute": 2}])
    with pytest.raises(InvalidSchemaError) as caught:
        await conn.dry_run(request(dup, VERSION_ABSENT))
    assert caught.value.reason == "bad_payload"


# -- enforcement policy -------------------------------------------------------------------


async def test_enforcement_validates_entra_strips_credentials_and_limits_per_grant() -> None:
    pub = publication(grants=[{"oid": OID_A, "calls_per_minute": 30}, {"oid": OID_B}])
    conn, apim, _ = make()
    await run(conn, request(pub, VERSION_ABSENT))
    xml = policy_xml(apim, NAMES.fragment)
    root = _parse(xml)
    validate = root.find("validate-azure-ad-token")
    assert validate is not None
    assert validate.get("tenant-id") == "{{ns-mcp-tenant-id}}"
    audience = validate.find("audiences/audience")
    assert audience is not None and audience.text == "{{" + AUDIENCE_NV + "}}"
    deleted = [
        h.get("name") for h in root.findall("set-header") if h.get("exists-action") == "delete"
    ]
    assert deleted == list(STRIPPED)
    assert root.find("authentication-managed-identity") is None
    whens = root.findall("choose/when")
    assert len(whens) == 2
    limits = root.findall("choose/when/rate-limit-by-key")
    assert len(limits) == 1
    assert limits[0].get("calls") == "30" and limits[0].get("renewal-period") == "60"
    assert limits[0].get("counter-key") == f"{NAMES.prefix}:{OID_A}"
    assert OID_A in str(whens[0].get("condition")) and OID_B in str(whens[1].get("condition"))
    forbidden = root.find("choose/otherwise/return-response/set-status")
    assert forbidden is not None and forbidden.get("code") == "403"
    # Named values are referenced, never inlined: the audience value is not in the policy.
    assert "api://ledger-tools" not in xml


async def test_managed_identity_is_attached_after_the_credential_strip() -> None:
    conn, apim, _ = make()
    await run(conn, request(publication(auth_kind="managed_identity"), VERSION_ABSENT))
    root = _parse(policy_xml(apim, NAMES.fragment))
    children = [c.tag for c in root]
    mi = root.find("authentication-managed-identity")
    assert mi is not None and mi.get("resource") == "{{" + AUDIENCE_NV + "}}"
    strip_last = max(i for i, c in enumerate(root) if c.tag == "set-header")
    assert children.index("authentication-managed-identity") > strip_last


def test_no_grant_means_no_access() -> None:
    xml = render_mcp_server_enforcement(
        tenant_named_value=TENANT_NAMED_VALUE,
        audience_named_value=AUDIENCE_NV,
        counter_prefix=NAMES.prefix,
        grants=[],
        managed_identity=False,
    )
    root = _parse(xml)
    assert root.find("choose") is None
    status = root.find("return-response/set-status")
    assert status is not None and status.get("code") == "403"


def _rendered() -> list[str]:
    return [
        render_mcp_server_enforcement(
            tenant_named_value=TENANT_NAMED_VALUE,
            audience_named_value=AUDIENCE_NV,
            counter_prefix=NAMES.prefix,
            grants=grants,
            managed_identity=mi,
        )
        for grants in ([], [McpGrantLimit(OID_A, 5), McpGrantLimit(OID_B)])
        for mi in (False, True)
    ] + [
        render_mcp_api_policy(fragment_id=NAMES.fragment_id, backend_id=NAMES.prefix),
        render_mcp_deny_policy(),
        render_mcp_prm_policy(login_host="login.microsoftonline.com", tenant_named_value="t"),
    ]


def test_every_mcp_template_renders_parses_and_never_reads_a_body() -> None:
    for name in MCP_TEMPLATE_NAMES:
        assert load_mcp_template(name)
    for xml in _rendered():
        _parse(xml)
        assert "[[" not in xml
        assert not _BODY_READ.search(xml), xml


def test_renderers_refuse_bad_input() -> None:
    with pytest.raises(ValueError, match="GUID"):
        McpGrantLimit("not-a-guid")
    with pytest.raises(ValueError, match="positive"):
        McpGrantLimit(OID_A, 0)
    with pytest.raises(ValueError, match="principal"):
        render_mcp_server_enforcement(
            tenant_named_value="t",
            audience_named_value="a",
            counter_prefix="p",
            grants=[McpGrantLimit(OID_A), McpGrantLimit(OID_A)],
            managed_identity=False,
        )
    with pytest.raises(ValueError, match="login host"):
        render_mcp_prm_policy(login_host="evil.example/x", tenant_named_value="t")
    with pytest.raises(ValueError, match="resource id"):
        render_mcp_api_policy(fragment_id="bad id", backend_id="b")
    with pytest.raises(ValueError, match="unknown"):
        load_mcp_template("../deny.xml")


# -- deny first, change and unpublish -----------------------------------------------------


async def test_change_and_remove_need_the_deny_stage_first() -> None:
    conn, apim, _ = await published()
    before = len(apim.writes())
    for stage in ("change", "remove"):
        with pytest.raises(InvalidSchemaError) as caught:
            await conn.dry_run(request(publication(stage), VERSION_PUBLISHED))
        assert caught.value.reason == "mcp_deny_first_required"
    # Drafted as if denied while the gateway is still published: stale, nothing written.
    with pytest.raises(StaleVersionError):
        await conn.dry_run(request(publication("change"), VERSION_DENIED))
    assert len(apim.writes()) == before


async def test_deny_stage_writes_only_the_deny_policy() -> None:
    conn, apim, _ = await published()
    before = len(apim.writes())
    req = request(publication("deny"), VERSION_PUBLISHED)
    plan = await conn.plan(req)
    assert [(s.name, s.expected) for s in plan.steps] == [(NAMES.api_policy, "found")]
    result = await conn.apply(await reviewed(conn, req))
    writes = apim.writes()[before:]
    assert [(c.method, c.path) for c in writes] == [("PUT", NAMES.api_policy)]
    assert writes[0].if_match is not None
    status = _parse(policy_xml(apim, NAMES.api_policy)).find("inbound/return-response/set-status")
    assert status is not None and status.get("code") == "503"
    assert result.version_after == VERSION_DENIED


async def test_change_after_deny_updates_the_backend_and_restores_enforcement() -> None:
    conn, apim, _ = await denied()
    new_url = "https://ledger-v2.contoso.example/mcp"
    req = request(publication("change", url=new_url), VERSION_DENIED)
    result = await conn.apply(await reviewed(conn, req))
    assert apim.resources[NAMES.backend][0]["url"] == "https://ledger-v2.contoso.example"
    assert _parse(policy_xml(apim, NAMES.api_policy)).find("inbound/include-fragment") is not None
    assert result.version_after == VERSION_PUBLISHED


async def test_failed_change_keeps_the_deny_and_reports_the_failure() -> None:
    conn, apim, _ = await denied()
    deny_xml = policy_xml(apim, NAMES.api_policy)
    # The shared metadata policy drifted, so the change rewrites it AFTER the per-server API
    # policy (same rank, sorted by name); that write fails.
    apim.seed(NAMES.metadata_policy, {"format": "rawxml", "value": "<policies />"})
    apim.fail("PUT", NAMES.metadata_policy, map_status(503))
    req = await reviewed(
        conn, request(publication("change", url="https://v2.contoso.example/mcp"), VERSION_DENIED)
    )
    with pytest.raises(Exception) as caught:
        await conn.apply(req)
    assert getattr(caught.value, "code", None) == "dependency_transient"
    # The stage had restored enforcement; the reversal put the API policy back to its prior
    # document, which is the deny. The backend is back to the old URL. Nothing re-opened.
    assert policy_xml(apim, NAMES.api_policy) == deny_xml
    assert apim.resources[NAMES.backend][0]["url"] == "https://ledger-tools.contoso.example/tools"


async def test_unpublish_removes_per_server_resources_after_the_deny() -> None:
    conn, apim, records = await denied()
    before = len(apim.writes())
    req = request(publication("remove"), VERSION_DENIED)
    plan = await conn.plan(req)
    assert [s.name for s in plan.steps] == [
        NAMES.api_policy,
        NAMES.prm_operation,
        NAMES.api,
        NAMES.fragment,
        NAMES.backend,
    ]
    assert {s.operation for s in plan.steps} == {"delete"}
    result = await conn.apply(await reviewed(conn, req))
    assert all(c.method == "DELETE" for c in apim.writes()[before:])
    for name in NAMES.per_server:
        assert name not in apim.resources
    # Shared metadata API and its policy stay.
    for name in NAMES.shared:
        assert name in apim.resources
    assert result.version_after == VERSION_ABSENT
    assert (await conn.verify(req)).matched is True
    record = await records.latest(result.rollback_token or "")
    assert record is not None and record.status == "succeeded"


async def test_failed_unpublish_never_restores_enforcement() -> None:
    conn, apim, _ = await denied()
    deny_xml = policy_xml(apim, NAMES.api_policy)
    apim.fail("DELETE", NAMES.fragment, map_status(503))
    req = await reviewed(conn, request(publication("remove"), VERSION_DENIED))
    with pytest.raises(Exception) as caught:
        await conn.apply(req)
    assert getattr(caught.value, "code", None) == "dependency_transient"
    # Everything the stage removed is back, and the API policy is the deny again (it is
    # restored last, after its API): the server stays closed and the failure is reported.
    assert NAMES.api in apim.resources
    assert policy_xml(apim, NAMES.api_policy) == deny_xml
    assert NAMES.backend in apim.resources


async def test_failed_unpublish_reversal_reports_orphans() -> None:
    conn, apim, _ = await denied()
    apim.fail("DELETE", NAMES.fragment, map_status(503))
    apim.fail("PUT", NAMES.api, map_status(503))
    req = await reviewed(conn, request(publication("remove"), VERSION_DENIED))
    with pytest.raises(RollbackFailedError) as caught:
        await conn.apply(req)
    assert caught.value.reason == "rollback_failed"
    assert NAMES.api in caught.value.orphans
    # Nothing restored an enforcement policy: the only API-policy writes are deny documents.
    puts = [c for c in apim.writes() if c.method == "PUT" and c.path == NAMES.api_policy]
    assert len(puts) == 3  # publish (enforcement), deny stage, reversal of the removal (deny)


async def test_rollback_of_a_publish_deletes_only_what_it_created() -> None:
    apim = InMemoryApim()
    seed_named_values(apim)
    # The shared metadata API already exists (another publication created it).
    conn, _, _ = make(apim)
    other_policy = render_mcp_prm_policy(
        login_host="login.microsoftonline.com", tenant_named_value=TENANT_NAMED_VALUE
    )
    apim.seed(
        NAMES.metadata_api,
        {
            "displayName": "NeuroSphere MCP metadata",
            "path": "",
            "protocols": ["https"],
            "subscriptionRequired": False,
        },
    )
    apim.seed(NAMES.metadata_policy, {"format": "rawxml", "value": other_policy})
    result = await run(conn, request(publication(), VERSION_ABSENT))
    rolled = await conn.rollback(result)
    assert rolled.status == "rolled_back"
    for name in NAMES.per_server:
        assert name not in apim.resources
    # Found (shared) resources are never deleted by a rollback.
    assert NAMES.metadata_api == f"apis/{METADATA_API}"
    assert NAMES.metadata_api in apim.resources and NAMES.metadata_policy in apim.resources


async def test_http_api_path_index_lists_names_and_paths_on_the_same_host() -> None:
    pages = {
        "/apis": {
            "value": [
                {"name": "a", "properties": {"path": "x"}},
                {"name": "b", "properties": {}},
            ],
            "nextLink": f"https://management.azure.com{ARM_ID}/apis?page=2",
        },
        "/apis?page=2": {"value": [{"name": "c", "properties": {"path": ""}}]},
    }

    def handler(req: httpx.Request) -> httpx.Response:
        key = "/apis?page=2" if req.url.params.get("page") == "2" else "/apis"
        return httpx.Response(200, json=pages[key])

    client = httpx.AsyncClient(
        base_url="https://management.azure.com", transport=httpx.MockTransport(handler)
    )
    index = HttpApiPathIndex(client, ARM_ID)
    assert await index.api_paths() == {"a": "x", "b": "", "c": ""}

    def evil(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": [], "nextLink": "https://evil.example/apis"})

    bad = httpx.AsyncClient(
        base_url="https://management.azure.com", transport=httpx.MockTransport(evil)
    )
    with pytest.raises(Exception, match="paging"):
        await HttpApiPathIndex(bad, ARM_ID).api_paths()
