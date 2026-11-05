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
