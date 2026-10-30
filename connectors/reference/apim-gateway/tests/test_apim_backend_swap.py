"""``model_deployment_swap`` on an ``apim_backend`` target (PRP-34 item 3), against InMemoryApim."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from apim_write_support import (  # pyright: ignore[reportMissingImports]
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
)
from neurosphere_connector_apim_gateway.arm import map_status
from neurosphere_connector_apim_gateway.swap import (
    BACKEND_ENTITY_TYPE,
    BackendSwapTranslator,
    backend_swap_diff,
    backend_target,
    parse_backend_swap,
    pool_weights,
)
from neurosphere_contracts.actions.v1.action_intent import PatchOperation, ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    InvalidSchemaError,
    StaleVersionError,
)
from neurosphere_core.gateway.mode import GATEWAY_OBSERVE_MODE

OLD_URL = "https://foundry-old.openai.azure.com/openai"
NEW_URL = "https://foundry-new.openai.azure.com/openai"
SINGLE: dict[str, Any] = {
    "type": "Single",
    "url": OLD_URL,
    "protocol": "http",
    "credentials": {"header": {"api-key": ["{{foundry-key}}"]}},
    "circuitBreaker": {"rules": [{"name": "trip", "tripDuration": "PT1M"}]},
}
POOL: dict[str, Any] = {
    "type": "Pool",
    "description": "chat pool",
    "pool": {
        "services": [
            {"id": "/backends/gpt4o-east", "weight": 100, "priority": 1},
            {"id": "/backends/gpt41-east", "weight": 0, "priority": 1},
        ]
    },
}


def _connector(
    apim: InMemoryApim, *, mode: str = "manage", canary_percent: int | None = 10
) -> tuple[ApimGatewayConnector, InMemoryApplyRecordStore]:
    records = InMemoryApplyRecordStore()
    counter = iter(range(1, 1000))
    conn = ApimGatewayConnector(
        GATEWAY,
        apim,
        records=records,
        mode=mode_handler(apim, mode=mode),  # type: ignore[arg-type]
        translators=[BackendSwapTranslator(canary_percent=canary_percent)],
        id_factory=lambda: f"apply-{next(counter)}",
    )
    return conn, records


def _seeded(name: str, doc: dict[str, Any]) -> tuple[InMemoryApim, str]:
    apim = InMemoryApim(service_etag=SERVICE_ETAG)
    etag = apim.seed(f"backends/{name}", doc)
    return apim, etag


def _request(name: str, etag: str, diff: ProposedDiff) -> WriteRequest:
    return WriteRequest(
        target=backend_target("commercial", "cust1", name),
        target_version=etag,
        proposed_diff=diff,
    )


async def _reviewed(conn: ApimGatewayConnector, req: WriteRequest) -> WriteRequest:
    dry = await conn.dry_run(req)
    return req.model_copy(update={"proposed_diff": dry.planned_diff})


# -- single backend: atomic URL swap ---------------------------------------------------------------


async def test_single_backend_swaps_the_url_and_keeps_everything_else() -> None:
    apim, etag = _seeded("foundry", SINGLE)
    conn, records = _connector(apim)
    req = _request("foundry", etag, backend_swap_diff(SINGLE, url=NEW_URL))
    dry = await conn.dry_run(req)
    assert dry.would_change is True
    assert apim.writes() == []  # dry run reads only
    reviewed = await _reviewed(conn, req)
    applied = await conn.apply(reviewed)
    assert applied.version_before == etag
    assert applied.version_after == apim.etag_of("backends/foundry") != etag
    stored = apim.snapshot()["backends/foundry"]
    assert stored == {**SINGLE, "url": NEW_URL}
    # One If-Match write on the backend; the prior document is captured for rollback.
    assert [(c.method, c.path, c.if_match) for c in apim.writes()] == [
        ("PUT", "backends/foundry", etag)
    ]
    record = await records.latest(applied.rollback_token or "")
    assert record is not None and record.status == "succeeded"
    assert record.steps[0].prior == SINGLE
    verified = await conn.verify(reviewed)
    assert verified.matched
    assert verified.observed_version == applied.version_after


async def test_rollback_restores_the_captured_prior_document() -> None:
    apim, etag = _seeded("foundry", SINGLE)
    conn, records = _connector(apim)
    req = await _reviewed(conn, _request("foundry", etag, backend_swap_diff(SINGLE, url=NEW_URL)))
    applied = await conn.apply(req)
    rolled = await conn.rollback(applied)
    assert rolled.status == "rolled_back"
    assert apim.snapshot()["backends/foundry"] == SINGLE
    statuses = [r.status for r in records.history(applied.rollback_token or "")]
    # The reverse marks the record busy first (the mode switch sees it running).
    assert statuses[-2:] == ["applying", "rolled_back"]
    assert (await conn.rollback(applied)).status == "not_needed"
    assert not (await conn.verify(req)).matched


async def test_verify_reports_a_mismatch_when_the_backend_drifted() -> None:
    apim, etag = _seeded("foundry", SINGLE)
    conn, _ = _connector(apim)
    req = await _reviewed(conn, _request("foundry", etag, backend_swap_diff(SINGLE, url=NEW_URL)))
    await conn.apply(req)
    apim.seed("backends/foundry", {**SINGLE, "url": "https://someone-else.example.com/openai"})
    verified = await conn.verify(req)
    assert not verified.matched
    assert verified.observed_state == {
        "resources": {"backends/foundry": {"present": True, "matched": False}}
    }
    assert "url" not in repr(verified.observed_state)  # booleans only, never the document


async def test_verify_before_apply_does_not_match() -> None:
    apim, etag = _seeded("foundry", SINGLE)
    conn, _ = _connector(apim)
    req = _request("foundry", etag, backend_swap_diff(SINGLE, url=NEW_URL))
    assert not (await conn.verify(req)).matched


# -- pool: weight shift with a canary-sized first step ---------------------------------------------


async def test_pool_shifts_weights_within_the_canary_share() -> None:
    apim, etag = _seeded("chat-pool", POOL)
    conn, _ = _connector(apim)
    diff = backend_swap_diff(POOL, weights={"gpt4o-east": 90, "gpt41-east": 10})
    req = await _reviewed(conn, _request("chat-pool", etag, diff))
    swap = parse_backend_swap(GATEWAY, req)
    assert swap.kind == "pool"
    assert [(s.member, s.weight_before, s.weight_after) for s in swap.raised] == [
        ("gpt41-east", 0, 10)
    ]
    await conn.apply(req)
    stored = apim.snapshot()["backends/chat-pool"]
    assert pool_weights(stored) == {"gpt4o-east": 90, "gpt41-east": 10}
    assert stored["description"] == "chat pool"
    assert stored["pool"]["services"][1]["priority"] == 1
    assert (await conn.verify(req)).matched


@pytest.mark.parametrize(
    "weights",
    [
        {"gpt4o-east": 0, "gpt41-east": 100},  # full promotion in one step
        {"gpt41-east": 50},  # 50 / 150 = 33 percent
    ],
)
async def test_pool_refuses_more_than_the_canary_share_first(weights: dict[str, int]) -> None:
    apim, etag = _seeded("chat-pool", POOL)
    conn, _ = _connector(apim)
    with pytest.raises(InvalidSchemaError) as info:
        await conn.dry_run(_request("chat-pool", etag, backend_swap_diff(POOL, weights=weights)))
    assert info.value.reason == "canary_weight_exceeded"
    assert apim.writes() == []


async def test_lowering_the_other_members_is_a_shift_too() -> None:
    base = copy.deepcopy(POOL)
    base["pool"]["services"][1]["weight"] = 5  # about 5 percent today
    apim, etag = _seeded("chat-pool", base)
    conn, _ = _connector(apim)
    with pytest.raises(InvalidSchemaError) as info:
        await conn.dry_run(
            _request("chat-pool", etag, backend_swap_diff(base, weights={"gpt4o-east": 1}))
        )
    assert info.value.reason == "canary_weight_exceeded"


async def test_a_member_past_the_canary_share_may_be_promoted() -> None:
    base = copy.deepcopy(POOL)
    base["pool"]["services"][0]["weight"] = 90
    base["pool"]["services"][1]["weight"] = 10
    apim, etag = _seeded("chat-pool", base)
    conn, _ = _connector(apim)
    diff = backend_swap_diff(base, weights={"gpt4o-east": 0, "gpt41-east": 100})
    await conn.apply(await _reviewed(conn, _request("chat-pool", etag, diff)))
    assert pool_weights(apim.snapshot()["backends/chat-pool"]) == {
        "gpt4o-east": 0,
        "gpt41-east": 100,
    }


async def test_canary_limit_can_be_disabled() -> None:
    apim, etag = _seeded("chat-pool", POOL)
    conn, _ = _connector(apim, canary_percent=None)
    diff = backend_swap_diff(POOL, weights={"gpt4o-east": 0, "gpt41-east": 100})
    await conn.apply(await _reviewed(conn, _request("chat-pool", etag, diff)))
    assert pool_weights(apim.snapshot()["backends/chat-pool"])["gpt41-east"] == 100


async def test_pool_rollback_restores_prior_weights() -> None:
    apim, etag = _seeded("chat-pool", POOL)
    conn, _ = _connector(apim)
    diff = backend_swap_diff(POOL, weights={"gpt4o-east": 90, "gpt41-east": 10})
    applied = await conn.apply(await _reviewed(conn, _request("chat-pool", etag, diff)))
    await conn.rollback(applied)
    assert apim.snapshot()["backends/chat-pool"] == POOL


# -- binding and refusals --------------------------------------------------------------------------


async def test_target_version_is_the_backend_etag() -> None:
    apim, etag = _seeded("foundry", SINGLE)
    conn, _ = _connector(apim)
    stale = _request("foundry", '"etag-old"', backend_swap_diff(SINGLE, url=NEW_URL))
    with pytest.raises(StaleVersionError):
        await conn.dry_run(stale)
    req = await _reviewed(conn, _request("foundry", etag, backend_swap_diff(SINGLE, url=NEW_URL)))
    apim.seed("backends/foundry", SINGLE)  # someone re-saved it: new ETag
    with pytest.raises(StaleVersionError):
        await conn.apply(req)
    assert apim.writes() == []


async def test_a_base_that_differs_from_the_live_document_is_refused() -> None:
    apim, etag = _seeded("foundry", SINGLE)
    conn, _ = _connector(apim)
    forged = {k: v for k, v in SINGLE.items() if k != "credentials"}  # would drop credentials
    with pytest.raises(StaleVersionError) as info:
        await conn.dry_run(_request("foundry", etag, backend_swap_diff(forged, url=NEW_URL)))
    assert info.value.reason == "backend_base_mismatch"
    smuggled = {**SINGLE, "protocol": "soap"}
    with pytest.raises(StaleVersionError):
        await conn.dry_run(_request("foundry", etag, backend_swap_diff(smuggled, url=NEW_URL)))
    assert apim.writes() == []


async def test_a_412_on_the_write_is_stale_and_nothing_changes() -> None:
    apim, etag = _seeded("foundry", SINGLE)
    conn, _ = _connector(apim)
    req = await _reviewed(conn, _request("foundry", etag, backend_swap_diff(SINGLE, url=NEW_URL)))
    apim.fail("PUT", "backends/foundry", map_status(412))
    with pytest.raises(StaleVersionError):
        await conn.apply(req)
    assert apim.snapshot()["backends/foundry"] == SINGLE


def _ops(*ops: tuple[str, str, Any]) -> ProposedDiff:
    return ProposedDiff(
        format="json_patch",
        operations=[PatchOperation(op=o, path=p, value=v) for o, p, v in ops],  # type: ignore[arg-type]
    )


_BASE_S = ("test", "/backend", SINGLE)
_BASE_P = ("test", "/backend", POOL)
_W = "/pool/services/{}/weight"


@pytest.mark.parametrize(
    ("diff", "reason"),
    [
        (_ops(("replace", "/url", NEW_URL)), "bad_backend_swap"),  # no base
        (_ops(_BASE_S), "empty_plan"),
        (_ops(_BASE_S, ("replace", "/protocol", "soap")), "unsupported_operation"),
        (_ops(_BASE_S, ("add", "/url", NEW_URL)), "unsupported_operation"),
        (_ops(_BASE_S, ("replace", "/url", "http://x.example")), "backend_url_invalid"),
        (_ops(_BASE_P, ("replace", _W.format(7), 1)), "bad_backend_swap"),
        (_ops(_BASE_P, ("replace", _W.format(0), 5000)), "bad_backend_swap"),
        (_ops(_BASE_P, ("replace", "/url", NEW_URL)), "unsupported_operation"),
    ],
)
async def test_malformed_swaps_are_refused(diff: ProposedDiff, reason: str) -> None:
    apim, etag = _seeded("foundry", SINGLE)
    conn, _ = _connector(apim)
    with pytest.raises(InvalidSchemaError) as info:
        await conn.dry_run(_request("foundry", etag, diff))
    assert info.value.reason == reason
    assert apim.writes() == []


@pytest.mark.parametrize(
    ("canonical_id", "reason"),
    [
        ("government:cust1:apim:apim_backend:foundry", "cloud_mismatch"),
        (f"commercial:cust1:apim:apim_backend:gw-{'b' * 32}/foundry", "wrong_entity"),
    ],
)
async def test_targets_on_another_cloud_or_gateway_are_refused(
    canonical_id: str, reason: str
) -> None:
    apim, etag = _seeded("foundry", SINGLE)
    conn, _ = _connector(apim)
    req = WriteRequest(
        target=TargetRef(canonical_id=canonical_id, entity_type=BACKEND_ENTITY_TYPE),
        target_version=etag,
        proposed_diff=backend_swap_diff(SINGLE, url=NEW_URL),
    )
    with pytest.raises(InvalidSchemaError) as info:
        await conn.dry_run(req)
    assert info.value.reason == reason


async def test_a_gateway_qualified_target_is_accepted() -> None:
    apim, etag = _seeded("foundry", SINGLE)
    conn, _ = _connector(apim)
    req = WriteRequest(
        target=backend_target("commercial", "cust1", f"{GATEWAY_ID}/foundry"),
        target_version=etag,
        proposed_diff=backend_swap_diff(SINGLE, url=NEW_URL),
    )
    await conn.apply(await _reviewed(conn, req))
    assert apim.snapshot()["backends/foundry"]["url"] == NEW_URL


async def test_a_missing_backend_is_not_found() -> None:
    apim = InMemoryApim(service_etag=SERVICE_ETAG)
    conn, _ = _connector(apim)
    with pytest.raises(InvalidSchemaError) as info:
        await conn.dry_run(_request("foundry", '"e"', backend_swap_diff(SINGLE, url=NEW_URL)))
    assert info.value.reason == "target_not_found"


async def test_literal_backend_credentials_are_refused() -> None:
    literal = {**SINGLE, "credentials": {"header": {"api-key": ["not-a-reference"]}}}
    apim, etag = _seeded("foundry", literal)
    conn, _ = _connector(apim)
    with pytest.raises(InvalidSchemaError) as info:
        await conn.dry_run(_request("foundry", etag, backend_swap_diff(literal, url=NEW_URL)))
    assert info.value.reason == "literal_credential"


# -- observe mode: advisory, nothing changes anywhere ---------------------------------------------


async def test_observe_mode_refuses_and_touches_nothing() -> None:
    apim, etag = _seeded("foundry", SINGLE)
    conn, records = _connector(apim, mode="observe")
    req = _request("foundry", etag, backend_swap_diff(SINGLE, url=NEW_URL))
    for call in (conn.dry_run, conn.apply):
        with pytest.raises(CapabilityUnavailableError) as info:
            await call(req)
        assert info.value.reason == GATEWAY_OBSERVE_MODE
    assert apim.calls == []  # not even a read of the gateway
    assert apim.snapshot()["backends/foundry"] == SINGLE
    assert records.history("apply-1") == ()


# -- drafting helper -------------------------------------------------------------------------------


def test_drafting_helper_shapes() -> None:
    diff = backend_swap_diff(SINGLE, url=NEW_URL)
    assert [(o.op, o.path) for o in diff.operations] == [("test", "/backend"), ("replace", "/url")]
    pool = backend_swap_diff(POOL, weights={"gpt41-east": 10})
    assert [o.path for o in pool.operations] == ["/backend", "/pool/services/1/weight"]
    with pytest.raises(ValueError):
        backend_swap_diff(SINGLE)
    with pytest.raises(ValueError):
        backend_swap_diff(POOL, weights={"nope": 1})
    with pytest.raises(ValueError):
        BackendSwapTranslator(canary_percent=0)
