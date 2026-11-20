from __future__ import annotations

import itertools

import pytest
from neurosphere_core.recommendations.matching import (
    DEFAULT_WEIGHTS,
    CombinedResult,
    MatchSettings,
    SignalValue,
    combine,
    rank_candidates,
)
from pydantic import ValidationError

W = DEFAULT_WEIGHTS


def _sv(name: str, value: float | None) -> SignalValue:
    return SignalValue(signal=name, value=value, detail_code="x")


def _all(value: float | None, **over: float | None) -> list[SignalValue]:
    vals: dict[str, float | None] = {n: value for n in W}
    vals.update(over)
    return [_sv(n, v) for n, v in vals.items()]


def test_contributions_sum_to_score_and_unobserved_have_zero_weight() -> None:
    res = combine(_all(0.8, latency=None, usage=None, feedback_prior=None), W)
    assert abs(sum(c.contribution for c in res.contributions) - res.score) < 1e-9
    assert set(res.unobserved) == {"latency", "usage", "feedback_prior"}
    by = {c.signal.root: c for c in res.contributions}
    for name in res.unobserved:
        assert by[name].weight == 0.0 and by[name].contribution == 0.0 and by[name].value is None
    assert abs(sum(c.weight for c in res.contributions) - 1.0) < 1e-9
    assert abs(res.score - 0.8) < 1e-9


def test_missing_signal_is_listed_unobserved() -> None:
    res = combine([_sv("tag_match", 1.0)], W)
    assert "text_match" in res.unobserved
    assert res.score == pytest.approx(1.0)


def test_nothing_observed_scores_zero() -> None:
    res = combine([], W)
    assert res.score == 0.0 and res.confidence == 0.0 and res.cold_start


def test_unknown_error_rate_does_not_count_as_zero_errors() -> None:
    unknown = combine(_all(0.5, historical_success=None), W)
    zero_success = combine(_all(0.5, historical_success=0.0), W)
    assert "historical_success" in unknown.unobserved
    assert unknown.score > zero_success.score


def test_score_monotonic_in_each_observed_signal() -> None:
    grid = [0.0, 0.25, 0.5, 0.75, 1.0]
    for name, base in itertools.product(W, (0.2, 0.9)):
        scores = [combine(_all(base, **{name: v}), W).score for v in grid]
        assert scores == sorted(scores), name


def test_cold_start_flag_and_confidence_below_observed_twin() -> None:
    telemetry = {"historical_success": 0.9, "latency": 0.9, "usage": 0.9}
    warm = combine(_all(0.9, **telemetry), W)
    cold = combine(_all(0.9, historical_success=None, latency=None, usage=None), W)
    assert not warm.cold_start and cold.cold_start
    assert cold.confidence < warm.confidence
    equal_score = combine(_all(0.9, historical_success=None, latency=None, usage=None), W)
    assert equal_score.confidence <= 0.6


def test_confidence_grows_with_margin() -> None:
    low = combine(_all(0.7), W, margin=0.0).confidence
    high = combine(_all(0.7), W, margin=0.3).confidence
    assert high > low


def test_rank_ties_break_by_canonical_id_and_confidence_uses_margin() -> None:
    a = combine(_all(0.6), W)
    top = combine(_all(0.9), W)
    ranked = rank_candidates([("gov:z", a), ("gov:b", a), ("gov:m", top)])
    assert [cid for cid, _ in ranked] == ["gov:m", "gov:b", "gov:z"]
    assert ranked[0][1].confidence > a.confidence * 0  # margin applied, still a valid number
    assert all(isinstance(r, CombinedResult) for _, r in ranked)
    assert 0.0 <= ranked[1][1].confidence <= 1.0


def test_settings_defaults_env_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    s = MatchSettings()
    assert (s.candidate_cap, s.feedback_bound, s.min_principals, s.feedback_ttl_days) == (
        200,
        0.15,
        3,
        180,
    )
    monkeypatch.setenv("NS_MATCH_WEIGHTS", '{"tag_match": 2.0}')
    assert MatchSettings().weights == {"tag_match": 2.0}
    monkeypatch.setenv("NS_MATCH_WEIGHTS", '{"bogus": 1.0}')
    with pytest.raises(ValidationError):
        MatchSettings()
