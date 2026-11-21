# Find an agent (page)

PRP-75. The page `/recommendations/find` ("Find an agent", Quality navigation, next to
Recommendations) puts a person in front of the agent and tool matcher described in
[Agent and tool matching](agent-match.md). You type a task, get a ranked list of agents and tools
from the selected domain, read why each one was ranked, and accept or reject it. It is a
recommendation only: the page never invokes, changes or deploys the chosen agent.

| Page action | Route | Permission |
|---|---|---|
| Submit a task | `POST /api/v1/recommendations/domains/{domain}/match` | `data.read` |
| Accept or reject a candidate | `POST /api/v1/recommendations/domains/{domain}/match/feedback` | `data.read` |
| Metrics strip | `GET /api/v1/recommendations/domains/{domain}/match/metrics` | `data.read` |
| Completeness tile | `GET /api/v1/catalog/completeness` (PRP-76, optional) | `data.read` |

The match always runs against the domain in the shared domain switcher. There is no control to
search other domains; switch domain to search there.

## Reading a candidate card

Each card shows the name, the kind (agent or tool), the `score`, the `confidence` and an
explanation table.

- `score` is a relative 0-1 weighted score. It ranks candidates within one answer; it is not a
  probability and is not comparable across answers.
- `confidence` is also relative. The API derives it from the score, the share of signal weight
  that was observed and the margin to the next candidate (see the `confidence_note` the API
  returns). It is not a probability that the agent will do the task well.
- The explanation table has one row per signal: its name, whether it was observed, its weight and
  its contribution to the score. An unobserved signal says "no telemetry yet" in text and never
  shows 0, because an unknown value is not a bad value.
- A candidate with no observed telemetry carries the cold-start label. Its confidence is capped by
  the API, so it sits below a comparable candidate with history.
- When the graph-proximity signal contributed, the card lists the related entities that linked
  the candidate to the task.
- "Open in catalog" goes to `/catalog/entity` for the candidate; "Show on map" opens the map on
  it.

## Partial and empty answers

- A banner says the results are partial when the API reports `truncated` or a `partial_reason`
  (`limit`: more candidates matched than were returned; `timeout_ms`: the scan stopped at its
  time bound).
- When the answer is cold start or names `signals_unavailable`, the page lists the signals that
  could not be computed.
- No candidates gives an empty state that suggests broader wording or another domain.
- A 403 or 503 (including `capability_unavailable`) shows the shared error state with the reason
  code.

The result count and the partial state are announced through a live region.

## Accepting and rejecting

Accept and Reject post to the feedback route once. The button only changes after the API answers
202, because feedback adjusts the shared ranking for everyone in the domain and a silent failure
would mislead. A failure keeps the previous decision and shows the error. You can change a
decision; the later one replaces the earlier one. Focus stays on the card.

There is no route that reads a past decision back, and the task text is not kept, so a reload
clears the form and the results. A decision is visible after a reload through the metrics strip.

## The metrics strip

The strip shows, for the API's default window, the number of matches, accepts, rejects and the
acceptance rate (`accepts / (accepts + rejects)`). With no feedback the rate reads "no feedback
yet", never 0 percent.

The original product goal is an acceptance rate above 60 percent. The strip shows the observed
rate; it is an outcome to watch, not a target the product has met.

The completeness tile reads PRP-76's metadata-completeness endpoint. Until that endpoint is
deployed it shows "not available" and nothing else on the page is affected.

## Privacy

The task text lives in the page's memory only. It is not written to the URL, local storage, logs
or analytics, and the page does not restore it after a reload. The API audits the match without
the task text (see the backend runbook).

## Known limits and what is not claimed

- The ranking is a transparent weighted-signal model, not a trained ranker or an LLM.
- The acceptance rate is observed, not claimed.
- The hosted deployment of this page is PRP-82; until then it runs on the mock API and the local
  stack only.
- Accessibility is tested with axe in light, dark and high-contrast themes; a sign-off by a
  person is still open project-wide.
