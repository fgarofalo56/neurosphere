# Agent identity resolution

This runbook is for stewards and operators. It explains how telemetry that arrives through the
OpenTelemetry path is counted for the right catalog agent, how to declare an alias, and how to
re-apply an alias to events that were already processed.

An OTLP span carries only the agent's external id (`gen_ai.agent.id`). The workers turn it into
the catalog's canonical agent id when they read stored events. The archive is never rewritten.
This runbook describes mechanics only and makes no authorization or compliance claim.

## What an alias is

An alias is a catalog document that maps an external agent id seen in one telemetry source to one
registered agent. Its key has three parts:

- the source id slug (lowercase, `[a-z0-9._-]`, other characters become `-`);
- the kind, always `external_id`;
- the external agent id, exactly as the span carries it.

Only one active alias exists for a key. An alias must point to an agent of the same cloud and
customer. An alias to another cloud, another customer or a non-agent id is ignored and counted as
`alias_target_invalid`. Resolution never crosses cloud or customer.

## Derived ids

When an external id has no alias, the worker uses a derived id:

`<cloud>:<customer>:<source>:agent:<slug>`

The id is computed again on every read. It is never stored as an alias, because a stored alias
would block the real alias you declare later.

When the slug differs from the lowercased external id, `-<first 8 hex of sha256(external id)>` is
appended. This stops two external ids that slug to the same text from sharing one series.

## The four resolution statuses

| Status | Meaning | Canonical id |
|---|---|---|
| `declared` | The event already carries a canonical id that is an agent of its own cloud and customer. | Kept unchanged. |
| `alias` | An active alias exists for the key. | The alias target. |
| `derived` | An external id but no usable alias. | The derived id. |
| `none` | No external id and no usable canonical id. | Stays null (counted `no_agent_id`). |

A canonical id that is not owned by the event's cloud and customer is treated as absent. The
external id then decides.

If the alias lookup fails, the entry is retried. It never falls back to the derived id, because
that would split the agent's series while the catalog is unavailable.

## Draft agents discovered from telemetry

For a `derived` event the catalog projection creates a draft agent if none exists. It carries
`attributes.discovered_from = "telemetry"`, `attributes.agent_identity = "derived_from_external_id"`
and the `external_agent_id`.

- Nothing merges a draft into a registered agent. A registered agent with the same external id
  and the draft stay side by side.
- To retire a draft, a steward deprecates it.
- A draft needs a domain. Without one the event is still counted and aggregated, but no draft or
  edge is written (counted `agent_undiscoverable_no_domain`).

## Domain for OTLP events

OTLP events arrive with no domain. The worker stamps one at read time and never overwrites a
domain the event already has.

| Status | Domain used |
|---|---|
| event has its own domain | The event's domain, unchanged. |
| `alias`, `declared` | The resolved agent's catalog domain. |
| `derived` | `NS_AGENT_IDENTITY_DISCOVERY_DOMAIN`, when it is a domain id of the event's cloud and customer. |
| otherwise | None. Counted `domain_unattributed`; no draft and no edge. |

Set `NS_AGENT_IDENTITY_DISCOVERY_DOMAIN` if you want drafts for undeclared agents. Leave it unset
to keep them out of the catalog.

## Declare or repoint an alias

`PUT /api/v1/agent-identity/domains/{domain}/aliases` needs `catalog.curate` in that domain.

Request body (no other fields are accepted):

| Field | Required | Notes |
|---|---|---|
| `source_id` | yes | The telemetry source id, up to 128 characters. |
| `external_agent_id` | yes | As the span carries it, up to 512 characters. |
| `target_agent_id` | yes | A canonical agent id in this domain, up to 512 characters. |
| `reason` | no | A reason code (`^[a-z][a-z0-9_]{0,63}$`), not free text. |

Response fields: `outcome` (`created`, `repointed` or `unchanged`), `alias_id`,
`retired_alias_id`, `target_agent_id`, `reresolve_needed` and `reresolve_job`.

- A previous active alias for the same key is retired first, then the new one is added.
- A target that is missing, out of your scope, in another domain or not an agent is one and the
  same 404 (`alias_target_not_found`).
- Each write is audited (`agent_identity.alias_declare`, and `agent_identity.alias_retire` for a
  repoint). Audit records carry ids and reason codes. The external agent id is never written to
  the audit record.
- `reresolve_needed` is true unless the outcome is `unchanged`. Then `reresolve_job` holds the
  `command` and the `arguments` to run (see below).

`GET /api/v1/agent-identity/domains/{domain}/aliases?source_id=...&external_agent_id=...` needs
`data.read` in the domain. It returns `source_id`, `external_agent_id` and `target_agent_id`, or a
404 `alias_not_found` when there is no active alias for a target in that domain.

The Foundry discovery poller also writes an alias for each discovered agent that has an external
id. Its source id is `foundry`. If that key already points to a different agent, nothing changes
and the poller counts an `alias_collisions`.

New events pick up a new alias within about a minute (the cache settings below). Events already
processed stay under the old id until you run re-resolution.

## Re-resolve past events

Re-resolution is an operator job. Nothing runs it for you after an alias change.

```
python -m neurosphere_workers.agent_identity reresolve --customer <customer> --source-id <source> --external-agent-id <external id> [--since <ISO 8601>] [--max-events <n>]
```

Use the `reresolve_job.arguments` from the PUT response for the three required values. The job
needs the same `NS_*` worker configuration as the worker roles. `--customer` is required.

The job reads the archive, finds the telemetry of that source and external id inside the
aggregates window, and feeds each event through the aggregates and catalog handlers again. The
contribution moves to the aliased agent and the old series points are rebuilt away. Running it
twice changes nothing (`moved` is 0 on the second run).

It prints one JSON object of counters and no event content:

| Field | Meaning |
|---|---|
| `customer_id`, `source_id`, `window_start`, `since` | What was asked for and the window floor. |
| `examined` | Archive records read. |
| `matched` | Telemetry events of this source and external id. |
| `reapplied` | Events fed through the handlers again. |
| `moved` | Contributions whose agent id changed. |
| `skipped_out_of_window` | Matched but older than the window or `--since`. |
| `skipped_foreign_customer` | Records of another customer, never processed. |
| `skipped_unreadable` | Records that could not be read. |
| `truncated` | More records remain than `--max-events`. |

Exit codes:

| Code | Meaning |
|---|---|
| 0 | Done. |
| 1 | Done, but the scan was truncated. Run again with a larger `--max-events` or a later `--since`. |
| 2 | Refused: no customer, unusable arguments or missing configuration. Nothing ran. |
| 3 | Dependencies are not wired. |

## Limits

- The job covers the aggregates window only. Older events stay under the derived id.
- The scan examines at most `--max-events` records, default `NS_AGENT_IDENTITY_RESCAN_MAX_EVENTS`.
  The report says `truncated` when more remain.
- There is no automatic trigger. An automatic run after an alias change is a follow-up.
- A derived draft is not merged or removed by the job.
- Cost records and the ledger carry no agent id and are not resolved here.

## Counters

Counters are integers with no ids and no event content.

| Group | Counters |
|---|---|
| Resolver | `resolved_alias`, `derived`, `declared`, `no_agent_id`, `alias_target_invalid`, `lookup_failures`, `domain_from_agent`, `domain_from_setting`, `domain_unattributed`, `drafts_created`, `contributions_moved` |
| Catalog projection | `agent_drafts_created`, `agent_drafts_existing`, `agent_undiscoverable_no_domain`, `agent_draft_out_of_scope`, `agent_draft_collision` |
| Foundry poller | `aliases_declared`, `aliases_unchanged`, `alias_collisions`, `alias_refused` |

The `projections`, `aggregates` and `evaluation` worker roles expose the resolver counters through
their role `counters()` hook. The projections role adds the catalog projection counters. The
Foundry poller reports its counters in its tick stats.

The worker's `/readyz` response lists each role; a running role that has counters carries them
under `counters` in its entry (for example `roles[].counters.derived`). A role whose counter read
fails is still reported, without `counters`. The Foundry poller counters stay in its tick stats.

## Settings

Read by the workers and the re-resolution job (prefix `NS_AGENT_IDENTITY_`).

| Variable | Default | Meaning |
|---|---|---|
| `NS_AGENT_IDENTITY_POSITIVE_TTL_SECONDS` | `60` | How long a found alias is cached. `0` looks up every time. |
| `NS_AGENT_IDENTITY_NEGATIVE_TTL_SECONDS` | `15` | How long "no alias" is cached. `0` looks up every time. |
| `NS_AGENT_IDENTITY_RESCAN_MAX_EVENTS` | `50000` | Default `--max-events` for re-resolution (at least 1). |
| `NS_AGENT_IDENTITY_DISCOVERY_DOMAIN` | unset | Domain id for events of derived agents. Unset: no draft and no edge for them. |

The cache holds up to 10 000 keys.

## Rollback

There is no schema change and no data migration. Archived events keep their raw fields, and the
next worker read resolves them.

To roll back, revert the change, or set both TTL settings to `0` so every lookup reads the
repository. Series created under derived ids in the meantime become orphans that the 90-day
aggregate window and the prune job age out. Draft agents stay as ordinary drafts that a steward
can deprecate.

## Live check

Verified only against in-memory twins and local emulators. A hosted check that an OTLP agent from a
real producer gets a series is open until it is evidenced.
