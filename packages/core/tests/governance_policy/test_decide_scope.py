"""``PolicyDecider`` scope rules (PRP-105 item 4): nothing outside the caller's scope is described.

A subject in a domain the caller cannot see reads exactly like a missing one; a policy outside
the scope is never applied or named; a customer-wide policy applies only through a domain the
scope sees; another customer's or cloud's scope sees none of it; an empty scope matches nothing.
"""

from __future__ import annotations

from neurosphere_core.governance.policy.decide import NO_RULE_MATCHED

from .decide_helpers import (
    BREACH,
    CONTROL,
    DOMAIN_A,
    DOMAIN_B,
    DOMAIN_HIDDEN,
    GHOST_AGENT,
    HIDDEN_AGENT,
    HIDDEN_SOURCE,
    READER,
    SCOPE_A,
    approve_exception,
    at,
    decider,
    publish,
    request,
    scope_for,
    set_mode,
    world,
)


def _strip_id(payload: str, decision_id: str) -> str:
    return payload.replace(decision_id, "<id>")


async def test_out_of_scope_asset_is_never_described_or_matched() -> None:
    engine = await world()
    pid = await publish(engine, "data_sensitivity_access")
    await set_mode(engine, pid, "tool_call", "enforce")
    fields = {**BREACH["data_sensitivity_access"][2], "data_asset_ids": [HIDDEN_SOURCE]}
    response = await decider(engine).decide(SCOPE_A, request("tool_call", **fields), now=at(1))

    assert response.effect == "allow"
    assert response.matches == []
    body = response.model_dump_json()
    assert HIDDEN_SOURCE not in body
    assert "hidden" not in body


async def test_out_of_scope_subject_reads_exactly_like_a_missing_one() -> None:
    engine = await world()
    pid = await publish(engine, "registration_required")
    await set_mode(engine, pid, "registration", "enforce")
    pdp = decider(engine)
    hidden = await pdp.decide(
        SCOPE_A, request("registration", operation="register", agent_id=HIDDEN_AGENT), now=at(1)
    )
    missing = await pdp.decide(
        SCOPE_A, request("registration", operation="register", agent_id=GHOST_AGENT), now=at(1)
    )

    assert HIDDEN_AGENT not in hidden.model_dump_json()
    assert _strip_id(hidden.model_dump_json(), hidden.decision_id.root) == _strip_id(
        missing.model_dump_json(), missing.decision_id.root
    )


async def test_policy_outside_the_scope_is_never_applied_or_named() -> None:
    engine = await world()
    pid = await publish(engine, "model_allow_list", policy_id="finance-models", domain=DOMAIN_B)
    point, _, fields = BREACH["model_allow_list"]
    await set_mode(engine, pid, point, "enforce")
    pdp = decider(engine)
    outside = await pdp.decide(SCOPE_A, request(point, **fields), now=at(1))
    nothing = await decider(await world()).decide(SCOPE_A, request(point, **fields), now=at(1))
    inside = await pdp.decide(scope_for([DOMAIN_B]), request(point, **fields), now=at(1))

    assert outside.effect == "allow"
    assert "finance-models" not in outside.model_dump_json()
    # The digest covers only the policies in scope, so it does not reveal the hidden policy.
    assert outside.policy_set_digest == nothing.policy_set_digest
    assert inside.effect == "deny"


async def test_entity_in_another_visible_domain_is_not_governed_by_a_domain_policy() -> None:
    engine = await world()
    pid = await publish(engine, "data_sensitivity_access", domain=DOMAIN_B)
    await set_mode(engine, pid, "tool_call", "enforce")
    fields = BREACH["data_sensitivity_access"][2]  # the PII source lives in domain a
    both = scope_for([DOMAIN_A, DOMAIN_B])
    response = await decider(engine).decide(both, request("tool_call", **fields), now=at(1))
    assert response.effect == "allow"


async def test_customer_wide_policy_needs_a_visible_domain() -> None:
    engine = await world()
    pid = await publish(engine, "data_sensitivity_access", policy_id="customer-pii", domain=CONTROL)
    await set_mode(engine, pid, "tool_call", "enforce")
    fields = BREACH["data_sensitivity_access"][2]
    pdp = decider(engine)
    control_only = await pdp.decide(scope_for([CONTROL]), request("tool_call", **fields), now=at(1))
    with_a = await pdp.decide(
        scope_for([CONTROL, DOMAIN_A]), request("tool_call", **fields), now=at(1)
    )
    a_only = await pdp.decide(SCOPE_A, request("tool_call", **fields), now=at(1))
    b_only = await pdp.decide(scope_for([DOMAIN_B]), request("tool_call", **fields), now=at(1))

    assert control_only.effect == "allow"
    assert "customer-pii" not in control_only.model_dump_json()
    assert with_a.effect == "deny"
    assert a_only.effect == "deny"
    # Domain b is visible, but the PII source it would govern lives in domain a.
    assert b_only.effect == "allow"


async def test_wrong_customer_sees_nothing_of_another_customer() -> None:
    engine = await world()
    pid = await publish(engine, "model_allow_list")
    point, _, fields = BREACH["model_allow_list"]
    await set_mode(engine, pid, point, "enforce")
    other = scope_for(["commercial:globex:neurosphere:domain:a"], customer="globex")
    response = await decider(engine).decide(other, request(point, **fields), now=at(1))

    assert response.effect == "allow"
    assert response.matches == []
    body = response.model_dump_json()
    assert pid not in body
    assert READER not in body


async def test_wrong_cloud_sees_nothing() -> None:
    engine = await world()
    pid = await publish(engine, "model_allow_list")
    point, _, fields = BREACH["model_allow_list"]
    await set_mode(engine, pid, point, "enforce")
    gov = scope_for(["government:acme:neurosphere:domain:a"], cloud="government")
    response = await decider(engine).decide(gov, request(point, **fields), now=at(1))
    assert response.effect == "allow"
    assert pid not in response.model_dump_json()


async def test_empty_scope_matches_nothing() -> None:
    engine = await world()
    pid = await publish(engine, "model_allow_list")
    point, _, fields = BREACH["model_allow_list"]
    await set_mode(engine, pid, point, "enforce")
    response = await decider(engine).decide(scope_for([]), request(point, **fields), now=at(1))

    assert response.effect == "allow"
    assert response.matches == []
    assert response.mode.root == "off"
    assert [c.root for c in response.reason_codes] == [NO_RULE_MATCHED]


async def test_exception_in_a_domain_the_scope_cannot_see_does_not_apply() -> None:
    engine = await world()
    pid = await publish(engine, "data_sensitivity_access", domain=CONTROL)
    await set_mode(engine, pid, "tool_call", "enforce")
    await approve_exception(
        engine,
        policy_id=pid,
        rule_id="r-data-sensitivity-access",
        subject=READER,
        domain=DOMAIN_HIDDEN,
    )
    fields = BREACH["data_sensitivity_access"][2]
    pdp = decider(engine)
    response = await pdp.decide_detail(SCOPE_A, request("tool_call", **fields), now=at(1))

    assert response.response.effect == "deny"
    assert response.applied_exception_ids == ()


async def test_snapshot_widens_to_load_exceptions_of_a_newly_seen_domain() -> None:
    engine = await world()
    pid = await publish(engine, "data_sensitivity_access", domain=CONTROL)
    await set_mode(engine, pid, "tool_call", "enforce")
    exception_id = await approve_exception(
        engine,
        policy_id=pid,
        rule_id="r-data-sensitivity-access",
        subject=READER,
        domain=DOMAIN_B,
    )
    fields = BREACH["data_sensitivity_access"][2]
    pdp = decider(engine)
    first = await pdp.decide_detail(SCOPE_A, request("tool_call", **fields), now=at(1))
    wider = await pdp.decide_detail(
        scope_for([DOMAIN_A, DOMAIN_B]), request("tool_call", **fields), now=at(2)
    )

    assert first.response.effect == "deny"
    assert wider.response.effect == "allow"
    assert wider.applied_exception_ids == (exception_id,)
