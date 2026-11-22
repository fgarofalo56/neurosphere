"""PRP-78 item 3: the ``recommend_agent`` tool (offline; the matcher is a local fake)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from neurosphere_contracts.recommendations.v1.agent_match_request import AgentMatchRequest
from neurosphere_contracts.recommendations.v1.agent_match_response import AgentMatchResponse
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.copilot.tools import (
    ScopeArgumentRefusedError,
    ToolPermissionError,
    ToolRegistry,
)
from neurosphere_core.copilot.tools.matching import (
    MAX_MATCH_DOMAINS,
    TOOL_NAME,
    RecommendAgentArgs,
    recommend_agent_spec,
)
from neurosphere_core.errors import ForbiddenError, InvalidSchemaError, NotFoundError
from neurosphere_core.scope import IdentityScope
from pydantic import ValidationError

NOW = datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC)


def _dom(name: str) -> str:
    return f"commercial:contoso:catalog:domain:{name}"


def _scope(readable: list[str], allowed: list[str] | None = None) -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": "contoso",
            "principal": {
                "principal_id": "commercial:contoso:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [{"role": "viewer", "domain_ids": readable}],
            "allowed_domains": allowed if allowed is not None else readable,
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-20T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"match-scope").hexdigest(),
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


def _candidate(name: str, score: float, rank: int = 1) -> dict[str, Any]:
    return {
        "rank": rank,
        "entity_id": f"commercial:contoso:foundry:agent:{name}",
        "entity_type": "agent",
        "display_name": f"Agent {name}",
        "lifecycle_status": "active",
        "score": score,
        "signals": [
            {
                "signal": "capability_match",
                "value": 1.0,
                "weight": 0.4,
                "contribution": 0.4,
                "detail_code": None,
                "evidence_ids": [],
            }
        ],
        "matched_capabilities": [],
        "matched_tags": [],
        "relations": [],
        "evidence_ids": [],
    }


def _response(domain: str, cands: list[dict[str, Any]], *, truncated: bool = False) -> Any:
    return AgentMatchResponse.model_validate(
        {
            "schema_version": "1.0.0",
            "match_id": "match-0001",
            "domain_id": domain,
            "generated_at": "2026-11-19T10:05:00Z",
            "ranker": {"ranker_id": "weighted-signals", "ranker_version": "1.0.0"},
            "cold_start": False,
            "signals_unavailable": [],
            "candidates": cands,
            "truncated": truncated,
            "partial_reason": "limit" if truncated else None,
        }
    )


@dataclass
class FakeMatcher:
    by_domain: dict[str, list[dict[str, Any]]] = field(default_factory=dict[str, list[Any]])
    errors: dict[str, Exception] = field(default_factory=dict[str, Exception])
    leak_domain: dict[str, str] = field(default_factory=dict[str, str])
    calls: list[str] = field(default_factory=list[str])

    async def match(
        self, scope: IdentityScope, domain: str, request: AgentMatchRequest
    ) -> AgentMatchResponse:
        self.calls.append(domain)
        if domain in self.errors:
            raise self.errors[domain]
        return _response(self.leak_domain.get(domain, domain), self.by_domain.get(domain, []))


def _registry(matcher: FakeMatcher, **kwargs: Any) -> ToolRegistry:
    return ToolRegistry([recommend_agent_spec(matcher=matcher, clock=lambda: NOW, **kwargs)])


def _args(**extra: Any) -> dict[str, Any]:
    request = {"schema_version": "1.0.0", "task_text": "summarize contracts", **extra}
    return {"request": request}


async def test_fan_out_capped_and_truncation_flagged() -> None:
    domains = [_dom(f"d{i}") for i in range(7)]
    matcher = FakeMatcher()
    result = await _registry(matcher).invoke(TOOL_NAME, _args(), _scope(domains))
    assert len(matcher.calls) == MAX_MATCH_DOMAINS == 5
    assert result.truncated is True


async def test_no_truncation_when_within_cap() -> None:
    domains = [_dom("a"), _dom("b")]
    matcher = FakeMatcher(by_domain={_dom("a"): [_candidate("x", 0.5)]})
    result = await _registry(matcher).invoke(TOOL_NAME, _args(), _scope(domains))
    assert result.truncated is False
    assert sorted(matcher.calls) == domains


async def test_merge_by_score_with_stable_tiebreak_and_limit() -> None:
    a, b = _dom("a"), _dom("b")
    matcher = FakeMatcher(
        by_domain={
            a: [_candidate("zeta", 0.5), _candidate("alpha", 0.9, 2)],
            b: [_candidate("beta", 0.5), _candidate("gamma", 0.7, 2)],
        }
    )
    result = await _registry(matcher).invoke(TOOL_NAME, _args(limit=3), _scope([a, b]))
    ids = [r.record_id.rsplit(":", 1)[-1] for r in result.records]
    assert ids == ["alpha", "gamma", "beta"]
    assert result.truncated is True


async def test_citation_per_candidate_with_score_signals_and_domain() -> None:
    a = _dom("a")
    matcher = FakeMatcher(by_domain={a: [_candidate("x", 0.8)]})
    result = await _registry(matcher).invoke(TOOL_NAME, _args(), _scope([a]))
    assert [c.record_id for c in result.citations] == [r.record_id for r in result.records]
    record = result.records[0]
    assert record.record_id == "commercial:contoso:foundry:agent:x"
    assert record.data["score"] == 0.8
    assert record.data["domain_id"] == a
    assert isinstance(record.data["signals"], list) and record.data["signals"]
    assert result.citations[0].as_of == "2026-11-19T10:05:00Z"
    assert result.citations[0].freshness == "fresh"


async def test_unreadable_domain_never_queried_and_leaked_candidates_dropped() -> None:
    a, secret = _dom("a"), _dom("secret")
    matcher = FakeMatcher(
        by_domain={a: [_candidate("ok", 0.4)], secret: [_candidate("leak", 0.99)]},
        leak_domain={a: secret},
    )
    # The scope allows both domains but holds data.read only on a.
    scope = _scope([a], allowed=[a, secret])
    result = await _registry(matcher).invoke(TOOL_NAME, _args(), scope)
    assert matcher.calls == [a]
    # The port answered for a domain other than the one asked: dropped.
    assert result.records == ()


async def test_preferred_domains_narrow_but_never_widen() -> None:
    a, b, other = _dom("a"), _dom("b"), _dom("other")
    matcher = FakeMatcher()
    registry = _registry(matcher, preferred_domains=lambda _s: [b, other])
    await registry.invoke(TOOL_NAME, _args(), _scope([a, b]))
    assert matcher.calls == [b]


async def test_no_readable_domain_is_permission_error() -> None:
    matcher = FakeMatcher()
    with pytest.raises(ToolPermissionError):
        await _registry(matcher).invoke(
            TOOL_NAME, _args(), _scope([_dom("a")], allowed=[_dom("b")])
        )
    assert matcher.calls == []


async def test_per_domain_forbidden_and_not_found_are_skipped() -> None:
    a, b, c = _dom("a"), _dom("b"), _dom("c")
    matcher = FakeMatcher(
        by_domain={c: [_candidate("kept", 0.6)]},
        errors={a: ForbiddenError("no"), b: NotFoundError("gone")},
    )
    result = await _registry(matcher).invoke(TOOL_NAME, _args(), _scope([a, b, c]))
    assert [r.record_id.rsplit(":", 1)[-1] for r in result.records] == ["kept"]


async def test_other_matcher_errors_propagate() -> None:
    a = _dom("a")
    matcher = FakeMatcher(errors={a: RuntimeError("boom")})
    with pytest.raises(RuntimeError):
        await _registry(matcher).invoke(TOOL_NAME, _args(), _scope([a]))


@pytest.mark.parametrize("key", ["domain_id", "customer_id"])
async def test_scope_key_inside_request_refused_by_contract(key: str) -> None:
    a = _dom("a")
    matcher = FakeMatcher()
    with pytest.raises(InvalidSchemaError):
        await _registry(matcher).invoke(TOOL_NAME, _args(**{key: a}), _scope([a]))
    assert matcher.calls == []
    with pytest.raises(ValidationError):
        RecommendAgentArgs.model_validate(_args(**{key: a}))


@pytest.mark.parametrize("key", ["domain_id", "domains", "scope", "customer_id"])
async def test_top_level_scope_key_refused(key: str) -> None:
    a = _dom("a")
    matcher = FakeMatcher()
    raw = {**_args(), key: a}
    with pytest.raises(ScopeArgumentRefusedError):
        await _registry(matcher).invoke(TOOL_NAME, raw, _scope([a]))
    assert matcher.calls == []


def test_no_budget_requested() -> None:
    assert RecommendAgentArgs.model_validate(_args()).requested_budget() is None
