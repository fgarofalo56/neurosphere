"""Shared fixtures for the APIM write connector tests (all against ``InMemoryApim``)."""

from __future__ import annotations

from typing import Any

from neurosphere_connector.write import WriteRequest
from neurosphere_connector_apim_gateway import (
    ApimGatewayConnector,
    GatewayRef,
    InMemoryApim,
    InMemoryApplyRecordStore,
    resource_pointer,
)
from neurosphere_connector_apim_gateway.policies import (
    GrantLimits,
    fragment_payload,
    render_api_policy,
    render_grant_fragment,
)
from neurosphere_contracts.actions.v1.action_intent import PatchOperation, ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_core.cloud.profile import CloudName

SUB = "00000000-1111-2222-3333-444444444444"
ARM_ID = (
    f"/subscriptions/{SUB}/resourceGroups/rg-ai/providers/Microsoft.ApiManagement/service/apim-demo"
)
GATEWAY_ID = "gw-" + "a" * 32
GATEWAY = GatewayRef(gateway_id=GATEWAY_ID, cloud=CloudName.COMMERCIAL, arm_resource_id=ARM_ID)
GOV_GATEWAY = GatewayRef(gateway_id=GATEWAY_ID, cloud=CloudName.GOVERNMENT, arm_resource_id=ARM_ID)
SERVICE_ETAG = '"svc-1"'
KV_ID = "https://kv-demo.vault.azure.net/secrets/foundry-key"

Op = tuple[str, str, Any]


def target(cloud: str = "commercial", gateway_id: str = GATEWAY_ID) -> TargetRef:
    return TargetRef(
        canonical_id=f"{cloud}:cust1:apim:apim_gateway:{gateway_id}",
        entity_type="apim_gateway",
    )


def request(
    *ops: Op,
    version: str = SERVICE_ETAG,
    tgt: TargetRef | None = None,
) -> WriteRequest:
    return WriteRequest(
        target=tgt or target(),
        target_version=version,
        proposed_diff=ProposedDiff(
            format="json_patch",
            operations=[PatchOperation(op=o, path=p, value=v) for o, p, v in ops],  # type: ignore[arg-type]
        ),
    )


def upsert(name: str, properties: dict[str, Any]) -> Op:
    return ("add", resource_pointer(name), properties)


def remove(name: str) -> Op:
    return ("remove", resource_pointer(name), None)


GRANT_XML = render_grant_fragment(GrantLimits(counter_key="subscription", tokens_per_minute=5000))

PUBLICATION: dict[str, dict[str, Any]] = {
    "namedValues/foundry-key": {
        "displayName": "foundry-key",
        "secret": True,
        "keyVault": {"secretIdentifier": KV_ID},
    },
    "backends/foundry": {
        "url": "https://foundry-demo.openai.azure.com/openai",
        "protocol": "http",
        "credentials": {"header": {"api-key": ["{{foundry-key}}"]}},
    },
    "policyFragments/ns-grant-g1": fragment_payload(GRANT_XML, description="grant g1"),
    "apis/llm": {
        "displayName": "LLM",
        "path": "llm",
        "protocols": ["https"],
        "subscriptionRequired": True,
    },
    "apis/llm/operations/chat": {
        "displayName": "chat",
        "method": "POST",
        "urlTemplate": "/chat/completions",
    },
    "apis/llm/policies/policy": fragment_payload(
        render_api_policy(["ns-grant-g1"], backend_id="foundry")
    ),
    "products/ns-grant-g1": {
        "displayName": "Grant g1",
        "subscriptionRequired": True,
        "state": "published",
    },
    "products/ns-grant-g1/policies/policy": fragment_payload(render_api_policy(["ns-grant-g1"])),
    "products/ns-grant-g1/apiLinks/llm": {"apiId": f"{ARM_ID}/apis/llm"},
    "subscriptions/ns-grant-g1-team": {
        "displayName": "team",
        "scope": "/products/ns-grant-g1",
        "state": "active",
    },
}

EXPECTED_ORDER = [
    "namedValues/foundry-key",
    "backends/foundry",
    "policyFragments/ns-grant-g1",
    "apis/llm",
    "apis/llm/operations/chat",
    "apis/llm/policies/policy",
    "products/ns-grant-g1",
    "products/ns-grant-g1/policies/policy",
    "products/ns-grant-g1/apiLinks/llm",
    "subscriptions/ns-grant-g1-team",
]


def publication_ops(reverse: bool = True) -> list[Op]:
    """All publication resources; reversed by default to prove ordering is the planner's job."""
    names = list(PUBLICATION)
    if reverse:
        names.reverse()
    return [upsert(n, PUBLICATION[n]) for n in names]


def make(
    apim: InMemoryApim | None = None, records: InMemoryApplyRecordStore | None = None
) -> tuple[ApimGatewayConnector, InMemoryApim, InMemoryApplyRecordStore]:
    apim = apim or InMemoryApim(service_etag=SERVICE_ETAG)
    records = records or InMemoryApplyRecordStore()
    counter = iter(range(1, 1000))
    conn = ApimGatewayConnector(
        GATEWAY, apim, records=records, id_factory=lambda: f"apply-{next(counter)}"
    )
    return conn, apim, records


async def reviewed(conn: ApimGatewayConnector, req: WriteRequest) -> WriteRequest:
    """The request as an approver would confirm it: diff from dry_run (digest bound in)."""
    result = await conn.dry_run(req)
    return req.model_copy(update={"proposed_diff": result.planned_diff})
