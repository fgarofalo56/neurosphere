"""``PolicyLifecycle`` and the intent diff grammars (PRP-105 item 3, criteria 5, 6, 9 and 10)."""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_contracts.actions.v1.action_intent import ProposedDiff
from neurosphere_core.actions.hashing import diff_to_wire, validate_proposed_diff
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.governance.policy import (
    POINTS_BY_RULE_KIND,
    GovernancePolicyNotFoundError,
    GovernancePolicyStaleError,
    LifecycleAuditContext,
    PolicyPublishedError,
    PublishRefusedError,
    binding_points_for,
    check_publishable,
    mode_change_diff,
    mode_change_target,
    parse_mode_change_diff,
    parse_publish_diff,
    policy_digest,
    publish_diff,
    publish_refusals,
    publish_target,
    publish_target_version,
    validate_draft,
)

from .engine_helpers import (
    CUSTOMER,
    DOMAIN_HIDDEN,
    INTENT,
    WORKER_ID,
    WORKER_SCOPE,
    Engine,
    build_engine,
    make_scope,
    policy_draft,
    rule,
)
from .rules.rules_helpers import SCOPE
from .rules.rules_helpers import make_scope as idp_scope

PII_POINTS = set(POINTS_BY_RULE_KIND["data_sensitivity_access"])
BUDGET_RULE = rule(
    "monthly-cap",
    "budget",
    {"budget_record_id": "budget-support-monthly", "threshold_percent": 100, "on_breach": "alert"},
)


def _ctx(**kw: Any) -> LifecycleAuditContext:
    return LifecycleAuditContext(
        scope=kw.pop("scope", WORKER_SCOPE),
        correlation_id="corr-life",
        intent_id=kw.pop("intent_id", INTENT),
        **kw,
    )


async def _publish(engine: Engine, body: dict[str, Any], **kw: Any) -> Any:
    created = await engine.create(body)
    return await engine.lifecycle.publish(
        created.policy.policy_id.root,
        created.policy.policy_version,
        expected_etag=created.etag,
        audit_ctx=_ctx(**kw),
    )


# --- publish ----------------------------------------------------------------------------------


async def test_publish_marks_published_and_binds_every_point_in_audit() -> None:
    engine = await build_engine()

    outcome = await _publish(engine, policy_draft())

    policy = outcome.stored.policy
    assert policy.status == "published"
    assert policy.published_intent_id is not None
    assert policy.published_intent_id.root == INTENT
    assert policy.published_audit_id is not None
    assert policy.published_audit_id.root == outcome.audit_id
    assert {b.binding.point.root for b in outcome.bindings} == PII_POINTS
    assert {b.binding.mode.root for b in outcome.bindings if b.binding.mode} == {"audit"}
    assert {b.binding.state for b in outcome.bindings} == {"pending"}
    stored = await engine.bindings.list(CUSTOMER, policy_id="pii-guard")
    assert len(stored) == len(PII_POINTS)
    assert outcome.projection.action == "created"
    records = await engine.records()
    publish = [r for r in records if r.operation == "govpolicy.publish"]
    assert [r.kind for r in publish] == ["before", "after"]
    assert str(publish[0].audit_id.root) == outcome.audit_id


async def test_an_off_policy_gets_off_bindings() -> None:
    engine = await build_engine()

    outcome = await _publish(engine, policy_draft(mode="off"))

    assert {b.binding.mode.root for b in outcome.bindings if b.binding.mode} == {"off"}


async def test_publishing_with_mode_enforce_is_refused_and_changes_nothing() -> None:
    engine = await build_engine()
    created = await engine.create(policy_draft(mode="enforce"))

    with pytest.raises(PublishRefusedError) as info:
        await engine.lifecycle.publish("pii-guard", 1, expected_etag=created.etag, audit_ctx=_ctx())

    assert info.value.reason == "enforce_requires_mode_change"
    still = await engine.policies.get(CUSTOMER, "pii-guard")
    assert still is not None
    assert still.policy.status == "draft"
    no_bindings = await engine.bindings.list(CUSTOMER)
    assert no_bindings == []
    operations = await engine.operations()
    assert "govpolicy.publish" not in operations


async def test_a_rule_kind_without_an_evaluator_is_refused_in_the_dry_run() -> None:
    engine = await build_engine()
    body = policy_draft(rules=[BUDGET_RULE])
    draft_policy = validate_draft(body)

    refusals = publish_refusals(draft_policy, engine.registry)
    assert [(r.reason, r.pointer) for r in refusals] == [("rule_kind_unavailable", "/rules/0/kind")]
    with pytest.raises(PublishRefusedError) as dry:
        check_publishable(draft_policy, engine.registry)
    assert dry.value.reason == "rule_kind_unavailable"

    created = await engine.create(body)
    with pytest.raises(PublishRefusedError) as info:
        await engine.lifecycle.publish("pii-guard", 1, expected_etag=created.etag, audit_ctx=_ctx())
    assert info.value.reason == "rule_kind_unavailable"
    still = await engine.policies.get(CUSTOMER, "pii-guard")
    assert still is not None
    assert still.policy.status == "draft"


async def test_content_rule_is_unavailable_while_no_finding_reader_is_bound() -> None:
    engine = await build_engine()
    engine.registry.mark_unavailable("content_rule", "finding_reader_unbound")
    content = rule(
        "no-secrets",
        "content_rule",
        {
            "detected_categories": ["payment_card"],
            "min_count": 1,
            "parts": ["prompt"],
            "window_minutes": 60,
        },
    )
    draft_policy = validate_draft(policy_draft(rules=[content]))
    refusals = publish_refusals(draft_policy, engine.registry)
    assert [r.reason for r in refusals] == ["rule_kind_unavailable"]
    assert engine.registry.unavailable_reason("content_rule") == "finding_reader_unbound"


async def test_both_refusals_are_listed_with_enforce_first() -> None:
    engine = await build_engine()
    draft_policy = validate_draft(policy_draft(mode="enforce", rules=[rule(), BUDGET_RULE]))

    refusals = publish_refusals(draft_policy, engine.registry)

    assert [r.reason for r in refusals] == ["enforce_requires_mode_change", "rule_kind_unavailable"]


async def test_publish_guards_etag_digest_state_intent_and_scope() -> None:
    engine = await build_engine()
    created = await engine.create(policy_draft())
    with pytest.raises(GovernancePolicyStaleError):
        await engine.lifecycle.publish("pii-guard", 1, expected_etag='"nope"', audit_ctx=_ctx())
    with pytest.raises(GovernancePolicyStaleError):
        await engine.lifecycle.publish(
            "pii-guard",
            1,
            expected_etag=created.etag,
            audit_ctx=_ctx(),
            expected_digest="sha256:" + "0" * 64,
        )
    with pytest.raises(InvalidSchemaError) as missing:
        await engine.lifecycle.publish(
            "pii-guard", 1, expected_etag=created.etag, audit_ctx=_ctx(intent_id=None)
        )
    assert missing.value.reason == "intent_required"
    outsider = make_scope("a", [("domain_steward", [DOMAIN_HIDDEN])], [DOMAIN_HIDDEN])
    with pytest.raises(GovernancePolicyNotFoundError):
        await engine.lifecycle.publish(
            "pii-guard", 1, expected_etag=created.etag, audit_ctx=_ctx(scope=outsider)
        )
    done = await engine.lifecycle.publish(
        "pii-guard",
        1,
        expected_etag=created.etag,
        audit_ctx=_ctx(),
        expected_digest=policy_digest(created.policy),
    )
    with pytest.raises(PolicyPublishedError):
        await engine.lifecycle.publish(
            "pii-guard", 1, expected_etag=done.stored.etag, audit_ctx=_ctx()
        )


async def test_a_later_publish_never_resets_an_approved_enforce_binding() -> None:
    engine = await build_engine()
    first = await _publish(engine, policy_draft())
    sdk = next(b for b in first.bindings if b.binding.point.root == "sdk")
    # the only path to enforce: BindingStore.set_mode (PRP-108's mode-change handler)
    await engine.bindings.set_mode(
        CUSTOMER, sdk.binding.binding_id.root, "enforce", if_match=sdk.etag, updated_by=WORKER_ID
    )
    retired_draft = policy_draft()
    retired_draft.update({"policy_version": 2, "previous_version": 1})

    second = await _publish(engine, retired_draft)

    modes = {b.binding.point.root: b.binding.mode.root for b in second.bindings if b.binding.mode}
    assert modes["sdk"] == "enforce"
    assert {m for p, m in modes.items() if p != "sdk"} == {"audit"}


async def test_a_binding_failure_leaves_the_policy_published_and_the_next_tick_repairs_it() -> None:
    engine = await build_engine()
    # an identity-provider principal is not a pseudonymous admin_config author: bindings refuse
    odd = idp_scope("a")

    outcome = await _publish(engine, policy_draft(), scope=odd)

    assert outcome.stored.policy.status == "published"
    assert outcome.bindings_reason == "bindings_failed"
    no_bindings = await engine.bindings.list(CUSTOMER)
    assert no_bindings == []
    run = await engine.tick()
    (reconciled,) = run.reconciled
    assert reconciled.bindings == len(PII_POINTS)
    assert reconciled.bindings_reason is None
    repaired = await engine.bindings.list(CUSTOMER)
    assert len(repaired) == len(PII_POINTS)


# --- retire -----------------------------------------------------------------------------------


async def test_retire_marks_retired_and_deprecates_the_catalog_entity() -> None:
    engine = await build_engine()
    published = await _publish(engine, policy_draft())

    outcome = await engine.lifecycle.retire(
        "pii-guard", 1, expected_etag=published.stored.etag, audit_ctx=_ctx()
    )

    assert outcome.stored.policy.status == "retired"
    assert outcome.projection.action == "deprecated"
    entity = await engine.catalog.get_entity(SCOPE, outcome.projection.entity_id)
    assert entity is not None
    assert entity.model_dump(mode="json")["lifecycle_status"] == "deprecated"
    retire = [r for r in await engine.records() if r.operation == "govpolicy.retire"]
    assert [r.kind for r in retire] == ["before", "after"]
    with pytest.raises(GovernancePolicyStaleError):
        await engine.lifecycle.retire(
            "pii-guard", 1, expected_etag=outcome.stored.etag, audit_ctx=_ctx()
        )


async def test_retiring_a_draft_is_refused() -> None:
    engine = await build_engine()
    created = await engine.create(policy_draft())
    with pytest.raises(GovernancePolicyStaleError) as info:
        await engine.lifecycle.retire("pii-guard", 1, expected_etag=created.etag, audit_ctx=_ctx())
    assert info.value.reason == "policy_not_published"


async def test_the_seed_flag_audits_as_govpolicy_seed() -> None:
    engine = await build_engine()
    await _publish(engine, policy_draft(), seed=True)
    operations = await engine.operations()
    assert "govpolicy.seed" in operations
    assert "govpolicy.publish" not in operations


def test_binding_points_follow_the_rule_kinds_without_repeats() -> None:
    policy = validate_draft(policy_draft(rules=[rule("one"), rule("two")]))
    assert binding_points_for(policy) == POINTS_BY_RULE_KIND["data_sensitivity_access"]


# --- diff grammars ----------------------------------------------------------------------------


def _draft_policy() -> Any:
    return validate_draft(policy_draft())


def test_publish_diff_round_trips_and_passes_the_executor_check() -> None:
    policy = _draft_policy()
    diff = publish_diff("publish", policy)
    validate_proposed_diff(diff)
    parsed = parse_publish_diff(diff)
    assert parsed.stage == "publish"
    assert parsed.policy_version == 1
    assert parsed.policy_digest == policy_digest(policy)
    # the wire form (what REST, chat and MCP send) parses the same
    assert parse_publish_diff(diff_to_wire(diff)) == parsed
    target = publish_target(policy)
    assert target.entity_type == "governance_policy"
    assert target.canonical_id == "commercial:acme:neurosphere:governance_policy:pii-guard"
    assert publish_target_version(policy) == "v1"


def test_the_policy_digest_ignores_publish_fields_but_not_rules_or_mode() -> None:
    policy = _draft_policy()
    published = policy.model_copy(update={"status": "published"})
    assert policy_digest(published) == policy_digest(policy)
    changed = validate_draft({**policy_draft(), "mode": "off"})
    assert policy_digest(changed) != policy_digest(policy)


def test_retire_diff_needs_a_published_version() -> None:
    policy = _draft_policy()
    with pytest.raises(InvalidSchemaError) as info:
        publish_diff("retire", policy)
    assert info.value.reason == "policy_not_published"
    retire = publish_diff("retire", policy.model_copy(update={"status": "published"}))
    assert parse_publish_diff(retire).stage == "retire"


@pytest.mark.parametrize(
    "operations",
    [
        [{"op": "replace", "path": "/status", "value": "published"}],
        [
            {"op": "test", "path": "/policy_version", "value": 1},
            {"op": "test", "path": "/policy_digest", "value": "sha256:" + "a" * 64},
            {"op": "replace", "path": "/status", "value": "published"},
            {"op": "replace", "path": "/mode", "value": "enforce"},
        ],
        [
            {"op": "test", "path": "/policy_version", "value": 1},
            {"op": "test", "path": "/policy_version", "value": 1},
            {"op": "replace", "path": "/status", "value": "published"},
        ],
        [
            {"op": "test", "path": "/policy_version", "value": True},
            {"op": "test", "path": "/policy_digest", "value": "sha256:" + "a" * 64},
            {"op": "replace", "path": "/status", "value": "published"},
        ],
        [
            {"op": "test", "path": "/policy_version", "value": 1},
            {"op": "test", "path": "/policy_digest", "value": "md5:abc"},
            {"op": "replace", "path": "/status", "value": "published"},
        ],
        [
            {"op": "test", "path": "/policy_version", "value": 1},
            {"op": "test", "path": "/policy_digest", "value": "sha256:" + "a" * 64},
            {"op": "replace", "path": "/status", "value": "draft"},
        ],
        [
            {"op": "test", "path": "/policy_version", "value": 1},
            {"op": "test", "path": "/policy_digest", "value": "sha256:" + "a" * 64},
            {"op": "add", "path": "/status", "value": "published"},
        ],
    ],
)
def test_parse_publish_diff_refuses_every_other_grammar(operations: list[dict[str, Any]]) -> None:
    with pytest.raises(InvalidSchemaError) as info:
        parse_publish_diff({"format": "json_patch", "operations": operations})
    assert info.value.reason == "bad_publish_diff"


def test_a_diff_breaking_rfc6902_member_rules_is_refused_by_the_executor_check() -> None:
    diff = ProposedDiff.model_validate(
        {"format": "json_patch", "operations": [{"op": "remove", "path": "/mode", "value": "x"}]}
    )
    with pytest.raises(InvalidSchemaError) as info:
        parse_mode_change_diff(diff)
    assert info.value.reason == "invalid_diff"


async def test_mode_change_diff_round_trips_including_enforce() -> None:
    engine = await build_engine()
    outcome = await _publish(engine, policy_draft())
    binding = outcome.bindings[0].binding

    diff = mode_change_diff(binding, "enforce")
    validate_proposed_diff(diff)
    parsed = parse_mode_change_diff(diff_to_wire(diff))

    assert (parsed.current_mode, parsed.mode) == ("audit", "enforce")
    target = mode_change_target(binding)
    assert target.entity_type == "enforcement_binding"
    assert target.canonical_id == (
        f"commercial:acme:neurosphere:enforcement_binding:{binding.binding_id.root}"
    )
    with pytest.raises(InvalidSchemaError) as same:
        mode_change_diff(binding, "audit")
    assert same.value.reason == "mode_unchanged"


@pytest.mark.parametrize(
    "operations",
    [
        [{"op": "replace", "path": "/mode", "value": "enforce"}],
        [
            {"op": "test", "path": "/mode", "value": "audit"},
            {"op": "replace", "path": "/mode", "value": "block"},
        ],
        [
            {"op": "test", "path": "/mode", "value": "audit"},
            {"op": "replace", "path": "/state", "value": "applied"},
        ],
        [
            {"op": "test", "path": "/mode", "value": "audit"},
            {"op": "replace", "path": "/mode", "value": "audit"},
        ],
        [
            {"op": "test", "path": "/mode", "value": "audit"},
            {"op": "replace", "path": "/mode", "value": "enforce"},
            {"op": "replace", "path": "/target", "value": None},
        ],
    ],
)
def test_parse_mode_change_diff_refuses_every_other_grammar(
    operations: list[dict[str, Any]],
) -> None:
    with pytest.raises(InvalidSchemaError) as info:
        parse_mode_change_diff({"format": "json_patch", "operations": operations})
    assert info.value.reason in {"bad_mode_change_diff", "mode_unchanged"}


@pytest.mark.parametrize(
    ("current", "mode"),
    [
        (["audit"], "enforce"),
        ("audit", {"mode": "enforce"}),
        ({"a": 1}, ["enforce"]),
        (1, "enforce"),
    ],
)
def test_parse_mode_change_diff_refuses_non_string_modes(current: Any, mode: Any) -> None:
    """An unhashable ``/mode`` value is the parser's 400, never a TypeError (500)."""
    operations = [
        {"op": "test", "path": "/mode", "value": current},
        {"op": "replace", "path": "/mode", "value": mode},
    ]
    with pytest.raises(InvalidSchemaError) as info:
        parse_mode_change_diff({"format": "json_patch", "operations": operations})
    assert info.value.reason == "bad_mode_change_diff"
