### Added
- Page `/recommendations/find` ("Find an agent", Quality navigation, PRP-75): type a task and get
  the ranked agents and tools of the selected domain from the PRP-72 matcher, each with its score,
  relative confidence, cold-start label and a per-signal explanation table (observed or "no
  telemetry yet", weight, contribution), the related entities behind graph proximity, and links to
  the catalog entity and the map.
- Accept and Reject on every candidate post to the match feedback route; the decision shows only
  after the API confirms it, can be changed, and a failure keeps the previous decision.
- A metrics strip with matches, accepts, rejects and the acceptance rate ("no feedback yet" when
  there is none, never 0 percent), stated as an outcome to observe rather than a target met, and a
  metadata-completeness tile that shows "not available" until PRP-76's endpoint exists.
- Partial, cold-start, empty and error states; result count and partial state are announced in a
  live region. The task text stays in page memory only.
- Runbook `docs/runbooks/agent-match-ui.md`; mock API module
  `frontend/tests/mock-api/features/agent-match.ts`.
