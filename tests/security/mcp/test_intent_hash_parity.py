"""REST and MCP draft the same intent hash for the same change (PRP-22 item 4, NS-06).

The same action (target, target version, diff, evidence, idempotency key, same maker) is drafted
once through the PRP-17 REST route (``POST /api/v1/actions/domains/{domain}/intents``) and once
through the item 1 MCP ``draft_action`` tool. Each channel runs in its own deployment (own intent
store, same fixed clock, same deterministic intent-id factory) so both stored intents exist side
by side. The hash is the canonical PRP-17 ``compute_confirmation_hash``
(``packages/core/neurosphere_core/actions/hashing.py``): channel, idempotency key and evidence are
excluded on purpose, target, version, diff, expiry and actor are bound.

Then both intents are validated and presented for confirmation (REST steps vs MCP tools) at the
same instant: the bound confirmation hash is identical too. Negative controls: changing one
hashed input changes the hash; changing an excluded input does not.
"""

from __future__ import annotations

from typing import Any, Final

import pytest
from neurosphere_core.actions import (
    HASHED_FIELDS,
    compute_confirmation_hash,
    confirmation_hash_input,
)
from neurosphere_core.audit.canonical import sha256_digest

from .mcp_security_harness import cs

IDEMPOTENCY_KEY: Final = "idem-parity-2026-10-22-0001"
OTHER_TARGET: Final = "commercial:contoso:foundry:agent:fin-1"
EVIDENCE: Final = [
    {
        "evidence_id": "rec-0042",
        "kind": "recommendation",
        "ref": "commercial:contoso:neurosphere:recommendation:rec-0042",
        "observed_at": None,
    }
]


def change(
    *,
    target: str = cs.TARGET,
    target_version: str = cs.TARGET_VERSION,
    new_version: str = "2026-06-15",
    evidence: list[dict[str, Any]] | None = None,
    key: str = IDEMPOTENCY_KEY,
) -> dict[str, Any]:
    """The change itself: identical dict for the REST body and the MCP tool arguments."""
    args = cs.draft_args(target, new_version)
    args["target_version"] = target_version
    args["evidence"] = [dict(e) for e in (EVIDENCE if evidence is None else evidence)]
    args["idempotency_key"] = key
    return args


def rest_draft(harness: Any, who: str, body: dict[str, Any]) -> dict[str, Any]:
    response = harness.api.draft(who, body)
    assert response.status_code == 201, response.text
    return response.json()


async def mcp_draft(client: Any, harness: Any, who: str, args: dict[str, Any]) -> dict[str, Any]:
    result = await cs.call_tool(client, harness.token(who), "draft_action", args)
    [record] = cs.records(result)
    return record["data"]


async def stored(harness: Any, intent_id: str) -> Any:
    found = await harness.api.intents.get(cs.CUSTOMER, cs.FINANCE, intent_id)
    assert found is not None
    return found.intent


async def test_rest_and_mcp_report_the_identical_intent_hash_and_record_their_channel() -> None:
    rest_side = cs.make_harness()
    mcp_side = cs.make_harness()
    assert rest_side.clock.now == mcp_side.clock.now  # same instant on both deployments

    rest_view = rest_draft(rest_side, cs.ALICE, change())
    async with cs.mcp_session(mcp_side) as client:
        mcp_data = await mcp_draft(client, mcp_side, cs.ALICE, change())

    rest_intent = rest_view["intent"]
    mcp_intent = mcp_data["action"]["intent"]
    rest_hash = compute_confirmation_hash(rest_intent)  # REST reports the intent; hash it
    mcp_hash = mcp_data["intent_hash"]  # MCP reports the hash itself
    assert rest_hash.startswith("sha256:") and len(rest_hash) == len("sha256:") + 64
    assert rest_hash == mcp_hash

    # The stored intents (not just the responses) hash identically and record their channel.
    rest_stored = await stored(rest_side, rest_intent["intent_id"])
    mcp_stored = await stored(mcp_side, mcp_intent["intent_id"])
    assert compute_confirmation_hash(rest_stored) == compute_confirmation_hash(mcp_stored)
    assert compute_confirmation_hash(rest_stored) == rest_hash
    assert (rest_stored.channel, mcp_stored.channel) == ("rest", "mcp")
    assert rest_intent["channel"] == "rest" and mcp_intent["channel"] == "mcp"

    # Same inputs really did reach both stores; only the excluded channel differs.
    for name in ("target", "target_version", "proposed_diff", "evidence", "idempotency_key"):
        assert rest_intent[name] == mcp_intent[name], name
    assert rest_intent["actor"] == mcp_intent["actor"]
    assert rest_intent["idempotency_key"] == IDEMPOTENCY_KEY

    # And it is the canonical hash of exactly the hashed fields (no channel in the input).
    hashed = confirmation_hash_input(rest_intent)
    assert tuple(hashed) == HASHED_FIELDS and "channel" not in hashed
    assert sha256_digest(hashed) == rest_hash
    assert hashed["confirmation_expires_at"] is None  # not bound yet at draft time


async def test_the_bound_confirmation_hash_is_identical_across_channels() -> None:
    rest_side = cs.make_harness()
    mcp_side = cs.make_harness()
    rest_id = rest_draft(rest_side, cs.ALICE, change())["intent"]["intent_id"]
    validated = rest_side.api.step(cs.ALICE, rest_id, "validate")
    assert validated.status_code == 200, validated.text
    presented = rest_side.api.step(cs.ALICE, rest_id, "confirmation")
    assert presented.status_code == 200, presented.text
    rest_bound = presented.json()["intent"]

    async with cs.mcp_session(mcp_side) as client:
        token = mcp_side.token(cs.ALICE)
        mcp_id = (await mcp_draft(client, mcp_side, cs.ALICE, change()))["intent_id"]
        validated_mcp = await cs.call_tool(client, token, "validate_action", {"intent_id": mcp_id})
        assert cs.records(validated_mcp)[0]["data"]["state"] == "validated"
        [record] = cs.records(
            await cs.call_tool(client, token, "present_action_confirmation", {"intent_id": mcp_id})
        )
    mcp_bound = record["data"]

    assert rest_bound["state"] == mcp_bound["state"] == "awaiting_confirmation"
    assert rest_bound["confirmation_expires_at"] == mcp_bound["confirmation_expires_at"]
    assert rest_bound["confirmation_hash"] == mcp_bound["confirmation_hash"]
    assert rest_bound["confirmation_hash"] == compute_confirmation_hash(rest_bound)
    assert mcp_bound["intent_hash"] == mcp_bound["confirmation_hash"]


async def test_a_cross_channel_replay_of_the_key_returns_the_original_intent() -> None:
    """Idempotency is per (principal, key), never per channel: MCP replaying the REST key gets
    the REST intent back (``created`` false, channel still ``rest``) and the same hash."""
    harness = cs.make_harness()
    rest_view = rest_draft(harness, cs.ALICE, change())
    async with cs.mcp_session(harness) as client:
        replay = await mcp_draft(client, harness, cs.ALICE, change())
    assert replay["created"] is False
    assert replay["intent_id"] == rest_view["intent"]["intent_id"]
    assert replay["action"]["intent"]["channel"] == "rest"
    assert replay["intent_hash"] == compute_confirmation_hash(rest_view["intent"])
    listed = harness.api.call("GET", cs.ALICE, harness.api.intents_path(cs.FINANCE))
    assert listed.status_code == 200 and len(listed.json()["items"]) == 1


# -- negative controls ---------------------------------------------------------------------------

HASHED_VARIANTS: Final[dict[str, dict[str, Any]]] = {
    "target_version": {"target_version": "etag-0x8dce1f2a3b4c5d7"},
    "diff_value": {"new_version": "2026-07-01"},
    "target": {"target": OTHER_TARGET},
}
EXCLUDED_VARIANTS: Final[dict[str, dict[str, Any]]] = {
    "evidence": {"evidence": []},
    "idempotency_key": {"key": "idem-parity-2026-10-22-0002"},
}


@pytest.mark.parametrize("variant", sorted(HASHED_VARIANTS))
async def test_changing_one_hashed_input_changes_the_hash(variant: str) -> None:
    rest_side = cs.make_harness()
    baseline = compute_confirmation_hash(rest_draft(rest_side, cs.ALICE, change())["intent"])
    mcp_side = cs.make_harness()
    async with cs.mcp_session(mcp_side) as client:
        same = await mcp_draft(client, mcp_side, cs.ALICE, change())
        changed = await mcp_draft(
            client,
            mcp_side,
            cs.ALICE,
            change(key="idem-parity-variant-0001", **HASHED_VARIANTS[variant]),
        )
    assert same["intent_hash"] == baseline  # the control itself is sound
    assert changed["intent_hash"] != baseline
    assert changed["created"] is True


async def test_a_different_maker_changes_the_hash() -> None:
    """``actor`` is bound: BOB (also a FINANCE steward) drafting the same change differs."""
    rest_side = cs.make_harness()
    baseline = compute_confirmation_hash(rest_draft(rest_side, cs.ALICE, change())["intent"])
    mcp_side = cs.make_harness()
    async with cs.mcp_session(mcp_side) as client:
        by_bob = await mcp_draft(client, mcp_side, cs.BOB, change())
    assert by_bob["intent_hash"] != baseline


@pytest.mark.parametrize("variant", sorted(EXCLUDED_VARIANTS))
async def test_changing_an_excluded_input_keeps_the_hash(variant: str) -> None:
    rest_side = cs.make_harness()
    baseline = compute_confirmation_hash(rest_draft(rest_side, cs.ALICE, change())["intent"])
    mcp_side = cs.make_harness()
    async with cs.mcp_session(mcp_side) as client:
        other = await mcp_draft(client, mcp_side, cs.ALICE, change(**EXCLUDED_VARIANTS[variant]))
    assert other["intent_hash"] == baseline
