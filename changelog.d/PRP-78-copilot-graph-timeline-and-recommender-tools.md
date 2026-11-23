### Added
- Copilot tools (PRP-78): `graph_query` (bounded structured graph read: depth 3, 100 nodes, 300
  edges, 50 start ids, `grants_access_to` excluded), `get_timeline` (changes, metric shifts and
  recommendations over 5 to 1440 minutes, 100 entries, `sections_omitted` for sections the caller
  cannot read) and `recommend_agent` (at most 5 domains). Each rechecks the caller's scope per
  call and writes one `copilot.tool_call` audit record (outcome allowed, refused or failed;
  arguments and rows never recorded).
- A `progress` SSE event on the message stream and a progress line in the copilot dock.
- Recorded demo model: `NS_COPILOT_MODE=recorded` (local only, `misconfigured` elsewhere) replays
  five scripted demo questions and answers extractively from real tool results, labelled
  synthetic in `GET /api/v1/copilot/status` and in the dock ("Recorded demo model, not AI").
  The demo profile turns it on (`NS_DEMO_COPILOT_MODE=recorded`); the demo check requires a ready,
  synthetic status and one cited answer. Runbook: `docs/runbooks/copilot.md`; the first real-model
  turn with the new tools is OPEN (PRP-64).

### Changed
- The demo settings seed no longer stores the placeholder `copilot` row when the demo copilot mode
  is `recorded`, and the demo check reports `switched_off` instead of `pending_prp_78` when an
  operator disables the demo copilot.
