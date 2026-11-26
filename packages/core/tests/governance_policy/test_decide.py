"""``PolicyDecider`` (PRP-105 item 4, acceptance criterion 7): matrix, exceptions, snapshot."""

from __future__ import annotations

import pytest
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.governance.policy import (
    DECIDABLE_KINDS,
    AuditDecisionRecorder,
    InMemoryBindingStore,
    InMemoryExceptionStore,
    InMemoryPolicyDefinitionStore,
    PolicyDecider,
    PolicyDecision,
)
from neurosphere_core.governance.policy.decide import (
    CATALOG_UNAVAILABLE,
    EXCEPTION_APPLIED,
    NO_RULE_MATCHED,
    OPERATION_DECIDE,
    RULE_MATCHED_AUDIT,
    RULE_MATCHED_ENFORCE,
    SNAPSHOT_UNAVAILABLE,
    STALE_SNAPSHOT,
)
from neurosphere_core.governance.policy.models import POINTS_BY_RULE_KIND, PolicyDecisionRequest
from neurosphere_core.scope import IdentityScope

from .decide_helpers import (
    BREACH,
    COMPLY,
    DOMAIN_A,
    PII_SOURCE,
    READER,
    SCOPE_A,
    Recorder,
    Settings,
    approve_exception,
    at,
    decider,
    publish,
    request,
    set_mode,
    spies,
    world,
)
from .engine_helpers import AuditClock

KINDS = sorted(BREACH)
MODE_EFFECT = {"audit": "audit", "enforce": "deny"}


def test_decidable_kinds_are_the_request_evaluable_subset() -> None:
    assert sorted(DECIDABLE_KINDS) == KINDS
    for kind in KINDS:
        assert BREACH[kind][0] in POINTS_BY_RULE_KIND[kind]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("mode", ["audit", "enforce"])
async def test_breach_effect_follows_the_binding_mode(kind: str, mode: str) -> None:
    engine = await world()
    pid = await publish(engine, kind)
    point, _, fields = BREACH[kind]
    if mode != "audit":
        await set_mode(engine, pid, point, mode)
    response = await decider(engine).decide(SCOPE_A, request(point, **fields), now=at(1))

    assert response.effect == MODE_EFFECT[mode]
    assert response.mode.root == mode
    assert response.degraded is False
    assert response.cache_ttl_seconds == 60
    assert [(m.policy_id.root, m.rule_id.root, m.rule_kind.root) for m in response.matches] == [
        (pid, f"r-{kind.replace('_', '-')}", kind)
    ]
    assert response.matches[0].policy_version == 1
    assert response.matches[0].effect == MODE_EFFECT[mode]
    expected = RULE_MATCHED_ENFORCE if mode == "enforce" else RULE_MATCHED_AUDIT
    assert [c.root for c in response.reason_codes] == [expected]


@pytest.mark.parametrize("kind", KINDS)
async def test_off_binding_is_ignored(kind: str) -> None:
    engine = await world()
    pid = await publish(engine, kind)
    point, _, fields = BREACH[kind]
    await set_mode(engine, pid, point, "off")
    response = await decider(engine).decide(SCOPE_A, request(point, **fields), now=at(1))

    assert response.effect == "allow"
    assert response.matches == []
    assert response.mode.root == "off"
    assert [c.root for c in response.reason_codes] == [NO_RULE_MATCHED]


@pytest.mark.parametrize("kind", KINDS)
async def test_compliant_request_is_allowed_under_enforce(kind: str) -> None:
    engine = await world()
    pid = await publish(engine, kind)
    point = BREACH[kind][0]
    await set_mode(engine, pid, point, "enforce")
    response = await decider(engine).decide(SCOPE_A, request(point, **COMPLY[kind]), now=at(1))

    assert response.effect == "allow"
    assert response.matches == []
    assert response.mode.root == "enforce"


async def test_rule_not_bound_at_the_request_point_is_ignored() -> None:
    engine = await world()
    pid = await publish(engine, "data_sensitivity_access")
    await set_mode(engine, pid, "tool_call", "enforce")
    fields = BREACH["data_sensitivity_access"][2]
    # gateway is not a data_sensitivity_access point, so no binding and no evaluation there.
    response = await decider(engine).decide(SCOPE_A, request("gateway", **fields), now=at(1))
    assert response.effect == "allow"
    assert response.matches == []


async def test_deny_wins_over_audit_and_matches_are_ordered() -> None:
    engine = await world()
    await publish(engine, "residency", policy_id="a-residency")
    enforce = await publish(engine, "model_allow_list", policy_id="b-models")
    await set_mode(engine, enforce, "gateway", "enforce")
    fields = {
        **BREACH["model_allow_list"][2],
        "data_asset_ids": [PII_SOURCE],
    }
    response = await decider(engine).decide(SCOPE_A, request("gateway", **fields), now=at(1))

    assert response.effect == "deny"
    assert [(m.policy_id.root, m.effect) for m in response.matches] == [
        ("b-models", "deny"),
        ("a-residency", "audit"),
    ]
    assert [c.root for c in response.reason_codes] == [RULE_MATCHED_ENFORCE, RULE_MATCHED_AUDIT]
    assert response.mode.root == "enforce"


async def test_active_exception_turns_deny_into_allow_with_the_exception_id() -> None:
    engine = await world()
    pid = await publish(engine, "data_sensitivity_access")
    await set_mode(engine, pid, "tool_call", "enforce")
    exception_id = await approve_exception(
        engine, policy_id=pid, rule_id="r-data-sensitivity-access", subject=READER
    )
    fields = BREACH["data_sensitivity_access"][2]
    decision = await decider(engine).decide_detail(
        SCOPE_A, request("tool_call", **fields), now=at(1)
    )

    response = decision.response
    assert response.effect == "allow"
    assert [m.effect for m in response.matches] == ["allow"]
    assert [c.root for c in response.reason_codes] == [EXCEPTION_APPLIED]
    assert decision.applied_exception_ids == (exception_id,)
    assert decision.would_deny is False
    assert [(b.policy_id, b.mode) for b in decision.bindings] == [(pid, "enforce")]


async def test_expired_exception_does_not_apply() -> None:
    engine = await world()
    pid = await publish(engine, "data_sensitivity_access")
    await set_mode(engine, pid, "tool_call", "enforce")
    await approve_exception(
        engine,
        policy_id=pid,
        rule_id="r-data-sensitivity-access",
        subject=READER,
        expires_at="2026-10-17T12:00:30Z",
    )
    fields = BREACH["data_sensitivity_access"][2]
    pdp = decider(engine, settings=Settings(ttl=0))
    before = await pdp.decide_detail(SCOPE_A, request("tool_call", **fields), now=at(10))
    after = await pdp.decide_detail(SCOPE_A, request("tool_call", **fields), now=at(31))

    assert before.response.effect == "allow"
    assert after.response.effect == "deny"
    assert after.applied_exception_ids == ()


async def test_exception_expiring_inside_the_snapshot_ttl_stops_applying_at_expiry() -> None:
    """The snapshot outlives the exception: the per-request expiry check must still drop it."""
    engine = await world()
    pid = await publish(engine, "data_sensitivity_access")
    await set_mode(engine, pid, "tool_call", "enforce")
    exception_id = await approve_exception(
        engine,
        policy_id=pid,
        rule_id="r-data-sensitivity-access",
        subject=READER,
        expires_at="2026-10-17T12:00:30Z",
    )
    fields = BREACH["data_sensitivity_access"][2]
    pdp = decider(engine, settings=Settings(ttl=60))
    before = await pdp.decide_detail(SCOPE_A, request("tool_call", **fields), now=at(10))
    after = await pdp.decide_detail(SCOPE_A, request("tool_call", **fields), now=at(31))

    assert before.response.effect == "allow"
    assert before.applied_exception_ids == (exception_id,)
    # same snapshot (31 s < 60 s TTL), so only the per-request expiry check can refuse it
    assert after.response.policy_set_digest == before.response.policy_set_digest
    assert after.response.effect == "deny"
    assert after.applied_exception_ids == ()


async def test_exception_for_another_rule_or_subject_does_not_apply() -> None:
    engine = await world()
    pid = await publish(engine, "data_sensitivity_access")
    await set_mode(engine, pid, "tool_call", "enforce")
    await approve_exception(engine, policy_id=pid, rule_id="other-rule", subject=READER)
    await approve_exception(
        engine, policy_id=pid, rule_id="r-data-sensitivity-access", subject=PII_SOURCE
    )
    fields = BREACH["data_sensitivity_access"][2]
    response = await decider(engine).decide(SCOPE_A, request("tool_call", **fields), now=at(1))
    assert response.effect == "deny"


# --- snapshot ------------------------------------------------------------------------------------


async def test_snapshot_is_reused_within_the_ttl_and_refreshed_after_it() -> None:
    engine = await world()
    point, _, fields = BREACH["model_allow_list"]
    pdp = decider(engine, settings=Settings(ttl=60))
    first = await pdp.decide(SCOPE_A, request(point, **fields), now=at(0))
    assert first.effect == "allow"

    await publish(engine, "model_allow_list")
    cached = await pdp.decide(SCOPE_A, request(point, **fields), now=at(59))
    refreshed = await pdp.decide(SCOPE_A, request(point, **fields), now=at(60))

    assert cached.effect == "allow"
    assert cached.policy_set_digest == first.policy_set_digest
    assert refreshed.effect == "audit"
    assert refreshed.policy_set_digest != first.policy_set_digest


async def test_ttl_comes_from_the_enforcement_setting() -> None:
    engine = await world()
    point, _, fields = BREACH["model_allow_list"]
    settings = Settings(ttl=5)
    pdp = decider(engine, settings=settings)
    first = await pdp.decide(SCOPE_A, request(point, **fields), now=at(0))
    assert first.cache_ttl_seconds == 5
    await publish(engine, "model_allow_list")
    after_ttl = await pdp.decide(SCOPE_A, request(point, **fields), now=at(5))
    assert after_ttl.effect == "audit"


def test_default_settings_give_sixty_seconds() -> None:
    pdp = PolicyDecider(
        InMemoryPolicyDefinitionStore(), InMemoryBindingStore(), InMemoryExceptionStore()
    )
    assert pdp.ttl_seconds() == 60


async def test_invalidate_forces_a_refresh() -> None:
    engine = await world()
    point, _, fields = BREACH["model_allow_list"]
    pdp = decider(engine)
    first = await pdp.decide(SCOPE_A, request(point, **fields), now=at(0))
    pid = await publish(engine, "model_allow_list")
    await set_mode(engine, pid, point, "enforce")
    cached = await pdp.decide(SCOPE_A, request(point, **fields), now=at(1))
    pdp.invalidate("acme")
    refreshed = await pdp.decide(SCOPE_A, request(point, **fields), now=at(2))

    assert first.effect == "allow"
    assert cached.effect == "allow"
    assert refreshed.effect == "deny"


async def test_refresh_failure_keeps_the_last_snapshot_and_reports_stale() -> None:
    engine = await world()
    pid = await publish(engine, "model_allow_list")
    point, _, fields = BREACH["model_allow_list"]
    await set_mode(engine, pid, point, "enforce")
    stores = spies(engine)
    pdp = decider(engine, spies=stores)
    good = await pdp.decide(SCOPE_A, request(point, **fields), now=at(0))
    assert good.effect == "deny" and good.degraded is False

    stores[0].fail = True
    stale = await pdp.decide(SCOPE_A, request(point, **fields), now=at(61))
    assert stale.effect == "deny"  # the last snapshot still answers
    assert stale.degraded is True
    assert stale.cache_ttl_seconds == 0
    assert STALE_SNAPSHOT in [c.root for c in stale.reason_codes]
    assert stale.policy_set_digest == good.policy_set_digest

    stores[0].fail = False
    recovered = await pdp.decide(SCOPE_A, request(point, **fields), now=at(70))
    assert recovered.degraded is False
    assert STALE_SNAPSHOT not in [c.root for c in recovered.reason_codes]


async def test_no_snapshot_at_all_is_a_degraded_audit_never_a_deny() -> None:
    engine = await world()
    pid = await publish(engine, "model_allow_list")
    point, _, fields = BREACH["model_allow_list"]
    await set_mode(engine, pid, point, "enforce")
    stores = spies(engine)
    stores[1].fail = True
    response = await decider(engine, spies=stores).decide(
        SCOPE_A, request(point, **fields), now=at(0)
    )

    assert response.effect == "audit"
    assert response.mode.root == "audit"
    assert response.degraded is True
    assert response.matches == []
    assert response.cache_ttl_seconds == 0
    assert [c.root for c in response.reason_codes] == [SNAPSHOT_UNAVAILABLE]


async def test_decide_performs_no_write() -> None:
    engine = await world()
    pid = await publish(engine, "data_sensitivity_access")
    await set_mode(engine, pid, "tool_call", "enforce")
    await approve_exception(engine, policy_id=pid, rule_id="r-other", subject=READER)
    stores = spies(engine)
    pdp = decider(engine, spies=stores, settings=Settings(ttl=0))
    fields = BREACH["data_sensitivity_access"][2]
    for second in range(3):
        await pdp.decide(SCOPE_A, request("tool_call", **fields), now=at(second))

    calls = [name for spy in stores for name in spy.calls]
    assert calls, "the snapshot must have been read"
    assert sorted(set(calls)) == ["list", "list_published"]
    assert [spy.writes() for spy in stores] == [[], [], []]


async def test_without_a_catalog_catalog_rules_are_unassessed() -> None:
    engine = await world()
    pid = await publish(engine, "data_sensitivity_access")
    await set_mode(engine, pid, "tool_call", "enforce")
    fields = BREACH["data_sensitivity_access"][2]
    response = await decider(engine, catalog=False).decide(
        SCOPE_A, request("tool_call", **fields), now=at(1)
    )
    assert response.effect == "allow"
    assert [c.root for c in response.reason_codes] == [CATALOG_UNAVAILABLE, NO_RULE_MATCHED]


async def test_naive_now_is_refused() -> None:
    engine = await world()
    point, _, fields = BREACH["model_allow_list"]
    with pytest.raises(ValueError):
        await decider(engine).decide(
            SCOPE_A, request(point, **fields), now=at(0).replace(tzinfo=None)
        )


# --- audit ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(("mode", "recorded"), [("enforce", True), ("audit", True), ("off", False)])
async def test_recorder_sees_deny_and_audit_would_deny_only(mode: str, recorded: bool) -> None:
    engine = await world()
    pid = await publish(engine, "model_allow_list")
    point, _, fields = BREACH["model_allow_list"]
    await set_mode(engine, pid, point, mode)
    recorder = Recorder()
    pdp = decider(engine, recorder=recorder)
    await pdp.decide(SCOPE_A, request(point, **fields), now=at(1))
    await pdp.decide(SCOPE_A, request(point, **COMPLY["model_allow_list"]), now=at(2))

    assert len(recorder.decisions) == int(recorded)
    if recorded:
        assert recorder.decisions[0].would_deny is True


async def test_excepted_match_is_not_audited() -> None:
    engine = await world()
    pid = await publish(engine, "data_sensitivity_access")
    await set_mode(engine, pid, "tool_call", "enforce")
    await approve_exception(
        engine, policy_id=pid, rule_id="r-data-sensitivity-access", subject=READER
    )
    recorder = Recorder()
    fields = BREACH["data_sensitivity_access"][2]
    await decider(engine, recorder=recorder).decide(
        SCOPE_A, request("tool_call", **fields), now=at(1)
    )
    assert recorder.decisions == []


async def test_audit_recorder_writes_one_govpolicy_decide_record() -> None:
    engine = await world()
    pid = await publish(engine, "model_allow_list")
    point, _, fields = BREACH["model_allow_list"]
    await set_mode(engine, pid, point, "enforce")
    audit = AuditRepository(InMemoryAuditStore(), clock=AuditClock())
    pdp = decider(engine, recorder=AuditDecisionRecorder(audit))
    response = await pdp.decide(SCOPE_A, request(point, **fields), now=at(1))
    await pdp.decide(SCOPE_A, request(point, **COMPLY["model_allow_list"]), now=at(2))

    records = await audit.read_range("acme.governance-policy", start=0, limit=10)
    assert [r.operation for r in records] == [OPERATION_DECIDE]
    record = records[0]
    assert record.subject is not None
    assert record.subject.target.canonical_id.endswith(response.decision_id.root)
    assert record.outcome is not None and record.outcome.detail == "effect=deny"
    assert READER not in record.model_dump_json()


async def test_recorder_failure_does_not_change_the_answer() -> None:
    engine = await world()
    pid = await publish(engine, "model_allow_list")
    point, _, fields = BREACH["model_allow_list"]
    await set_mode(engine, pid, point, "enforce")

    class Broken:
        async def record(
            self, scope: IdentityScope, request: PolicyDecisionRequest, decision: PolicyDecision
        ) -> None:
            raise ConnectionError("audit down")

    pdp = decider(engine, recorder=Broken())
    response = await pdp.decide(SCOPE_A, request(point, **fields), now=at(1))
    assert response.effect == "deny"


def test_domain_constant_matches_the_harness() -> None:
    assert DOMAIN_A.endswith(":domain:a")
