"""Usage summaries over archived cost documents whose token counts are explicit nulls.

Found on the seeded demo stack (PRP-71): the archive keeps an unreported count as ``null``, and
``int(None)`` crashed the recommendations role on every tick, so it restarted forever.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from neurosphere_workers.recommendations.pipeline import summarize_usage_docs
from neurosphere_workers.recommendations.tests.support import make_scope

DOMAIN = "commercial:synthco:sandbox:domain:finance"
AGENT = "commercial:synthco:sandbox:agent:invoice-intake-assistant"


@dataclass
class _Day:
    covered: bool = True


@dataclass
class _Series:
    agent_id: str = AGENT
    domain_id: str = DOMAIN
    owner_id: str | None = None
    days: list[_Day] = field(default_factory=lambda: [_Day()])


class _Source:
    def series(self, **_: Any) -> list[_Series]:
        return [_Series()]


def _doc(n: int, tokens: Any) -> dict[str, Any]:
    return {
        "kind": "estimated",
        "cost_id": f"cost-{n}",
        "dedupe_key": f"synthco/evt-{n}",
        "cloud": "commercial",
        "customer_id": "synthco",
        "canonical_agent_id": AGENT,
        "provider": "azure-openai",
        "model": "gpt-demo",
        "model_version": None,
        "token_breakdown": tokens,
    }


def test_null_token_counts_add_nothing_and_do_not_crash() -> None:
    docs = [
        _doc(1, {"input": 100, "output": 20, "cached": None, "reasoning": None}),
        _doc(2, {"input": 50, "output": None, "cached": 5}),
        _doc(3, {"input": None, "output": 0}),
        _doc(4, None),
    ]
    summaries = summarize_usage_docs(
        docs,
        scope=make_scope([DOMAIN]),
        window=(date(2026, 10, 1), date(2026, 10, 8)),
        source=_Source(),  # type: ignore[arg-type]
    )
    assert len(summaries) == 1
    tokens = summaries[0].tokens
    assert (tokens.input, tokens.output, tokens.cached) == (150, 20, 5)
