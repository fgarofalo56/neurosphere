"""Agent match latency at 10,000 agents (PRP-72 item 5): MEASURED, never asserted.

What this is: wall-clock p50/p95/max of ``AgentMatcher.match_detailed`` over a fixed task set
against the sandbox ``custom`` profile with 10,000 agents (tags, capabilities and descriptive text
added locally), the in-memory catalog repository and the fixture BM25 search provider, with the
default candidate cap. Warm-up runs are excluded. The result is printed and written to
``temp/agent_match/p95.json`` (gitignored), labelled with the backend, the agent count, the
candidate cap and a statement that it is not a live claim.

What this is not: a performance claim for Azure AI Search or Cosmos NoSQL. The test fails only on
correctness (every ranked candidate is in the caller's scope, every task ranks something), never
on a latency threshold.
"""

from __future__ import annotations

import asyncio

from .harness import check_and_record, measure


def test_match_latency_at_10k_agents_is_measured_and_recorded() -> None:
    check_and_record(asyncio.run(measure()))
