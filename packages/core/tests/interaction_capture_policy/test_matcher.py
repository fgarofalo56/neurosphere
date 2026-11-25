"""CaptureMatcher: every gate in order, each off reason distinct; sampling and rate limit."""

from __future__ import annotations

import pytest
from neurosphere_contracts.admin.v1.system_setting import SystemSetting
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.interactions.policy import (
    OFF_REASONS,
    CaptureMatch,
    CaptureMatcher,
    CapturePolicy,
    CaptureRateLimiter,
    capture_setting_enabled,
    is_sampled,
    parse_capture_policy,
)
from neurosphere_core.interactions.policy_store import (
    InMemoryCapturePolicyStore,
    StoredCapturePolicy,
)
from neurosphere_core.lifecycle.policy import UNSET

from .policy_helpers import (
    CUSTOMER,
    DOMAIN,
    OTHER_DOMAIN,
    SOURCE,
    active_doc,
    policy_doc,
    retention,
)


def _matcher(*docs: dict[str, object], setting: bool = True, opt_in: bool = True) -> CaptureMatcher:
    return CaptureMatcher(
        [parse_capture_policy(d) for d in docs],
        setting_enabled=setting,
        retention=retention(opt_in=opt_in),
    )


def test_off_reasons_are_distinct_and_complete() -> None:
    assert OFF_REASONS == (
        "setting_off",
        "retention_not_enabled",
        "no_policy",
        "not_approved",
        "source_mismatch",
        "domain_missing",
        "domain_mismatch",
        "not_sampled",
    )
    assert len(set(OFF_REASONS)) == len(OFF_REASONS)


@pytest.mark.parametrize(
    ("matcher_kwargs", "source", "domain", "expected"),
    [
        ({"setting": False}, SOURCE, DOMAIN, "setting_off"),
        ({"opt_in": False}, SOURCE, DOMAIN, "retention_not_enabled"),
    ],
)
def test_global_gates(
    matcher_kwargs: dict[str, bool], source: str, domain: str, expected: str
) -> None:
    matcher = _matcher(active_doc(), **matcher_kwargs)
    result = matcher.evaluate(source, domain, "evt-1")
    assert result.off_reason == expected
    assert result.decision is None
    assert matcher.match(source, domain, "evt-1") is None


def test_retention_without_content_rule_is_off() -> None:
    matcher = CaptureMatcher(
        [parse_capture_policy(active_doc())],
        setting_enabled=True,
        retention=retention(content_rule=False),
    )
    assert matcher.evaluate(SOURCE, DOMAIN, "evt-1").off_reason == "retention_not_enabled"


def test_unset_retention_is_off() -> None:
    matcher = CaptureMatcher(
        [parse_capture_policy(active_doc())], setting_enabled=True, retention=UNSET
    )
    assert matcher.status() == "retention_not_enabled"
    none_matcher = CaptureMatcher(
        [parse_capture_policy(active_doc())], setting_enabled=True, retention=None
    )
    assert none_matcher.status() == "retention_not_enabled"


def test_no_policy() -> None:
    matcher = _matcher()
    assert matcher.status() == "no_policy"
    assert matcher.evaluate(SOURCE, DOMAIN, "evt-1").off_reason == "no_policy"


@pytest.mark.parametrize("state", ["proposed", "suspended", "retired"])
def test_not_active_is_not_approved(state: str) -> None:
    matcher = _matcher(policy_doc(state=state))
    assert matcher.evaluate(SOURCE, DOMAIN, "evt-1").off_reason == "not_approved"


def test_source_domain_gates_in_order() -> None:
    matcher = _matcher(active_doc())
    assert matcher.status() is None
    assert matcher.evaluate("other-source", DOMAIN, "e").off_reason == "source_mismatch"
    # source mismatch is reported before a missing domain
    assert matcher.evaluate("other-source", None, "e").off_reason == "source_mismatch"
    assert matcher.evaluate(SOURCE, None, "e").off_reason == "domain_missing"
    assert matcher.evaluate(SOURCE, "", "e").off_reason == "domain_missing"
    assert matcher.evaluate(SOURCE, OTHER_DOMAIN, "e").off_reason == "domain_mismatch"


def test_match_returns_decision() -> None:
    matcher = _matcher(active_doc())
    decision = matcher.match(SOURCE, DOMAIN, "evt-1")
    assert decision is not None
    assert decision.capture_policy_id == "support-capture"
    assert decision.capture_policy_version == 1
    assert decision.max_per_minute == 120
    assert isinstance(decision.policy, CapturePolicy)


def test_several_policies_pick_by_domain_deterministically() -> None:
    sales = active_doc(capture_policy_id="sales-capture", domain_id=OTHER_DOMAIN)
    matcher = _matcher(active_doc(), sales, policy_doc(capture_policy_id="aaa-draft"))
    first = matcher.match(SOURCE, OTHER_DOMAIN, "e")
    second = matcher.match(SOURCE, DOMAIN, "e")
    assert first is not None
    assert second is not None
    assert first.capture_policy_id == "sales-capture"
    assert second.capture_policy_id == "support-capture"


def test_sampling_is_deterministic_per_event() -> None:
    matcher = _matcher(active_doc(sampling={"rate": 0.5, "max_per_minute": 6000}))
    ids = [f"evt-{i}" for i in range(400)]
    first = [matcher.evaluate(SOURCE, DOMAIN, e).captured for e in ids]
    again = [matcher.evaluate(SOURCE, DOMAIN, e).captured for e in ids]
    assert first == again
    kept = sum(first)
    assert 120 < kept < 280  # roughly half
    skipped = [e for e, c in zip(ids, first, strict=True) if not c]
    assert matcher.evaluate(SOURCE, DOMAIN, skipped[0]).off_reason == "not_sampled"


def test_is_sampled_bounds() -> None:
    assert is_sampled("anything", 1.0) is True
    assert is_sampled("anything", 0.0) is False
    assert is_sampled("x", 0.3) == is_sampled("x", 0.3)


def test_capture_match_requires_exactly_one() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        CaptureMatch()


async def test_from_store_snapshot_and_switch_off_reads_nothing() -> None:
    store = InMemoryCapturePolicyStore()
    await store.create(parse_capture_policy(active_doc()))
    matcher = await CaptureMatcher.from_store(
        store, setting_enabled=True, retention=retention(), customer_id=CUSTOMER
    )
    assert matcher.match(SOURCE, DOMAIN, "e") is not None

    class ExplodingStore(InMemoryCapturePolicyStore):
        async def list(
            self, *, customer_id: str | None = None, limit: int = 100
        ) -> list[StoredCapturePolicy]:
            del customer_id, limit
            raise AssertionError("must not read while the switch is off")

    off = await CaptureMatcher.from_store(
        ExplodingStore(), setting_enabled=False, retention=retention()
    )
    assert off.status() == "setting_off"


def _setting(enabled: bool, *, body: bool = True) -> SystemSetting:
    doc: dict[str, object] = {
        "schema_version": "1.0.0",
        "setting_key": "interaction_capture",
        "enabled": enabled,
    }
    if body:
        doc["interaction_capture"] = {
            "kek_provider": "local_development",
            "kek_uri": None,
            "content_storage_account_resource_id": (
                "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-ns"
                "/providers/Microsoft.Storage/storageAccounts/stnstest"
            ),
            "content_container": "interaction-content",
            "credential": {"kind": "managed_identity", "managed_identity_client_id": None},
        }
    return SystemSetting.model_validate(doc)


def test_capture_setting_enabled() -> None:
    assert capture_setting_enabled(None) is False
    assert capture_setting_enabled(_setting(False)) is False
    assert capture_setting_enabled(_setting(True)) is True
    assert capture_setting_enabled(_setting(True, body=False)) is False


# --- runtime policy rules ------------------------------------------------------------------------


def test_active_without_approval_is_invalid() -> None:
    with pytest.raises(InvalidSchemaError) as info:
        parse_capture_policy(policy_doc(state="active", approved_intent_id=None))
    assert info.value.reason == "capture_policy_invalid"


def test_credential_category_cannot_be_kept() -> None:
    with pytest.raises(InvalidSchemaError):
        parse_capture_policy(active_doc(kept_categories=["jwt"]))


def test_domain_must_belong_to_policy_customer() -> None:
    with pytest.raises(InvalidSchemaError):
        parse_capture_policy(active_doc(domain_id="commercial:fabrikam:neurosphere:domain:x"))


def test_duplicate_parts_rejected() -> None:
    with pytest.raises(InvalidSchemaError):
        parse_capture_policy(active_doc(parts=["prompt", "prompt"]))


def test_invalid_errors_carry_no_values() -> None:
    canary = "NSCANARY-display"
    with pytest.raises(InvalidSchemaError) as info:
        parse_capture_policy(active_doc(sampling={"rate": 2.0, "max_per_minute": 1}, x=canary))
    rendered = str(info.value) + repr(info.value.errors and [e.detail for e in info.value.errors])
    assert canary not in rendered
    assert "2.0" not in rendered


# --- rate limiter --------------------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_token_bucket_per_policy() -> None:
    clock = _Clock()
    limiter = CaptureRateLimiter(clock=clock)
    granted = [limiter.try_acquire("p1", 3) for _ in range(5)]
    assert granted == [True, True, True, False, False]
    assert limiter.try_acquire("p2", 3) is True  # independent bucket
    clock.now += 20.0  # 3 per minute -> one token per 20 s
    assert limiter.try_acquire("p1", 3) is True
    assert limiter.try_acquire("p1", 3) is False
    clock.now += 600.0  # refill caps at capacity
    assert [limiter.try_acquire("p1", 3) for _ in range(4)] == [True, True, True, False]


def test_token_bucket_evicts_oldest() -> None:
    limiter = CaptureRateLimiter(clock=_Clock(), max_buckets=2)
    assert limiter.try_acquire("a", 1) is True
    assert limiter.try_acquire("b", 1) is True
    assert limiter.try_acquire("c", 1) is True  # evicts "a"
    assert limiter.try_acquire("a", 1) is True  # fresh bucket
    assert limiter.try_acquire("c", 1) is False


def test_token_bucket_for_decision() -> None:
    matcher = _matcher(active_doc(sampling={"rate": 1.0, "max_per_minute": 1}))
    decision = matcher.match(SOURCE, DOMAIN, "e")
    assert decision is not None
    limiter = CaptureRateLimiter(clock=_Clock())
    assert limiter.try_acquire_for(decision) is True
    assert limiter.try_acquire_for(decision) is False
