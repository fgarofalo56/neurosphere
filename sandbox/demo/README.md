# Curated demo world (PRP-71)

Hand-written, deterministic catalog for the local `demo-world` profile. Synthetic only; teams are
role labels, never people. Data lives in `data/*.json`; `build.py` turns it into contract-valid
documents and the generator NDJSON layout (plus `services.ndjson` and `mcp_servers.ndjson`).

```python
from sandbox.demo.build import build_demo_world, write_demo_world, demo_manifest

world = build_demo_world("commercial", customer="synthco", epoch="2026-10-01T00:00:00Z", days=7)
write_demo_world(world, Path("temp/demo"))  # -> {file name: line count}
world.undeclared_agents  # telemetry-only agents (UndeclaredAgent: ids, model, tools, services)
world.outage_service_id  # the service the scripted outage hits
world.downstream_agent_ids  # agents that depend on it (sorted)
world.unrelated_agent_ids  # every other catalog agent (sorted)
```

## Id scheme

`<cloud>:synthco:sandbox:<type>:<slug>` where the slug is the value in the tables below, for
example `commercial:synthco:sandbox:agent:payment-approval-assistant`. Edge ids are
`<relation>:<source slug>.<target slug>`. Agent versions are `<agent slug>-v1` / `-v2`.
Per-agent relationships (`owned_by`, `uses_model`, `invokes` tools, `depends_on` services, `reads`,
`writes`, `grounded_by`) are curated in `data/agents.json`; tools list the services they
`depends_on` in `data/tools.json`. An agent that invokes a tool must also list the tool's
services (a test enforces this, so the downstream set is unambiguous).

## Delegation pairs

Parent agent slug to child agent slug (ids are `<cloud>:synthco:sandbox:agent:<slug>`):

| Parent | Child | Scope |
|---|---|---|
| `payment-run-coordinator` | `card-settlement-reconciler` | finance |
| `payment-approval-assistant` | `journal-entry-agent` | finance |
| `billing-dispute-resolver` | `payment-approval-assistant` | cross-domain (support to finance) |
| `billing-dispute-resolver` | `customer-reply-drafter` | support |
| `expense-reimbursement-assistant` | `expense-policy-advisor` | cross-domain (HR to finance) |
| `month-end-close-assistant` | `journal-entry-agent` | finance |
| `treasury-cash-forecaster` | `budget-variance-analyst` | finance |
| `support-triage-assistant` | `ticket-summarizer` | support |
| `support-triage-assistant` | `escalation-router` | support |
| `customer-reply-drafter` | `knowledge-answer-assistant` | support |
| `alert-triage-assistant` | `incident-case-builder` | security-operations |
| `alert-triage-assistant` | `threat-intel-enricher` | security-operations |

Hard rule (incident integrity): no parent outside the downstream set may delegate to a
downstream agent, so a delegation can never make an agent fail that does not depend on
`payments-gateway`. `build_demo_world` raises on a violation, an unknown agent, a
self-delegation or a duplicate; tests also check there are no cycles.

## Domains and teams

| Domain slug | Teams (owner slug) |
|---|---|
| `finance` | `treasury-operations`, `accounts-payable-automation`, `general-accounting` |
| `support` | `support-platform`, `support-quality-engineering` |
| `human-resources` | `people-operations`, `talent-acquisition-systems` |
| `security-operations` | `security-operations-center`, `identity-protection`, `platform-engineering` |

## Services (7) and the scripted outage

`payments-gateway` (**designated outage service**), `ledger-api`, `crm-platform`, `ticketing-api`,
`hris-api`, `siem-api`, `identity-directory`.

Downstream of `payments-gateway` (5 agents, three domains): `payment-approval-assistant`,
`payment-run-coordinator`, `card-settlement-reconciler` (finance), `billing-dispute-resolver`
(support), `expense-reimbursement-assistant` (human-resources). The other 27 agents are unrelated
(for example `journal-entry-agent`, `support-triage-assistant`, `alert-triage-assistant`).
The service is also reached through tool `payment-initiation` (MCP server `finance-tools-mcp`).

## Agents (32)

- finance (9): `invoice-intake-assistant`, `payment-approval-assistant`, `treasury-cash-forecaster`,
  `payment-run-coordinator`, `journal-entry-agent`, `month-end-close-assistant`,
  `card-settlement-reconciler`, `budget-variance-analyst`, `expense-policy-advisor`
- support (8): `support-triage-assistant`, `ticket-summarizer`, `knowledge-answer-assistant`,
  `customer-reply-drafter`, `escalation-router`, `billing-dispute-resolver`,
  `customer-sentiment-analyst`, `returns-policy-assistant`
- human-resources (7): `leave-request-assistant`, `benefits-enrollment-advisor`,
  `candidate-screening-assistant`, `job-posting-writer`, `onboarding-coordinator`,
  `expense-reimbursement-assistant`, `employee-policy-assistant`
- security-operations (8): `alert-triage-assistant`, `incident-case-builder`,
  `threat-intel-enricher`, `phishing-report-analyzer`, `vulnerability-prioritizer`,
  `access-anomaly-investigator`, `security-runbook-assistant`, `compliance-evidence-collector`

Display names are the title-cased slugs (see `data/agents.json`; for example "Payment Approval
Assistant", "Month-End Close Assistant").

Two-version agents (capabilities differ between versions): `payment-approval-assistant`
(1.0.0 -> 1.1.0, adds `payment.initiate`), `month-end-close-assistant` (2.0.0 -> 2.1.0, adds
`ledger.post`), `support-triage-assistant` (1.4.0 -> 1.5.0, adds `ticket.route`),
`benefits-enrollment-advisor` (1.0.0 -> 1.1.0, adds `enrollment.guide`), `alert-triage-assistant`
(2.1.0 -> 2.2.0, adds `incident.escalate`).

## Telemetry-only agents (no catalog entity)

`adhoc-invoice-reconciler` ("Ad Hoc Invoice Reconciler", finance), `unregistered-ticket-bot`
("Unregistered Ticket Bot", support), `experimental-hr-chatbot` ("Experimental HR Chatbot",
human-resources), `personal-log-analyzer` ("Personal Log Analyzer", security-operations). Ids use
the same scheme (`...:agent:<slug>`) but no document or edge mentions them.

## Data assets (15, `grounding_source`)

| Slug | Classification | Sensitivity | Residency |
|---|---|---|---|
| `eu-customer-records` | confidential | pii | eu_eea |
| `us-customer-records` | confidential | pii | united_states |
| `support-ticket-archive` | internal | pii | united_states |
| `product-knowledge-base` | public | none | united_states |
| `general-ledger` | restricted | financial | united_states |
| `ap-invoices` | confidential | financial, pii | eu_eea |
| `treasury-cash-positions` | restricted | financial | united_states |
| `payment-card-tokens` | restricted | pci, financial | united_states |
| `finance-policy-handbook` | internal | none | united_states |
| `eu-employee-records` | restricted | pii | eu_eea |
| `employee-health-benefits` | restricted | phi, pii | united_states |
| `recruiting-candidate-pool` | confidential | pii | eu_eea |
| `employee-policy-handbook` | internal | none | united_states |
| `security-event-logs` | confidential | other | united_states |
| `threat-intelligence-index` | internal | none | united_states |

Two writers: `general-ledger` (`journal-entry-agent`, `month-end-close-assistant`) and
`support-ticket-archive` (`customer-reply-drafter`, `escalation-router`). EU PII readers:
`support-triage-assistant` and `access-anomaly-investigator` (and others) read `eu-customer-records`
or `eu-employee-records`.

## Tools (16), models (4), MCP server (1)

Tools: `payment-initiation`, `ledger-lookup`, `invoice-parser`, `journal-entry-poster`,
`exchange-rate-lookup`, `ticket-search`, `ticket-updater`, `customer-profile-lookup`,
`knowledge-article-search`, `employee-directory-lookup`, `leave-balance-calculator`,
`job-posting-publisher`, `alert-triage-query`, `incident-case-creator`, `threat-intel-lookup`,
`analysis-code-sandbox`. Models: `general-reasoning-model`, `fast-chat-model`, `embedding-model`,
`small-private-model`. MCP server: `finance-tools-mcp` (owner team `treasury-operations`).

## Not included

`EntityRevision` history is not seeded here (the revision store is PRP-76); version history is
carried by the two `AgentVersion` documents per agent above.

## Telemetry and the scripted incident (`sandbox/demo/incident.py`)

Telemetry and cost for the curated world, built directly from a `DemoWorld` with the contract
models (the generic generator world cannot take curated entities). Deterministic for a seed,
epoch and volume; every event validates as `TelemetryEvent`, every cost row as `CostRecord`.

```python
from sandbox.demo.build import build_demo_world
from sandbox.demo.incident import (
    build_demo_telemetry,
    write_demo_telemetry,
    incident_manifest,
    write_incident_manifest,
)

world = build_demo_world("commercial")
tele = build_demo_telemetry(world, seed=1)  # DemoTelemetry(events, costs, manifest)
write_demo_telemetry(tele, out_dir)  # telemetry.ndjson + cost.ndjson (generator layout)
write_incident_manifest(tele.manifest, out_dir / "incident-manifest.json")
```

- Volume parameters: `traces_per_agent_day` (2), `baseline_traces` (4, the hour before the
  incident), `incident_traces` (6, the incident hour). Defaults give about 6k events for the 36
  agents (32 curated plus the 4 telemetry-only ones) over 7 days.
- The incident window is the last hour of the seeded window (`epoch + days`), so it stays
  recent after the seed rebases the epoch. In it, spans bound to `payments-gateway` fail
  (`error`/`timeout`) with 8x latency, and only its five downstream agents fail (hourly error
  rate at or above 0.25, health `failing`); the other agents stay under 0.05. The baseline hour
  before is healthy for all.
- Tool-call spans carry `tool.external_tool_id`, `tool.canonical_tool_id`, `tool.tool_name`,
  the tool's service (`service.*`) when it depends on one, and `mcp_server_ref` when the seeded
  tool has one. Direct service calls are `tool_call` spans with only `service.*`. All other
  spans leave these null.
- Delegation: about half of a parent's traces hand off to each paired child (a `delegation`
  span under the parent's `agent_run`, then the child's `agent_run` parented to it; structure
  as in `sandbox/traces.py`). A child failure never fails its parent. Pairs are curated in
  `data/scenario.json` (`delegations`), exposed as `world.delegations` and in the demo
  manifest, and emitted as `delegates_to` catalog edges. Telemetry-only agents do not delegate
  (a catalog edge cannot name them). See "Delegation pairs" below.
- `incident-manifest.json`: service id and name, downstream/unrelated/undeclared agent ids,
  `window`, `baseline_window`, `effects` and `expected_health_transitions`.
