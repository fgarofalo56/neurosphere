---
title: "NeuroSphere walking deck"
status: draft
date: 2026-11-02
audience: "sellers and evaluators"
claims:
  - id: C01
    text: "NeuroSphere is a customer-hosted AI governance platform for Azure Commercial and Azure Government."
    source: docs/index.md
  - id: C02
    text: "Stated objectives: discover registered and observed agents, explain ownership, models, grounding and cost, surface evidence-backed recommendations, enable governed actions (review queue and API; chat planned), give operators a live ecosystem view."
    source: docs/PRD.md
  - id: C03
    text: "The synthetic sandbox generator produces a catalog of domains, owners, agents, model deployments, grounding sources and tools, with asserted and inferred relations."
    source: sandbox/README.md
  - id: C04
    text: "Missing fields stay null or unknown, never zero by default; cost records distinguish estimated from invoiced spend and carry a price version."
    source: docs/PRD.md
  - id: C05
    text: "Reference connectors are documented for Azure Monitor and Log Analytics, APIM gateway logs, Foundry discovery, Azure Cost Management exports and generic OpenTelemetry and CloudEvents; coverage and limits are published and no connector has run against a live provider (G04 open)."
    source: docs/connectors/coverage.md
  - id: C06
    text: "The Admin walkthrough injects duplicate, out-of-order and malformed events so quarantine and replay can be observed."
    source: docs/walkthroughs/admin.md
  - id: C07
    text: "A persona with data.read can compare cost sources for a seeded spike window on the reconciliation page; access for the Auditor role is to be verified."
    source: docs/walkthroughs/auditor.md
  - id: C08
    text: "Consolidation candidates are always labelled candidate and never auto-merged; unused agents are agents that are active with zero telemetry for the window."
    source: docs/walkthroughs/steward.md
  - id: C09
    text: "The action executor rechecks permission, honors approvals, audits, and verifies the real change; the seeded demo intents stop at awaiting confirmation, so no change is executed in the demo."
    source: docs/walkthroughs/steward.md
  - id: C10
    text: "The MCP server exposes bounded structured tools and has no confirm, execute or approve tool; a human confirms through the same durable action executor."
    source: docs/reference/mcp.md
  - id: C11
    text: "In repo: analytics adapters accept no query text, so no LLM-generated SQL reaches the engine. Copilot controls (sandboxed Vega-Lite charts, the model drafting an action without executing it) are planned."
    source: docs/security/threat-model.md
  - id: C12
    text: "The Viewer walkthrough uses the map page to browse agents and the catalog page to read an agent entry; the recommendations page lists cost_spike items without singling out the seeded spike agent."
    source: docs/walkthroughs/viewer.md
  - id: C13
    text: "Access is scoped by grants in the policy store; there is no unrestricted bypass for any role; the Viewer role has no action, export or edit path."
    source: docs/walkthroughs/viewer.md
  - id: C14
    text: "Automated axe tests with WCAG 2.2 AA and Section 508 rule tags cover every registered route in light, dark and high-contrast modes; this is test evidence, not a conformance statement, and no VPAT exists."
    source: docs/accessibility/README.md
  - id: C15
    text: "Unsupported cloud, region or feature combinations are disabled with a reason from the capability matrix, not routed to another cloud; availability, GA and authorization are separate."
    source: docs/PRD.md
  - id: C16
    text: "NeuroSphere is not FedRAMP authorized and cannot grant an agency ATO; agency authorizing officials make that decision."
    source: docs/PRD.md
  - id: C17
    text: "Control mapping, SSP narratives and a POA&M template exist as documents that support, and do not make, the authorizing official's decision."
    source: docs/RESEARCH-AND-GATES.md
  - id: C18
    text: "Planning targets, to be measured and not promised: regional core API availability 99.9%; dashboard p95 <=2s on bounded 90-day aggregates; catalog p95 <=500ms on indexed scoped queries; map freshness p95 <=10s after normalized ingestion; browser target <=2k visible nodes at >=30fps."
    source: docs/PRD.md
  - id: C19
    text: "Five persona walkthroughs (Viewer, Analyst, Steward, Admin, Auditor) each name a sandbox scenario and are marked DRAFT."
    source: docs/walkthroughs/viewer.md
  - id: C20
    text: "The documentation set includes install, operations, security, migration and DR runbooks, and API, MCP and SDK references."
    source: docs/runbooks/install.md
  - id: C21
    text: "Gate G09 (theme, brand and media review) is waived by the owner for demo scope and no independent review was performed; the walkthroughs are marked DRAFT and have not passed an independent new-user test."
    source: docs/runbooks/new-user-test.md
  - id: C22
    text: "Hidden navigation is not authorization: the API denies regardless of what the UI shows; theme is never permission."
    source: docs/security/threat-model.md
---

# NeuroSphere
Claims: C01

- Customer-hosted AI governance for Azure Commercial and Azure Government
- Walking deck, DRAFT: claims unreviewed, see the claims checklist
- Every screen shown comes from the synthetic sandbox, never production data

Notes:
Welcome. This deck is a draft for sellers and evaluators. Every factual statement is tied to a document in the repository through the claims checklist, and none of those claims has had an independent review yet. All demo data is synthetic. Say that out loud at the start of every session.

---

# What it is for
Claims: C01, C02

- Discover registered and observed agents
- Explain ownership, models, grounding and cost
- Surface evidence-backed recommendations
- Enable governed actions (review queue and API; chat planned)
- Give operators a live view of the AI ecosystem

Notes:
These are the stated objectives in the product requirements document. They are objectives, so describe them as what the product is built to do, and move straight to the next slides for what is actually documented and demonstrable today. Do not add claims about savings or about how much of an estate it will find.

---

# A catalog with relationships
Claims: C03, C12

- Agents, owners, domains, models, grounding sources and tools
- Relations are marked asserted (declared) or inferred (derived from traces)
- Demo: browse agents on the map; the recommendations page lists cost_spike items
- Demo: the catalog page shows one agent entry

Notes:
The sandbox generator creates this synthetic catalog deterministically from a seed. In the Viewer walkthrough you open the map page and then the catalog page; the map has no spike overlay. The cost_spike recommendations list several agents with unknown projected change and insufficient history, so do not present that list as identifying the seeded spike agent. Stay on the synthetic data and point at the isolation banner if the sandbox mode is on. Do not say anything about the size of a real customer estate.

---

# Telemetry in, with limits stated
Claims: C05, C06

- Reference connectors: Azure Monitor and Log Analytics, APIM gateway logs, Foundry discovery, Cost Management exports, generic OpenTelemetry and CloudEvents
- A coverage page publishes the documented API, granularity and limits for each connector
- No connector has run against a live provider (gate G04 open)
- Messy input (duplicates, out-of-order, malformed) goes to quarantine and can be replayed

Notes:
Read the coverage page before answering any question about a provider. If a provider is not listed there, say it is not documented as built. The Admin walkthrough shows the quarantine and replay behaviour using injected bad events in the sandbox. Live runs against real provider environments need operator approval and are separate gates.

---

# Cost that admits what it does not know
Claims: C04, C07

- Unknown stays unknown: a missing value is null, never zero by default
- Estimated and invoiced spend are kept distinct
- Cost records carry a price version
- Demo: a persona with data.read compares cost sources for a seeded spike on the reconciliation page (Auditor access to be verified)

Notes:
The point for evaluators is honesty about cost data. Do not quote any dollar figure or percentage as a benefit. The seeded spike in the sandbox is an injected test condition, not a customer result.

---

# Recommendations and human review
Claims: C08

- Consolidation candidates are labelled candidate and are never auto-merged
- Unused agents are those that are active with zero telemetry for the window
- A steward reviews each item in a review queue

Notes:
The Steward walkthrough uses the duplicate agent candidates scenario. Stress that the system proposes and a person decides. Avoid saying how accurate the candidates are; no accuracy figure is cited in this deck.

---

# One path for governed actions
Claims: C09, C10, C11

- The executor rechecks permission, honors approvals, audits, and verifies the real change; the seeded demo stops before execution
- The MCP server has no confirm, execute or approve tool: an agent can draft, a human confirms
- In repo: analytics adapters accept no query text, so no LLM-generated SQL reaches the engine
- Planned: copilot controls (sandboxed charts, model drafts and does not execute)

Notes:
Review-queue buttons and MCP share the same durable action executor, so there is one place where permission is rechecked and the outcome is verified; the chat route is not merged. Seeded demo intents stop at awaiting confirmation and the screen reads that nothing will be changed. The threat model marks the chart sandbox and model-drafts-action controls as planned; check the threat model status column before answering detailed questions, and say what is not live-verified.

---

# Access is scoped
Claims: C13, C22

- Access follows grants in the policy store
- No unrestricted bypass for any role, privileged roles included
- The Viewer role is read-only: no action, export or edit path
- Hidden navigation is not authorization; the API must deny

Notes:
Five personas: Viewer, Analyst, Steward, Admin, Auditor. Each sees a workspace scoped to its grants. If asked about identity provider integration, say live identity behaviour is covered by separate live gates and is not demonstrated in the sandbox.

---

# Accessible by design, tested honestly
Claims: C14

- Automated axe checks across every registered route in light, dark and high-contrast modes
- WCAG 2.2 AA and Section 508 rule tags used as the test basis
- This is test evidence, not a conformance statement
- No VPAT or conformance report exists; manual checklists are not yet signed

Notes:
Do not say the product is accessible-certified or conformant. Say what was tested and that human testing is still pending. Manual keyboard and screen reader checklists are prepared and unsigned.

---

# Government: gated, not assumed
Claims: C15, C16, C17

- Unsupported cloud, region or feature combinations are disabled with a reason from the capability matrix
- Availability, GA and authorization are separate questions
- NeuroSphere is not FedRAMP authorized and cannot grant an agency ATO
- Authorization support documents exist: control mapping, SSP narratives, POA&M template

Notes:
Never imply that a feature available in Azure Government is therefore available in NeuroSphere on Government, and never imply that anything here is authorized. The authorizing official at the customer agency makes that decision. The support documents help the customer prepare; they do not make the decision.

---

# Planning targets
Claims: C18

- Targets, to be measured and not promised
- Target: regional core API availability 99.9%
- Target: dashboard p95 <=2s on bounded 90-day aggregates
- Target: catalog p95 <=500ms on indexed scoped queries
- Target: map freshness p95 <=10s after normalized ingestion

Notes:
These are planning targets from the requirements document. They have not been measured in a customer environment and are not results. If someone asks for measured results, say none are cited in this deck. Provider billing freshness depends on the connector and is not within these targets.

---

# Try it: the sandbox demo path
Claims: C19, C20, C12

- Five persona walkthroughs, each tied to a seeded sandbox scenario
- Scenarios: cost spike, latency regression, duplicate agent candidates, bad events
- Runbooks and references cover install, operations, security, migration, DR, API, MCP and SDKs
- Synthetic sandbox data, never production data

Notes:
The walkthroughs are marked DRAFT. Run a persona script from the marketing scripts folder against the sandbox as written, and stop if a screen does not match. Never use production data in a demo.

---

# What we do not claim
Claims: C16, C21

- We do not claim FedRAMP authorization, an ATO, or Commercial and Government parity
- We do not claim savings figures, uniqueness or completeness
- Waived by the owner for demo scope: brand, legal and accessibility review (gate G09); none was performed. Still open: an independent new-user test
- Open: live runs against real provider environments need operator approval

Notes:
Close by naming what is still open. The deck front matter stays at draft status because no claims row had an independent reviewer. The owner waived gate G09 for demo scope on 2026-11-03; brand and legal review of this deck has not happened.
