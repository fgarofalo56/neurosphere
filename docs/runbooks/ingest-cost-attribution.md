# Ingest: cost attribution and invoiced records

Applies to `POST /v1/ingest/events` CloudEvents of type cost.

## Request id (#31)

The `nsrequestid` CloudEvent extension is canonical. A cost `data.request_id` is accepted as
a fallback:

| extension | data.request_id | result |
|---|---|---|
| present | absent | extension used |
| absent | present | data value used (removed from the stored CostRecord) |
| present | present, equal | accepted |
| present | present, different | per-event rejection `request_id_mismatch` |
| any | not a string, empty or over 256 chars | per-event rejection `invalid_event` |

With neither, the record is an unattributed allocation (never merged into a request entry).

## Invoiced records (#27)

`kind=invoiced` is accepted only from a source registered with observation source `billing`.
Otherwise the single event is rejected with `invoiced_not_billing` (HTTP 202, listed in
`rejected`). The ledger repeats the check: a non-billing `invoiced` observation is never folded
(outbox mapping drops it; `Observation` refuses to be built), so it cannot win precedence rank 0.

## Cost center (`nscostcenter`, #190)

The `nscostcenter` CloudEvent extension (set by the gateway poller) is read after the producer
scope is resolved, for telemetry and cost events. The value is stripped of control characters
and must match `^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$`; `N/A` or empty is treated as absent. An
invalid value never rejects the event, is not stored and is never logged. A valid value is
stored as `HubMessage.cost_center`; for a cost record it is also merged into
`tags.cost_center`. A record that already carries a different `tags.cost_center` keeps its own
tag and the mismatch is counted (`IngestService.cost_center_mismatches`).

## Reason families

| Family | Codes | Result |
|---|---|---|
| Whole-request 422 | `body_too_large`, `depth_exceeded`, `malformed_json`, `unsupported_media_type`, `invalid_envelope` | nothing published |
| Whole-request 403 (identity claims) | `claim_mismatch` (`customer_id`, `cloud`, `source_id`), `cloud_mismatch` | nothing published |
| Whole-request 429 | `rate_limited` | nothing published |
| Per-item rejection (202, listed in `rejected`) | `invalid_event`, `invalid_cloudevent`, `missing_time`, `request_id_mismatch`, `unsupported_event_type`, `invoiced_not_billing`, `observation_source_mismatch` | other items still published |
| Per-item ignored | `unsupported_metric_type`, `unmapped_metric_name`, `unsupported_temporality` | valid but not mapped |

`observation_source_mismatch` (a cost `observation_source` that disagrees with the producer
registration, #169) is per item: one bad item must not block a batch. Identity claims stay a
whole-request 403.
