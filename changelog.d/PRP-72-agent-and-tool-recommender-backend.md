### Added
- Agent and tool matching (PRP-72): `POST /api/v1/recommendations/domains/{domain}/match` takes a
  task description and returns a ranked list of candidate agents and tools from the caller's
  scope. Each candidate carries a relative 0-1 score, a confidence value that is not a
  probability, and the contribution of every signal: capability and tag match, lexical
  relevance, graph proximity to named context entities, and historical success, latency and
  usage from the per-agent aggregates. Candidates without telemetry are flagged as cold start
  and their confidence is capped.
- Match feedback: `POST .../match/feedback` records an accept or reject per principal, match
  and candidate. Feedback from at least three distinct principals moves later rankings for
  similar tasks by a bounded amount (default 0.15 of score) that is shown in the explanation.
- `GET .../match/metrics` returns match, feedback, accept and reject counts and the acceptance
  rate for a window. The rate is null when there is no feedback.
- Container `recommendation_feedback` with a per-item TTL. It stores normalized task tokens and
  the principal pseudonym, never the task text.
- Settings `NS_MATCH_WEIGHTS`, `NS_MATCH_CANDIDATE_CAP`, `NS_MATCH_FEEDBACK_BOUND`,
  `NS_MATCH_MIN_PRINCIPALS` and `NS_MATCH_FEEDBACK_TTL_DAYS`, the optional `agent_matcher`
  readiness component, and the runbook `docs/runbooks/agent-match.md`.
- A 10,000-agent in-memory latency profile under `tests/load/agent_match`. It measures and
  records; it is not a claim about Azure AI Search or Cosmos.

### Changed
- Matching is a recommendation only. It is lexical, uses untuned default weights, and never
  invokes or changes an agent. Tools without a domain are not candidates.
