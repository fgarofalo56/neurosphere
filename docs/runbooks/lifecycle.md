# Data lifecycle: legal holds, deletion requests and dry-run

This runbook is for records officers and security teams who run the lifecycle role. The role
retains, holds and deletes customer data held by NeuroSphere. Deletion cannot be undone, so the
role starts in **dry-run** and nothing is deleted until an operator sets execute mode.

This runbook describes mechanics only and makes no authorization or compliance claim. Retention periods, data classification and
the legal-hold process are customer inputs (gate G06, OPEN): this runbook does not choose them.

## What the role does

| Piece | What it does |
|---|---|
| API (`/api/v1/lifecycle`) | Places and releases legal holds, persists deletion requests as jobs, reports status. It never deletes anything itself. |
| Worker role `lifecycle` | Claims pending jobs, applies the written conflict rules, deletes (execute mode) or records what it would delete (dry-run), reads back to verify, and audits. |
| Targets | The catalog, the cost ledger and the redacted archive. The audit store is never a target and is refused by name and by content. The conversation store is not wired (follow-up). |

Conflict rules, highest first: audit immutability, legal hold, minimum retention, subject
request, maximum-retention expiry. A blocked request is queued and audited and runs when the
blocking rule lifts. It is never forced.

## Settings

Set these on both the API and the worker (the API only reports them; the worker acts on them).
Changing them needs a restart.

| Variable | Default | Meaning |
|---|---|---|
| `NS_LIFECYCLE_MODE` | `dry_run` | `dry_run` decides and audits but calls no mutating method. `execute` is the only value that deletes. Any other value is rejected at startup, so a typo cannot enable deletion. |
| `NS_LIFECYCLE_POLICY_FILE` | unset | Path to a JSON retention policy (see below). Unset, unreadable or invalid means no policy: nothing expires and requests that need a rule are queued as `policy_unset`. |
| `NS_LIFECYCLE_MAX_ATTEMPTS` | `5` | How many times a FAILED queued request is retried (exponential backoff, capped at one hour) before it is audited as `failed_final` and dropped. |

The role needs `lifecycle` in `NS_WORKER_ROLES`. Without Cosmos configuration it reports `idle`
with reason `lifecycle_no_job_source` and does not affect readiness.

### Retention policy file

```json
{
  "policy_version": "records-2026-1",
  "retain_prompt_response_bodies": false,
  "rules": [
    {"data_class": "ledger_entry", "min_retention_days": 30, "max_retention_days": 2555},
    {"data_class": "archive_event", "min_retention_days": 30, "max_retention_days": 365},
    {"data_class": "catalog_entity", "min_retention_days": 0, "max_retention_days": 3650}
  ]
}
```

The values above are shapes, not recommendations. Data classes are `ledger_entry`,
`archive_event` and `catalog_<doc_type>` (`catalog_entity`, `catalog_edge`, ...). A request for a
record whose class has no rule is queued as `no_rule_for_data_class`.

## Operating it

Every route needs `lifecycle.manage` at customer level (the admin role on the customer control
domain). Identity is taken from your token; a customer or domain in a request body is ignored.

1. Check the state: `GET /api/v1/lifecycle/status` returns `mode`, `policy_status`
   (`set` or `unset`, with `policy_problem` when unset), `queue_depth` and `active_holds`.
2. Place a hold before anything else if data may be needed: `POST /api/v1/lifecycle/holds` with
   `reason_code` and at least one selector (`target_kind`, `record_id`, `subject_id`,
   `data_class`) and optional `custodians`. A held record cannot be deleted, pseudonymized or
   expired. `DELETE /api/v1/lifecycle/holds/{hold_id}` releases it.
3. Request a deletion: `POST /api/v1/lifecycle/requests` with `action` (`delete`, `expire`,
   `pseudonymize`, `erase_subject`), a `target` (`target_kind`, `container`, `record_id`) or a
   `subject_id`, and optionally `"dry_run": true`. The response is 202 with a request id.
4. Follow it: `GET /api/v1/lifecycle/requests/{id}` shows `pending`, then `queued` (waiting on a
   hold or minimum retention) or `done` with the outcome.

### Dry-run first

Run every new kind of request in dry-run and read the outcome before enabling execute mode. A
dry-run outcome has `dry_run: true`, `effect: none` and reason `dry_run:would_delete` (or
`would_pseudonymize`, `would_erase`). The audit chain holds a before and an after record with the
same detail, so the audit trail shows what would have happened. A job may ask for dry-run in
execute mode; no job can switch dry-run mode off.

### Switching to execute

1. Confirm `policy_status` is `set` and the policy is the one your records officer approved.
2. Confirm the hold list is current.
3. Set `NS_LIFECYCLE_MODE=execute` on the worker and the API and restart both.
4. `GET /status` now reports `mode: execute`. The worker logs `worker.lifecycle_mode` at startup
   with the mode, the policy state and the registered targets.

## Kill switch and rollback

Set `NS_LIFECYCLE_MODE=dry_run` (or remove `lifecycle` from `NS_WORKER_ROLES`) and restart the
worker. This stops all further mutation. Requests already queued stay queued.

Deleted data is not restorable by NeuroSphere. Recovery is the store-level path in
`docs/ops/dr-runbook.md` (Cosmos backup restore, blob soft delete where enabled). After any
restore, replay the lifecycle audit chain so erased subjects are not brought back. The audit
record of each deletion holds the record id digest and the outcome, never the record body.

## Limits

* One worker pass handles at most 50 jobs; a larger purge needs repeated requests, each audited.
* The worker `/readyz` detail does not show the mode (the supervisor has no per-role detail
  field); use the API status route or the `worker.lifecycle_mode` startup log.
* Scheduled expiry sweeps from policy rules and the conversation target are not built.
* The emulator integration tests (`tests/integration/lifecycle`) need the compose stack and were
  not run in the session that built this.
