# Hot aggregates worker (PRP-14 item 1)

Materializes 90-day rolling aggregates per customer and domain from the PRP-07 outbox (sink
`aggregates`, its own per-sink checkpoint). Aggregates are projections: they are rebuildable by
rewinding the sink checkpoint, and the worker has no dependency on `neurosphere_core/analytics`,
so they keep updating and stay readable while the batch analytics backend is delayed or down.

Documents, models and the read API live in `neurosphere_core.aggregates` (the API imports only
that package, never this one and never the ledger).

## Grains and window

| Grain | Bucket start (UTC) | Materialized for |
|-------|--------------------|------------------|
| `day` | `YYYY-MM-DDT00:00:00Z` | 90 whole UTC days ending today (`WINDOW_DAYS`) |
| `hour` | `YYYY-MM-DDTHH:00:00Z` | 14 whole UTC days ending today (`HOUR_RETENTION_DAYS`); reads over a wider hour window are refused |

A subject whose time is before the window start is dropped (and an existing contribution of it
is removed). `AggregateProjection.prune(customer_id)` deletes data that has since left the window.

## Rollup keys

Document id = hash(customer, domain, metric, grain, bucket start, series key). Partition key
`/customer_id`. Domain `_unassigned` holds subjects with no `domain_id`.

| Metric | Series key | Source | Value fields |
|--------|-----------|--------|--------------|
| `cost` | `estimated:<CUR>`, `invoiced:<CUR>` | ledger entries | `amount` (sum of known), `entry_count`, `known_count`, `price_versions[{id, effective_date}]` |
| `latency` | `latency` | `model_call` spans | `p50_ms`, `p95_ms`, `p99_ms` (nearest rank over known durations), `sample_count`, `missing_count` |
| `errors` | `errors` | `model_call` spans | `request_count` (known outcomes), `error_count` (`error`, `timeout`), `error_rate`, `unknown_count` |
| `coverage` | `<CUR>` | ledger entries | `known_count / entry_count` with `compute_totals` semantics, `unresolved_count`, `unknown_count`, `amount` |
| `reconciliation` | `<CUR>` | ledger entries and allocations | `reference_amount` (each request once), `sources[gateway, app, billing]` each with `amount`, `coverage`, `granularity`, `observed_entry_count`, `known_count`, `allocation_count`, `complete` |

Every document also carries `watermark` (latest source `observed_at` applied, event time, not wall
clock) and `complete`. Lag = now minus `watermark`, computed at read time
(`AggregateStatus.lag_seconds`); `AggregateStatus.billing_observed_at` is the billing source
freshness, reported separately.

## Semantics

* Unknown is never 0. A total over partly unknown inputs keeps the known sum and has
  `complete: false`; a total over only unknown inputs has `amount: null`.
* Estimated and invoiced are separate series, per currency. Never blended, never summed across
  currencies. Inputs whose currency cannot be determined sit in `XXX` and also count against each
  real currency's `entry_count`/`complete`, as in `ledger.totals`.
* Cost, coverage and the reconciliation reference sum LEDGER ENTRIES only (one per request), so a
  request seen by gateway, app and billing is counted once. Request-less allocation records
  (vendor/period billing) feed reconciliation only, as extra source amount with granularity
  `vendor`; they are not added to the reference or the cost series.
* Source `granularity`: `request` when the source reported on ledger entries, `vendor` when it
  has vendor-period allocations, `unknown` when it has none or only unattributed ones; the
  coarsest level wins. Source `coverage` = entries with a known amount from that source divided by
  reference entries; `null` (unknown, not 0) when the source reported on no entry.
* Latency and errors count `model_call` spans only (an `agent_run` span and its child
  `model_call` spans describe the same work).

## Idempotency

Each outbox subject maps to ONE stored contribution (deterministic id) that replaces its previous
version; the affected buckets are then recomputed from all of their contributions. Replays,
redeliveries, changed ledger entries and delivery order therefore do not change the result, and a
failure at any step leaves the checkpoint unadvanced so the redelivery converges.

## Open items

* No `__main__` entrypoint and no hosting in the compose `workers` container yet.
* A production `TraceEventSource` (archive reader) does not exist yet; latency/errors need it.
* Rebuilding a bucket reads one domain-day of contributions; sizing is not claimed (gates G07,
  G12 stay open; the emulator has no RU accounting).
