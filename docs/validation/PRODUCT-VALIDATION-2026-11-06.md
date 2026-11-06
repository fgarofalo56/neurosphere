# NeuroSphere product validation, 2026-11-06

Consolidates four lane reports (`lane1-*.md` .. `lane4-*.md`) written against `docs/validation/RUBRIC.md`.
Method: read-and-run agents traced each capability from UI route to API router to store to real data
source and ran targeted tests. **No lane ran the composed app, the Cosmos emulator, the real-stack
suite or a browser against the real API.** Every test result below is against in-memory fakes. This is
stronger than the 2026-11-04 audit (`PRPs/reports/audit-deep-2026-11-04.md`, static only) but it still
cannot prove anything works on real data. The next step for confidence is to run the composed app.

## Verdict

Across roughly 105 capability rows: about 14 WORKS, 65 PARTIAL, 3 MOCK-ONLY, 11 MISSING, 14 UNVERIFIED.
Almost every WORKS row is qualified "in-memory", "static data" or "synthetic only". The honest reading:

- The pieces are mostly real code with real tests. The **product** is not usable by an enterprise:
  nothing can be set up from the product, real data cannot reach most pages without hand-edited files,
  and the write side is off.
- It is not an all-in-one tool today. It is a library and API platform with a UI over mock or seeded data.

What WORKS with evidence (all qualified): authz derivation and fail-closed behaviour, per-domain audit
hash chain, catalog versioning and ETag concurrency, HITL queue and maker-checker, recommendations list
and review (over seeded data), OpenAPI and its drift test, theme packs, the static capability matrix, and
one narrow live action (the G05 Foundry model swap on 2026-11-05).

## The operator-setup finding (the product owner's central complaint)

There is **no admin console, no first-run wizard and no setup UI**. Setup is Bicep or Helm parameters,
about 60 `NS_*` environment variables, JSON files and operator scripts; `/readyz` JSON is the only view
of what is unconfigured. Specifically:

| An admin cannot do this in the product | How it is done today |
|---|---|
| Assign or revoke a role or domain scope | One principal at a time with `scripts/sandbox/sbx_grant_operator.py`; `policy.py:108-114` refers to an "audited admin path" that does not exist; `POLICY_MANAGE` and `GRANT_WRITE` have no route |
| Register an ingest producer or data source | Hand-written hashed-secret JSON (`NS_INGEST_PRODUCERS_FILE`); unset means every ingest route returns 503; the hosted demo does not set it |
| Add or run a connector | Connectors are libraries; only the APIM connector has a runner (`gateway_poll`, env-only, never run live); Foundry, billing and OTel connectors have no caller |
| Register a gateway | Raw `POST` to the API; the Gateways page lists only |
| Create catalog entities | API only (`POST /catalog/entities`, `/import`) or the sandbox seed script; no UI page calls them; no discovery runs |
| Define evaluation suites, datasets, judges | Files; the API is read-only; the only judge is a recorded fixture |
| Set HITL SLAs, escalation, expiry | Hard-coded defaults (`ReviewPolicyRegistry()` built with no arguments) |
| Configure the copilot and its model | Env or Bicep (`NS_COPILOT_MODE` defaults to `disabled`, every route 503s); never run against a real model (G16 OPEN) |
| Set budgets, price sheets, retention, legal hold, domains, branding | Files, seed scripts or compile-time `packs.ts`; not configurable in UI or API |
| Turn on deployment scan, MCP server, write targets | Env flags that are off in compose, Helm and the hosted demo (`NS_SCAN_ENABLED`, `NS_MCP_RESOURCE_SERVER_URL`, `NS_FOUNDRY_ENABLED`, `NS_APIM_ENABLED`) |
| See the audit log with search or export | `/audit` has no search or export; SIEM export is stdout or file only |

The existing "admin" pages are thin: `/workspaces/*` return `items=[]` and print "Placeholder";
`/workspaces/admin` administers nothing; `/admin/execution-control` is a kill switch; `/mcp-admin` registers
servers whose tools nothing calls.

## Root causes (extends the 2026-11-04 audit's seven)

1. No real data path (audit root 1): producers unconfigured, catalog starts empty, recommendations read sandbox
   NDJSON via `NS_WORKER_REC_DATA_DIR`, no price table, connectors uncalled.
2. Write side inert (audit root 2): zero write targets registered in every shipped profile; buttons, chat
   and MCP produce advisory intents only.
3. Everything off by default (audit root 3), with no UI to turn it on.
4. **No operator control plane** (new): identity policy writes, producers, connectors, domains, budgets,
   policies, model endpoints, first-run. No PRP covers it; the PRD asks only for "setup runbooks".
5. Mock-only end to end (audit root 4): Playwright's only web server is the mock API.
6. Search has no backend (audit root 5).
7. Security audit holes (audit root 6): denials, SIEM, push revocation.
8. Live gates open (audit root 7): G01, G02, G04, G05 (once), G06, G07, G12, G16, G17 (phases 1-4 only).
9. **No delivery to Azure** (new): no workflow deploys main to the hosted environment; `hosted_demo.py` is run
   by hand; both v0.1.0 releases are drafts; the hosted demo is the 2026-10-28 build.
10. **Tracker is not a truth source** (new): 14 PRPs are in `PRPs/backlog/` although their PRs merged (reopened
    by the audit); acceptance checkboxes are unreliable; PRP-06 is shipped without its policy-write path.

## Capability gaps against comparable products (decision 2026-11-06)

Compared with a competitor's published claims (SolidCore): NeuroSphere has no cloud coverage beyond Azure
(no AWS Bedrock connector), no compliance-framework mapping (NIST AI RMF, SR 11-7, FINRA, HIPAA, OMB M-25-21),
no PII-exposure or content-filter configuration checks, and no working shadow-AI discovery. Prompt and
response capture is excluded by design (PRP-33). **Decision: keep metadata-only and add compliance mapping.**

## Proposed re-plan (a proposal; nothing is scheduled until approved)

Order follows the audit's advice (composition first) and puts the operator control plane before more features.

1. **Operator control plane (new PRP).** Identity and policy write path with audit (closes the PRP-06 gap);
   producer and connector registration with credential references (vault or managed identity); domain and
   budget and price-sheet management; model endpoint and copilot configuration; feature enablement with
   `readyz`-driven first-run checklist; admin pages that actually administer.
2. **Real data path.** Connector runners (Foundry discovery, billing, OTel, APIM) as supervised worker roles;
   catalog discovery from real sources; recommendations and evaluation reading live data; hosted roles enabled.
3. **Write side on, gated.** Write-target registry populated by configuration; approvals; verify-by-change.
4. **Real-stack e2e.** Playwright against the composed API and Cosmos/Event Hubs emulators; compose-gated tests
   in CI; this is what turns PARTIAL into WORKS.
5. **Delivery.** Release from main, build, deploy to the hosted environment by pipeline; smoke on every deploy.
6. **Security audit holes.** Denial auditing, SIEM export, push revocation.
7. **Compliance mapping and detections (from the competitor decision).** Control library and evidence bundles
   for NIST AI RMF, SR 11-7, HIPAA, OMB M-25-21; PII and content-filter configuration checks from metadata and
   platform configs; shadow-AI discovery; Bedrock connector. Metadata only.
8. **Live gates** under operator approval (G17 observe join first).

Fix the tracker first (PR #182 makes `/prp:prp-next` enforce dependencies). After this validation, PRP
statuses should be reset from this register, not from PR merges.

## Open questions carried from the lanes

Where retention, the evaluator model and the legal-hold flow are configured (lane 4); whether the projections
worker ever creates Agent entities in a composed run (lane 2); relationship-conflict items go to a
`catalog_review_queue` that no route lists (lane 2); PRP-32's runbook still says all live steps are OPEN.
