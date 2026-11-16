### Added
- PRP-49: per-agent and per-model aggregate series. The aggregates worker rolls `model_call` events up per hour and day into a new `subject` metric (`SubjectPoint`, series keys `agent:<id>` and `model:<provider>/<model>`), and the aggregate stores gain a bounded batch read (`SubjectMetricsReader.latest_subject_points`), PR #301 (#243).
- PRP-49: agent and model nodes on `/map` now carry `frequency`, `latency_p95_ms`, `tokens` and `health` from the latest subject point; unknown stays `null` and `unknown`. The realtime delta source also pushes changed agent and model nodes.

### Changed
- PRP-49: `replace_bucket` skips unchanged documents, and the map client merges a metrics-only delta without overwriting labels; deltas for unknown agent, model and source ids are ignored.
