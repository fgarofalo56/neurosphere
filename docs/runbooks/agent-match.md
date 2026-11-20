# Agent and tool matching

The matcher takes a task description and returns a ranked list of candidate agents and tools from
the caller's scope, each with a score, a confidence value and the signals behind the rank. It is a
recommendation only: it never invokes, changes or deploys an agent.

Status: this is a transparent weighted-signal model, not a trained ranker and not an LLM. The
default weights are a starting point and have not been tuned against real usage. A score is a
relative 0-1 value and a confidence is not a probability. NeuroSphere is not FedRAMP authorized;
the authorizing official decides.

## Routes

All three routes sit under `/api/v1/recommendations/domains/{domain}/match` and need `data.read`
on the path domain. A caller without it gets 403 and a denial record.

| Route | Purpose | Success |
|---|---|---|
| `POST` (no suffix) | Rank candidates for a task | 200 |
| `POST /feedback` | Record `accepted` or `rejected` for a candidate of a match the caller received | 202 |
| `GET /metrics?since&until` | Counts and acceptance rate for a window (default 30 days, at most 366) | 200 |

The match response carries the contract `AgentMatchResponse` under `match`, plus one assessment
per candidate (`confidence`, `cold_start`) and a `confidence_note`.

| Status | Code | Meaning |
|---|---|---|
| 403 | `context_entity_out_of_scope` | A context entity id is outside the caller's scope. It is refused, never ignored |
| 404 | `match_not_found` | Feedback for a match that is unknown, expired or was shown to someone else |
| 409 | `capability_unavailable` | Search or the catalog is not composed; the body names `search_unavailable` or `catalog_unavailable` |
| 422 | `candidate_not_in_match` | Feedback for a candidate that match did not return |
| 422 | `invalid_window` | Metrics window is reversed or longer than 366 days |
| 503 | `recommendations_unconfigured` | The matcher is not composed at all |

## How a candidate is scored

The candidate pool is every domain in the caller's scope. The path domain is the authorization
target. Scope is applied before ranking, so an out-of-scope entity never appears, is never counted
and never influences a score.

| Signal | Default weight | What it measures |
|---|---|---|
| `capability_match` | 0.25 | Overlap between the request's required capabilities and the candidate's |
| `tag_match` | 0.15 | Exact tag match is 1, otherwise the token overlap fraction |
| `text_match` | 0.20 | Lexical (BM25) relevance from the search port, normalized by the top hit |
| `graph_proximity` | 0.10 | 1.0 at 0 or 1 hop from a context entity, 0.5 at 2 hops; the edge type and hop count are returned |
| `historical_success` | 0.15 | 1 minus the error rate from the per-agent aggregates |
| `latency` | 0.05 | p95 against the candidate pool median (0.5 at the median) |
| `usage` | 0.05 | Event count, log-scaled |

Each signal is returned with its value, weight, contribution and a detail code. Contributions sum
to the score. A signal with no data is unobserved: its value is null, it carries no weight and the
remaining weights are renormalized. An unknown error rate is never treated as zero errors.

### Cold start

A candidate with no aggregate points is flagged `cold_start`. Its telemetry signals are
unobserved, and its confidence is multiplied by 0.7 and capped at 0.6, so it always sits below an
otherwise equal candidate with observed telemetry. Tools have no subject aggregates, so every tool
is cold start today.

### Feedback

- One decision per principal, match and candidate. A later decision replaces the earlier one.
- Feedback applies to later tasks whose normalized tokens are similar (Jaccard at least 0.5).
- Below `NS_MATCH_MIN_PRINCIPALS` distinct principals the prior is 0 and is reported as
  `feedback_insufficient_evidence`. One person cannot move a ranking alone.
- The prior is a signed adjustment added on top of the combined score, never more than
  `NS_MATCH_FEEDBACK_BOUND` in either direction, and it is shown as its own contribution.

## What is stored

Container `recommendation_feedback` holds `match` and `feedback` documents with a per-item TTL.
They contain normalized task tokens (at most 32, stop words removed), the principal pseudonym,
ids, the decision, rank and score at decision time and timestamps. The task text and the clear
principal identifier are never stored and never logged.

## Settings

| Variable | Default | Effect |
|---|---|---|
| `NS_MATCH_WEIGHTS` | table above | JSON object of signal weights. The response always carries the weights used |
| `NS_MATCH_CANDIDATE_CAP` | 200 | Largest candidate pool ranked per call |
| `NS_MATCH_FEEDBACK_BOUND` | 0.15 | Largest score movement feedback can cause |
| `NS_MATCH_MIN_PRINCIPALS` | 3 | Distinct principals needed before feedback counts |
| `NS_MATCH_FEEDBACK_TTL_DAYS` | 180 | Lifetime of stored match and feedback documents |

The `feedback_prior` entry in `NS_MATCH_WEIGHTS` has no effect. Feedback is bounded by
`NS_MATCH_FEEDBACK_BOUND` only.

## Partial results

`truncated` and `partial_reason` say when a budget stopped the work. The contract allows two
reasons: `limit` (the candidate cap, the search result limit or the 20-domain telemetry cap) and
`timeout_ms` (the search timeout or the total time budget). `signals_unavailable` lists signals
that were unobserved for every returned candidate.

## Readiness

`agent_matcher` is an optional component. When search or the catalog is unavailable it reports
`disabled` in `/readyz`. The readiness registry carries a reason only for failed components, so
the reason code appears in the route's 409 body, not in `/readyz`.

## Known limits and what is not claimed

- Tools without a `domain_id` are not indexed by search, so they are never candidates and the
  response does not say that any were skipped.
- Matching is lexical. There are no embeddings and no semantic ranking.
- Latency has been measured only on the in-memory repository with the fixture search provider
  (`tests/load/agent_match_latency`, result in `temp/agent_match/p95.json`). No latency is claimed for
  Azure AI Search or Cosmos.
- The acceptance rate is instrumented here. Whether it reaches the 60 percent target is an
  adoption outcome that this feature cannot claim.
- Matching never crosses customers or clouds.
