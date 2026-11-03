# Claims checklist: walking deck

Every factual claim in `deck.md` (front matter `claims:` list), the slides that use it, the
document that supports it, and its reviewer. The deck stays `status: draft` while any row
reads UNREVIEWED. A claim with no supporting document is removed, not left as a TODO.

This table is generated from the deck front matter and checked by
`tests/marketing/test_deck_claims.py` (ids, slide references and doc paths must agree).

| ID | Claim | Slides | Supporting doc | Reviewer |
|---|---|---|---|---|
| C01 | NeuroSphere is a customer-hosted AI governance platform for Azure Commercial and Azure Government. | 1, 2 | `docs/index.md` | UNREVIEWED (pending independent review) |
| C02 | Stated objectives: discover registered and observed agents, explain ownership, models, grounding and cost, surface evidence-backed recommendations, enable governed actions, give operators a live ecosystem view. | 2 | `docs/PRD.md` | UNREVIEWED (pending independent review) |
| C03 | The synthetic sandbox generator produces a catalog of domains, owners, agents, model deployments, grounding sources and tools, with asserted and inferred relations. | 3 | `sandbox/README.md` | UNREVIEWED (pending independent review) |
| C04 | Missing fields stay null or unknown, never zero by default; cost records distinguish estimated from invoiced spend and carry a price version. | 5 | `docs/PRD.md` | UNREVIEWED (pending independent review) |
| C05 | Reference connectors are documented for Azure Monitor and Log Analytics, APIM gateway logs, Foundry discovery, Azure Cost Management exports and generic OpenTelemetry and CloudEvents; coverage and limits are published and some entries are not live-tested. | 4 | `docs/connectors/coverage.md` | UNREVIEWED (pending independent review) |
| C06 | The Admin walkthrough injects duplicate, out-of-order and malformed events so quarantine and replay can be observed. | 4 | `docs/walkthroughs/admin.md` | UNREVIEWED (pending independent review) |
| C07 | A persona with data.read can compare cost sources for a seeded spike window on the reconciliation page; access for the Auditor role is to be verified. | 5 | `docs/walkthroughs/auditor.md` | UNREVIEWED (pending independent review) |
| C08 | Consolidation candidates are always labelled candidate and never auto-merged; unused agents are agents that are active with zero telemetry for the window. | 6 | `docs/walkthroughs/steward.md` | UNREVIEWED (pending independent review) |
| C09 | A decision shows the exact target and diff, rechecks permission, honors approvals, audits, and verifies the real change. | 7 | `docs/walkthroughs/steward.md` | UNREVIEWED (pending independent review) |
| C10 | The MCP server exposes bounded structured tools and has no confirm, execute or approve tool; a human confirms through the same durable action executor. | 7 | `docs/reference/mcp.md` | UNREVIEWED (pending independent review) |
| C11 | No LLM-generated SQL, Cypher, KQL or JavaScript; charts are a Vega-Lite subset in a sandboxed iframe; the model drafts an action and does not execute it. | 7 | `docs/security/threat-model.md` | UNREVIEWED (pending independent review) |
| C12 | The Viewer walkthrough uses the map page to see which agents are involved in a seeded cost spike and the catalog page to read an agent entry. | 3, 12 | `docs/walkthroughs/viewer.md` | UNREVIEWED (pending independent review) |
| C13 | Access is scoped by grants in the policy store; there is no unrestricted bypass for any role; the Viewer role has no action, export or edit path. | 8 | `docs/walkthroughs/viewer.md` | UNREVIEWED (pending independent review) |
| C14 | Automated axe tests with WCAG 2.2 AA and Section 508 rule tags cover every registered route in light, dark and high-contrast modes; this is test evidence, not a conformance statement, and no VPAT exists. | 9 | `docs/accessibility/README.md` | UNREVIEWED (pending independent review) |
| C15 | Unsupported cloud, region or feature combinations are disabled with a reason from the capability matrix, not routed to another cloud; availability, GA and authorization are separate. | 10 | `docs/ARCHITECTURE.md` | UNREVIEWED (pending independent review) |
| C16 | NeuroSphere is not FedRAMP authorized and cannot grant an agency ATO; agency authorizing officials make that decision. | 10, 13 | `docs/PRD.md` | UNREVIEWED (pending independent review) |
| C17 | Control mapping, SSP narratives and a POA&M template exist as documents that support, and do not make, the authorizing official's decision. | 10 | `docs/RESEARCH-AND-GATES.md` | UNREVIEWED (pending independent review) |
| C18 | Planning targets, to be measured and not promised: regional core API availability 99.9%; dashboard p95 <=2s on bounded 90-day aggregates; catalog p95 <=500ms on indexed scoped queries; map freshness p95 <=10s after normalized ingestion; browser target <=2k visible nodes at >=30fps. | 11 | `docs/PRD.md` | UNREVIEWED (pending independent review) |
| C19 | Five persona walkthroughs (Viewer, Analyst, Steward, Admin, Auditor) each name a sandbox scenario and are marked DRAFT. | 12 | `docs/walkthroughs/viewer.md` | UNREVIEWED (pending independent review) |
| C20 | The documentation set includes install, operations, security, migration and DR runbooks, and API, MCP and SDK references. | 12 | `docs/index.md` | UNREVIEWED (pending independent review) |
| C21 | Gate G09 (theme, brand and media review) is OPEN; the walkthroughs have not passed an independent new-user test. | 13 | `docs/RESEARCH-AND-GATES.md` | UNREVIEWED (pending independent review) |
| C22 | Hidden navigation is not authorization: the API denies regardless of what the UI shows; theme is never permission. | 8 | `docs/security/threat-model.md` | UNREVIEWED (pending independent review) |
