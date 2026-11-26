# Governance policy engine

Status date: 2026-11-26. This runbook covers the governance policy engine (PRP-105): policy
definitions, the `policy_eval` worker that finds violations, time-boxed exceptions through HITL,
enforcement bindings and the in-process decision function `decide`.

The engine is detective only. It records evidence that a rule matched; it blocks nothing.
Publishing a policy and changing an enforcement mode are action-executor intents, and the
platform-control write target that executes them is PRP-108. Until PRP-108 lands, a publish or
retire request drafts an advisory intent ("no supported write connector") and the policy stays a
draft. A violation is evidence of a rule match, not a legal or compliance verdict.

## What exists after PRP-105

| Piece | Where | State |
|---|---|---|
| Policy models, validation, stores (memory and Cosmos) | `neurosphere_core.governance.policy` | Built |
| Seven rule evaluators and the plugin extension point | `neurosphere_core.governance.policy.rules`, `rule_plugins` | Built |
| Evaluation run, exceptions, catalog projection, lifecycle | `neurosphere_core.governance.policy` (`evaluate`, `exceptions`, `projection`, `lifecycle`) | Built |
| Decision function `decide` | `neurosphere_core.governance.policy.decide` | Built; no caller until PRP-112 to PRP-114 |
| Worker role `policy_eval` | `neurosphere_workers.policy_eval` | Built; runs when listed in `NS_WORKER_ROLES` |
| API routes and the optional component `governance_policy` | `neurosphere_api.governance.policy`, `runtime/builders/governance.py` | Built; on by default |
| Executing publish, retire and enforcement mode changes | PRP-108 platform-control target | Planned; intents are advisory until then |
| Policy UI | PRP-106 | Planned |
| Violation notifications | PRP-107 binds `violation_event_sink` | Planned; the sink is a no-op today |
| `content_rule` interaction finding reader | PRP-104 binds `interaction_finding_reader` | Planned; `content_rule` is unavailable today |
| Cosmos containers | `policy_definitions`, `policy_violations`, `policy_exceptions` (PRP-102) | Declared; filled by this engine |
| Enforcement on real systems | PRP-112 (gateway), PRP-113 (tool call, MCP), PRP-114 (SDK) | OPEN |

The hosted Bicep templates list worker roles explicitly, so `policy_eval` does not run in the
hosted environment until an infra change adds it to `NS_WORKER_ROLES`.

## Policies and rules

A policy is a versioned document of 1 to 32 typed rules. Each rule has a `rule_id`, a `kind` from
a closed list, an `applies_to` filter (entity types, tags, environments, entity ids; all empty
means every entity in the domain) and `params` validated against that kind's parameter model.
There is no expression language: no rule text is compiled, evaluated or templated, and a draft
with an unknown kind, bad parameters or an extra field is refused with 422 `invalid_schema`.

A published version is immutable. A new draft is the next version; there is at most one open
draft per policy. Policy ids are unique per customer.

| Rule kind | What it finds | Evaluator |
|---|---|---|
| `model_allow_list` | A model used through a catalog `uses_model` edge or seen in telemetry that is not on the list | Built |
| `data_sensitivity_access` | An agent that reads or writes data of a listed sensitivity category without an approved agent version | Built |
| `residency` | An asset whose residency region or geography is outside the allowed set | Built |
| `required_owner` | An entity with no `owned_by` edge | Built |
| `required_approval` | An AgentVersion whose approval state is anything but `approved` | Built |
| `registration_required` | An agent seen in telemetry with no catalog Agent, or an AgentVersion with no approval record | Built |
| `content_rule` | Counts of detected content categories, from interaction finding metadata only | Built; unavailable until PRP-104 binds the reader |
| `budget` | Spend against a cap | PRP-115 |
| `required_attestation` | A missing attestation | PRP-130 |
| `identity_entitlement` | An identity entitlement gap | PRP-119 |

A kind without an evaluator in this deployment is reported `evaluator_unavailable` by
`GET /api/v1/governance/policy/status`. A draft may hold it, but publishing a policy that
contains it is refused at the dry run with `rule_kind_unavailable`, so no policy looks active
while doing nothing.

A later rule kind plugs in by adding one module to
`neurosphere_core.governance.policy.rule_plugins` that exposes
`build(ctx) -> RuleEvaluator | None`. `None` means the kind is unavailable in this deployment; a
`build` that raises is reported `evaluator_unavailable` with reason `plugin_failed`.

## Enforcement modes and points

Every enforcement binding has a mode: `off`, `audit` or `enforce`. Bindings created at publish
start at the policy's mode, which may only be `audit` (the default) or `off`. Publishing with
`mode: enforce` is refused with `enforce_requires_mode_change`. `enforce` is always a per-point
`enforcement_mode_change` action with approval, executed by PRP-108 through
`BindingStore.set_mode`; nothing else sets it.

Which points a rule kind can bind to (a planning assumption, revisit with PRP-112 to PRP-115):

| Rule kind | Points |
|---|---|
| `model_allow_list`, `residency` | `gateway`, `sdk` |
| `data_sensitivity_access` | `tool_call`, `mcp_server`, `mcp_client`, `sdk` |
| `required_owner`, `required_approval`, `required_attestation`, `registration_required` | `registration` |
| `budget` | `budget` |
| `content_rule` | none (detective only) |

What each point can actually block. Nobody may claim a block outside this table:

| Point | Can block | What it blocks | Owner |
|---|---|---|---|
| `gateway` | yes | Only model traffic through a NeuroSphere-managed APIM gateway in manage mode on NeuroSphere-owned products; Commercial only | PRP-112 |
| `tool_call` | yes | NeuroSphere's own copilot tool calls | PRP-113 |
| `mcp_server` | yes | Calls to NeuroSphere's MCP server tools | PRP-113 |
| `mcp_client` | yes | NeuroSphere's outbound calls to registered external MCP servers | PRP-113 |
| `sdk` | no | Nothing: a cooperative guard in the workload, never a boundary | PRP-114 |
| `budget` | no | Nothing automatically: proposes a `budget_cap_change` action for approval | PRP-115 |
| `registration` | yes | Withholds activation of an unapproved AgentVersion inside NeuroSphere only | PRP-108 |

Detective evaluation by the `policy_eval` worker blocks nothing.

## Violations

Each worker tick evaluates every published policy the worker's own derived scope covers, with a
separate budget per rule (subjects and seconds). For each finding it creates or updates one
violation, de-duplicated by policy, rule, subject and evidence class. A violation carries the
policy id and version, rule id, subject id, evidence ids, `first_seen_at`, `last_seen_at` and
`occurrence_count`, and never any interaction content.

A violation is resolved only after a run that finished that rule completely. When a rule's run
was cut short (subject budget, time budget, a source that truncated, or the resolve pass itself
hitting its cap with `resolve_truncated`), nothing is resolved and the run status says
`truncated`. A truncated or failed run never silently "fixes" a violation.

The worker evaluates only domains its own scope covers and never widens it; the run status lists
domains it skipped. Customer-wide policies apply to subjects in domains the worker can see.

## Exceptions

A caller with `action.propose` in the violation's domain can request a time-boxed exception:
`POST /api/v1/governance/policy/domains/{domain}/violations/{violation_id}/exception-requests`
with a justification code, justification text (1 to 1000 characters) and an expiry at most
`NS_GOVPOLICY_EXCEPTION_MAX_DAYS` days away. The request opens a HITL item of kind
`policy_exception` whose subject is the violation's canonical id. Only the SHA-256 of the
justification text is kept, in the audit record; the reviewer sees the justification code
(issue #418 tracks a contract field for the text).

A reviewer with `catalog.curate` approves or rejects it in the review queue. The next worker tick
reads the item back: an approval makes the exception `active` until its expiry and the violation
`excepted`; a rejection or an expiry leaves the violation open. The requester can never approve
their own request: the worker refuses an approval whose reviewer is the requester, or whose
review item was opened by someone else, and closes the exception as `rejected` with
`self_approval_refused`.

## The decision function

`PolicyDecider.decide(scope, request, now=...)` answers `allow`, `deny` or `audit` for one
enforcement point, with the matched rule ids, policy versions, the binding mode, reason codes
and a cache lifetime. It answers from a snapshot refreshed every
`EnforcementSetting.decision_cache_ttl_seconds` (60 by default; the `enforcement` stored setting
is not loadable until PRP-108/109, so the default applies everywhere today).

- `deny` only when a matching rule's binding for that point is `enforce` and no active exception
  applies. A match under `audit` answers `audit`. `off` bindings are ignored.
- A subject, policy or exception outside the caller's scope is never described in the response.
- A failed refresh keeps the last snapshot and marks answers degraded with `stale_snapshot`.
  With no snapshot at all the answer is `audit`, degraded, `snapshot_unavailable`. A failure
  never produces `deny`.
- `decide` writes nothing; a `govpolicy.decide` audit record is written only for `deny` and for
  an audit-mode would-deny, never per allow.

Known limit: a subject with no catalog entity (an unregistered agent, or a model known only by
name) is governed by every policy in the caller's scope. Under a future `enforce` binding,
`registration_required` could therefore deny an agent that is registered in a domain the caller
cannot see. PRP-112 to PRP-114 must account for this before turning on `enforce`.

## API

All routes are under `/api/v1/governance/policy`. Reads need `govpolicy.read` in the subject's
domain; an id outside the caller's scope is 404, indistinguishable from a missing one.
Customer-wide policies live in the customer-control domain and need the permission there.

| Method | Path | Permission |
|---|---|---|
| GET, POST | `/domains/{domain}/policies` | `govpolicy.read`, `govpolicy.manage` |
| GET | `/domains/{domain}/policies/{policy_id}` (`?version=`, `ETag`) | `govpolicy.read` |
| GET | `/domains/{domain}/policies/{policy_id}/versions` | `govpolicy.read` |
| PUT | `/domains/{domain}/policies/{policy_id}/draft` (`If-Match`) | `govpolicy.manage` |
| POST | `/domains/{domain}/policies/{policy_id}/publish` | `govpolicy.manage` |
| POST | `/domains/{domain}/policies/{policy_id}/retire` | `govpolicy.manage` |
| GET | `/domains/{domain}/violations`, `/domains/{domain}/violations/{violation_id}` | `govpolicy.read` |
| POST | `/domains/{domain}/violations/{violation_id}/exception-requests` | `action.propose` |
| GET | `/domains/{domain}/exceptions` | `govpolicy.read` |
| GET | `/domains/{domain}/bindings` | `govpolicy.read` |
| GET | `/status` | `govpolicy.read` in any domain |

`govpolicy.read` is held by viewer, analyst, domain steward, admin and security auditor;
`govpolicy.manage` by domain steward and admin. Publish and retire return the drafted action
intent; its approval follows the action plane (`action.approve`, a second steward, no
self-approval). These permissions are unrelated to `policy.manage`, which governs identity
principal policies.

Creating a policy whose id is already used anywhere in the customer, including a domain the
caller cannot see, is refused with 409 `policy_exists`. The response names nothing about the
existing policy.

## Settings

API (`governance_policy` component):

| Variable | Default | Meaning |
|---|---|---|
| `NS_GOVPOLICY_ENABLED` | `true` | `false` disables the component; every route answers 503 `capability_unavailable` |
| `NS_GOVPOLICY_BACKEND` | `cosmos` | `memory` is accepted only under `NS_ENV=local` (otherwise startup is refused with `govpolicy_memory_not_local`) |
| `NS_GOVPOLICY_EXCEPTION_MAX_DAYS` | `90` | Longest exception a requester may ask for |
| `NS_GOVPOLICY_LOCAL_SEED_FILE` | unset | Local demo seed, see below |

Worker (`policy_eval` role):

| Variable | Default | Range |
|---|---|---|
| `NS_POLICY_EVAL_INTERVAL_SECONDS` | `300` | 30 to 86400 |
| `NS_POLICY_EVAL_SUBJECT_BUDGET` | `5000` | 1 to 100000 subjects per rule |
| `NS_POLICY_EVAL_TIME_BUDGET_SECONDS` | `120` | 1 to 3600 seconds per rule |

An unknown `NS_POLICY_EVAL_*` variable refuses the role (`policy_eval_setting_unknown`), as does
an invalid value (`policy_eval_setting_invalid`). A store outage releases the tick with a logged
reason code and the role retries; it does not crash-loop. Policies published since the last run
are evaluated first.

## Local demo seed

Before PRP-108 there is no way to publish a policy outside a local stack. Under `NS_ENV=local`
only, `NS_GOVPOLICY_LOCAL_SEED_FILE` names a JSON file of up to 50 draft policies, each with its
domain; at startup each is published through the same lifecycle as an approved intent, audited as
`govpolicy.seed`, under a local-only scope that covers exactly the seed's domains. A policy whose
content is already published is skipped, so a restart publishes nothing twice. In any other
environment the file refuses startup with `govpolicy_seed_not_local`.

```json
{
  "policies": [
    {
      "domain_id": "commercial:acme:neurosphere:domain:support",
      "policy_id": "no-unapproved-pii-readers",
      "display_name": "No agent without approval may read PII",
      "severity": "high",
      "mode": "audit",
      "rules": [
        {
          "rule_id": "pii-read",
          "kind": "data_sensitivity_access",
          "applies_to": {},
          "params": {
            "sensitivity_categories": ["pii"],
            "access": "read",
            "allowed_when": "agent_version_approved"
          }
        }
      ]
    }
  ]
}
```

Then run the API and the worker with `policy_eval` in `NS_WORKER_ROLES`; one violation appears
for each agent with a `reads` edge to a PII grounding source and no approved version.

## Rollback

No migration: every document is new. To turn the engine off, set `NS_GOVPOLICY_ENABLED=false`
and remove `policy_eval` from `NS_WORKER_ROLES`, or revert the change. Projected catalog `Policy`
entities stay as `advisory` records and can be deprecated through the catalog. Nothing enforces
in this release, so turning it off removes no control.
