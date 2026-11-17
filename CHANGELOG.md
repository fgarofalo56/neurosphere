# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). The release process is in `docs/release/release-process.md`.

## [Unreleased]

## [0.1.0-rc.3] - 2026-11-16

### Added
- **prp-62:** AWS Bedrock reference connector (metadata only) (#317)
- **prp-61:** configuration detections and shadow-AI discovery (#318)
- **prp-63:** delivery pipeline to the hosted environment (#316)
- **prp-51:** composition and API hygiene (#319)
- **prp-60:** search indexing hardening (#311)
- **prp-55:** real deploy apply through the action executor (#314)
- **prp-58:** hosted data path switches, connector RBAC and G04 gate script (#312)
- **prp-57:** admin console data sources, pricing and feature settings (#313)
- **prp-59:** deploy and Government follow-ups (#307)
- **prp-56:** compliance control library and evidence bundles (#308)
- **prp-54:** write targets from stored configuration (#310)
- **prp-53:** admin console identity, domains, system status and audit search (#309)
- **prp-52:** CI and infrastructure hardening (#302)
- **prp-50:** connector SDK and data-path follow-ups (#300)
- **prp-49:** per-agent aggregates and map node metrics (#301)
- **prp-45:** system status, first-run checklist and stored feature settings (#303)
- **prp-46:** cost-center attribution and ingest follow-ups (#296)
- **prp-44:** platform configuration (domains, budgets, price sheets, review policy) (#297)
- **prp-48:** authorization and audit-chain hardening (#299)
- **prp-47:** frontend shell fixes and test infrastructure (#298)
- **prp-43:** catalog hardening and relationship review queue (#292)
- **prp-42:** connector configuration with credential references (#293)
- **prp-41:** ingest producer registry with show-once secrets (#290)
- **prp-40:** audit search, export, denials view and Event Hubs SIEM sink (#291)
- **prp-18:** bulk map edges, replay guard, gateway cadence, map nits (#280)
- **prp-21:** admission wiring, federation hardening, FinOps t-band, pilot re-run (#282)
- **prp-15:** archive series source, held-out measurement and #133 race fixes (#281)
- **prp-39:** identity admin API and block-until-lifted revocation (#283)
- **prp-65:** admin permissions, policy write repository and admin_config store (#277)
- **prp-23:** data lifecycle runtime, dry-run by default (#276)
- **prp-11:** analytics adapters runtime, product executor, Synapse windowed quantile (#275)
- **prp-38:** real stack stack-up order, seed fixes and real-stack CI workflow (#278)
- **prp-68:** changelog fragments and INDEX freshness check (#270)
- **prp-37:** admin v1 contracts, cost tags, query entities, error codes and manifest caps (#273)
- **docs-assistant:** publish image on release, compose profile and operator runbook
- **docs-assistant:** Azure OpenAI model client with abstention and 503 model_unavailable
- **connector-sdk:** write-connector contract-kit profile (PRP-09 r2 item 14)
- **workers:** billing_export role feeds reconciliation (PRP-09 r2 item 12)
- **workers:** foundry_discovery role (PRP-09 r2 item 11)
- **otel-connector:** harden otel-generic (#49) and compose the collector (PRP-09 item 10)
- **catalog:** reason-code picker, shared stale confirm, entity create and edit (PRP-31 item 10)
- **catalog:** optional closed reason_code on deprecate and recertify (PRP-31 item 9)
- **ui-adapters:** domain-path catalog entity create and update (PRP-31 item 13)
- **evaluation:** point-read get_result on evaluation stores (PRP-19 r2 item 16)
- **runtime:** close PRP-05 audit gaps (telemetry, worker roles, readiness) (#184)
- **gates:** G17 --tag option for resource group tag policies
- **frontend:** gateway observe UI and Grant/McpServer catalog renderers (PRP-33 item 7, closes #147)
- **prp-33:** wire NS_GATEWAY_POLL_METRICS_APP_ID into gateway_poll
- **prp-33:** query App Insights customMetrics for gateway cost-center attribution
- **workers:** gateway_poll joins all as a safe no-op when unconfigured
- **actions:** run review-reconcile sweep in the actions role; scope kill switch to control domain
- **actions:** review-reconcile sweep for stale and orphan maker-checker items
- **auth:** close PRP-06 composed-app audit gaps (D1-D5) (#172)
- **ingest:** wire compose workers for ingestion and add synthetic price table
- **runtime:** compose search/write env, runtime-composition runbook and smoke test (PRP-35 item 5)
- **actions:** register write targets from settings in API and workers (PRP-35 item 4)
- **seed:** compose catalog seeder, local-only and idempotent (PRP-35 item 2)
- **search:** NS_SEARCH_PROVIDER catalog search backend and indexer (PRP-35 item 3)
- **ingest:** dev producers file for compose, Helm producers mount, runbook (PRP-35 item 1)
- **video:** PRP-27 captioned explainer video render (local, zero cost) (#163)
- **marketing:** local zero-cost render backend for the explainer video (PRP-27)
- **video:** guarded render entry point with stub backend, captions, spend cap
- **marketing:** add asset manifest and path test (PRP-26 item 4)
- **marketing:** PRP-26 item 1 walking deck source, PPTX and claims lint
- **marketing:** persona demo scripts and feature-to-persona map (PRP-26 item 2)
- **marketing:** explainer video storyboard, script and claims source (PRP-26 item 3)
- **docs-assistant:** public docs assistant service (PRP-25 item 4)
- **docs:** PRP-25 item 1 docs site (ADR-0008, mkdocs.yml, Pages workflow)
- PRP-31 missing UI surfaces (12 routes + UI adapters) (#150)
- **apim:** PRP-34 item 10 wiring and hand-offs
- **frontend:** PRP-34 item 8 manage UI (plan preview, mode switch, publish buttons)
- **gates:** PRP-34 item 9 G17 manage live gate script (not run, OPEN)
- **apim:** PRP-34 item 6 MCP server publish and unpublish
- **prp-34:** item 3 model swap via APIM backend, canary probe, worker wiring
- **prp-34:** grant publish and unpublish (item 5)
- **apim:** PRP-34 item 4 budget_cap_change on grant targets
- **gateway:** PRP-34 item 2 manage-mode switch and write preflight
- **contracts:** admit gateway write action kinds in connector manifests (PRP-34 item 1b)
- **connectors:** PRP-34 item 1 APIM gateway write connector core
- **infra:** PRP-34 item 7 APIM v2 SKUs, created-only diagnostics, optional MCP front
- **api:** gateway plane builder in the runtime composition (PRP-33 item 9)
- **workers:** gateway_poll role feeds APIM gateway logs through the ingest API (PRP-33 item 4)
- **gates:** G17 APIM observe live gate script, evidence README and gate row (PRP-33 item 8)
- **gateway:** observe-mode APIM gateway registry, preflight and inventory (PRP-33 item 6)
- **contracts:** Grant and McpServer catalog contracts, grants_access_to relation, grant permissions (PRP-33 item 5)
- **connectors:** APIM gateway and MCP log source kinds in the Azure Monitor connector (PRP-33 item 3)
- **core:** APIM gateway suffix and ARM client factories (PRP-33 item 2)
- **capabilities:** APIM tier and feature matrix rows (PRP-33 item 1)
- **gates:** hosted_demo deploy --resume-failed recovers ownership after a failed S3

### Changed
- **catalog:** type the service reason_code as the closed ReasonCode literal

### Fixed
- **docs:** publish the theme assets and brand the docs site
- **docs:** keep the release DoD checklist internal
- **images:** copy foundry and azure-billing connectors into every uv --frozen image
- **connectors:** keep _tracked type-transparent so write connectors satisfy WriteConnector
- **workers:** billing_export posts closed billing months only (PRP-09 r2 item 15)
- **connector-sdk:** harden Python and TS SDKs (PRP-09 r2 item 9, #48, #50)
- **connector-sdk:** strict write-verify semantics (PRP-09 r2 item 8, #47)
- **azure-monitor:** hold watermark on truncated slices, keep slices on 429 (PRP-09 r2 item 7, #46)
- **egress:** absolute nslookup names; label-based audience check (PRP-20 r2 item 7)
- **capabilities:** refuse Government regions outside the evidence-backed set (PRP-20 item 5)
- **gates:** confine G01 --evidence-dir to the evidence root (#101)
- **gates:** G02 profile teardown survives timeouts and bad JSON; add approved-path tests (#99)
- **frontend:** forecast 409 unavailable state and real-stack spec fixes (PRP-31 item 15)
- **audit:** source-qualified per-domain audit chains (PRP-31 item 14b)
- **copilot:** evidence reader fails closed on store errors (PRP-19 r2 item 9 rework)
- **deploy:** regenerate API reference, keep apply prompts out of empty-state audit (#188)
- **gates:** G17 live-run defects found across eight real attempts; record partial result
- **prp-33:** register /gateways/detail in route-count test, call map and demo audit
- **deps:** bump oauthlib 4.0.0 to 4.0.1 for CVE-2026-49272 (HIGH)
- **mcp-client:** harden SSRF, host normalisation, credential headers and auth errors (#112)
- **mcp:** scope-derive MCP listings, answer metadata preflight, window derived draft keys
- **mcp:** audit sync revocations and blocked names, bound admin list, bind /mcp exemption (#113)
- **workers:** actions role sweep must be customer-scoped, never unscoped
- **actions:** customer-level kill switch and resumable rejections (PRP-17 close-out)
- **ingest:** regenerate API reference, pin price-table mount, document v2 id upgrade
- **ingest:** restrict invoiced to billing sources, collision-safe ledger ids, request id check
- **ingest:** harden normalizer ids, watermark, cloud default and duplicate metric
- **prp-35:** satisfy single-executor-path and no-commercial-host guards
- **prp-35:** copy foundry-actions into production api and workers images
- **frontend:** drop entrance motion on the governed-change confirm dialog
- **prp-26:** do not attribute reconciliation demo to Auditor role
- **marketing:** make storyboard pass the shared claims lint (PRP-26)
- **prp-25:** CI findings - image build context, CodeQL, gitleaks fixture
- **docs-assistant:** clear pyright errors and refresh licence register (PRP-25)
- **codeql:** clear the three PRP-34 error alerts
- **prp-34:** close the three full-suite regressions found by verify-gates
- **apim:** judge the pool canary within the priority group; pass mode in grant tests
- **gateway:** mode route needs only scoped action.propose (PRP-34 item 2 rework)
- **apim:** restore found resources after a lost update or delete response
- **infra:** PRP-34 item 7 rework: diagnostics dependsOn apim, keep Authorization on own MCP front
- resolve CodeQL error and warnings on PRP-33 code
- **ci:** PRP-33 CI follow-ups: copy azure-monitor connector into images, gitleaks fixtures, viewer grant.read
- **api:** gateways container in the registry and one meaning for auto (PRP-33 item 9)
- **gates:** keep G17 evidence dir inside the repo unless overridden (Snyk CWE-23)
- **demo:** point the API /readyz probes at the real private hosts
- **gates:** deploy passes copilotMode via --copilot-mode (default disabled)
- **demo:** copilotMode param defaults to disabled; smoke uses PT5M and reports az errors
- **gates:** live-run fixes for hosted demo (role ids, KV ref refresh, register-bound revoke)
- **frontend:** let trace tree items take their accessible name from content
- **gates:** resume NIC ownership requires the exact <pe>.nic. prefix
- **infra:** demo endpoint outputs read module outputs, not out-of-template references

### Security
- **security:** gitleaksignore the OTel collector endpoint false positive
- **security:** ignore four unfixable sqlite-libs High CVEs in the Alpine base (#170)
- **security:** allow the two APIM child modules without a publicNetworkAccess switch (PRP-34 item 7 follow-up)

### Unclassified
- PRP-19 round 2 item 15: loop test cites a seeded evaluation result via get_result
- PRP-19 round 2 item 15: copilot real-stack loop test and G12 evidence
- PRP-19 r2 item 12: harden outbound redaction (phones, addresses, credentials, call ids)
- PRP-19 round 2 item 8: Commercial copilot matrix rows, compose passthrough, copilot runbook
- PRP-19 r2 item 13: chat UI fixes (error terminal, first-token clock, selection provider, status)
- PRP-19 round 2 item 11: reports hardening
- PRP-19 round 2 item 10: query_spec on chart events and GET /copilot/status
- PRP-19 round 2 item 9: store-backed copilot EvidenceReader wired in the builder
- PRP-19 r2 item 14: propose_action evidence refs must resolve; empty in filters refused
- PRP-16 round 2: evaluation audit gap closure (items 7-15) (#200)
- PRP-10 round 2: catalog audit gap closure (items 8-13) (#192)
- PRP-34 audit gap closure: recorder wiring, plan steps in confirmation dialog (#191)
- PRP-08 audit gap closure: scan enablement, audit/consent, apply + uninstall preview, UI step (#186)

_177 maintenance commits omitted._

### Release notes by change (curated entries moved from Unreleased)

### Added
- Contracts revision for the control plane (PRP-37, PR #273): new `admin/v1` schema family (credential reference, admin config documents, role, domain and grant change requests, revocation, producer, connector, domain, spend budget, price sheet, review policy, system setting, first-run checklist) with generated bindings and a no-credential-values walker; `CostRecord.tags`; structured query entities `grant`, `mcp_server` and relation `grants_access_to`; error taxonomy 1.1.0 (`not_found`, `method_not_allowed`, `payload_too_large`, `internal_error`) with core error classes; connector manifest caps; additive-only baseline test. API emission of the new codes is tracked in #272.
- Tracker and docs truth-up (PRP-36, PR #271): README, decision D1 and the master index now say the repository is public and cover waves W11 to W21; gate register, threat-model rows and test paths corrected; new `docs/dev/env-example-process.md`; the pre-commit hook regenerates `PRPs/INDEX.md`.
- Connector runners and SDK hardening (PRP-09 round 2, PR #221):
  - New worker roles, both part of `all` and idle until configured:
    - `foundry_discovery`: creates draft catalog entities if they are absent, and never overwrites curated ones.
    - `billing_export`: posts closed-month invoiced cost through the ingest edge to the reconciliation `billing` source. The open month is held.
  - Opt-in `otel` compose profile running the OpenTelemetry Collector (0.165.0) with body attributes dropped.
  - Contract-kit conformance for all six reference connectors, with a new write-connector profile.
  - Operator CLI `scripts/connectors/billing_variance.py`.
  - Fixes:
    - #46: Azure Monitor no longer skips truncated slices.
    - #47: strict `WriteConnector` verify.
    - #48 and #50: SDK hardening.
    - #49: OTel edge cases.
  - G04 stays OPEN (no live provider run).
- Docs site and public docs assistant audit-gap closure (PRP-25 round 2, PR #223):
  - GitHub Pages enabled; https://fgarofalo56.github.io/neurosphere/ now publishes the adopter set (runbooks, walkthroughs, API/SDK/MCP reference, operations, security runbooks, release, connectors, architecture and gates). Evidence, validation and internal planning stay unpublished.
  - The site was unstyled since it first shipped (`exclude_docs: /*` also dropped the theme's CSS/JS). Fixed and branded with the product palette; the docs workflow now fails if theme assets are missing.
  - Docs assistant: Azure OpenAI v1 model client (keyless Entra or key read from a named env var, per-cloud endpoint allowlist, no tools, abstains with `ABSTAIN`, 503 `model_unavailable` on model failure). Image published by `release.yml`; opt-in `docs` compose profile on 127.0.0.1:8091; operator runbook.
  - Live smoke against a throwaway gpt-5-nano deployment passed (evidence under `docs/evidence/PRP-25/`). An automated clean-room install run is recorded; the human new-user test stays OPEN.
- Government sovereign profile audit-gap closure (PRP-20 round 2, PR #216):
  - Government deployment profiles accept only usgovvirginia, usgovarizona and usgovtexas. DoD and unknown regions are refused with a `capability_unavailable` reason.
  - Government audiences recorded from Microsoft Learn on 2026-11-12:
    - AI Search: `https://search.azure.us`.
    - Event Hubs: `https://eventhubs.azure.net/` (the same in every cloud; a token audience, not an egress host).
    - Cosmos DB: still not verified.
  - Hostname (FQDN) egress enforcement is recorded as a customer firewall control and stays OPEN.
  - CI runs the Government helm/az static tests (it fails, not skips, when a tool is missing). A new `egress blocked (compose probe)` job proves 40 Commercial hosts neither resolve nor connect from the isolated compose network. This is static and compose proof only; the in-cluster proof stays OPEN.
  - G02 profile scripts always issue the resource-group delete, even after a cleanup timeout. G01 gate `--evidence-dir` paths are confined to the evidence root.
  - No FedRAMP authorization, ATO or parity is claimed. Live Government runs stay OPEN because there is no Government subscription.
- UI surfaces audit-gap closure (PRP-31 round 2, PR #204):
  - Catalog entities can be created and edited from the UI (`catalog.curate`). This uses new `POST`/`PUT /api/v1/catalog/domains/{domain}/entities` adapters that stamp cloud, customer, domain and id server-side. A body carrying a server-owned key gets 422.
  - Deprecate and recertify take an optional closed `reason_code`, which is stored in the audit record. There is no free text.
  - Stale-agent confirm goes through the shared governed-change dialog.
  - Audit chains are source-qualified, so domains whose source is not `catalog` (for example `sandbox`, `neurosphere`) can now be audited. Catalog chains are unchanged. Domains that share a name across sources no longer share a chain.
  - A forecast with no price version shows "Forecast unavailable: <reason>" instead of "try again".
  - A real-stack integration loop covers every UI-surface mutation and the auditor flow. The real-stack browser spec covers all 41 manifest routes, and the a11y matrix checks `/audit` as an auditor.
- Copilot audit-gap closure (PRP-19, PR #202):
  - Commercial gpt-4.1-mini capability rows: Global Standard in 9 Americas regions and Data Zone Standard in 7 US regions. These record availability only, with no authorization claim. A Commercial approved endpoint is now enabled by the matrix instead of being disabled.
  - Compose passes `NS_COPILOT_*` through and still defaults to `disabled`. A new `docs/runbooks/copilot.md` covers setup.
  - Copilot answers cite real recommendation, evaluation-result and catalog records with freshness, through scoped point reads that fail closed. `EvaluationStore.get_result` is new.
  - A chat chart can be saved as a report: the `chart` event carries the exact query that filled it.
  - New `GET /api/v1/copilot/status`. The chat shows "not configured" with a reason instead of "try again".
  - Reports require `If-Match` on share, unshare and request-publication. They emit audit events for run, share, unshare and publication, and normalize principal ids.
  - Redaction now masks phones, street addresses and credential phrasing.
  - `propose_action` refuses evidence refs that cannot be resolved, and empty filters are refused.
  - Proved on the compose emulators with the real endpoint adapter over recorded provider streams. The live model run is still OPEN. Nothing was deployed.
- Evaluation audit-gap closure (PRP-16, PR #200): the evaluation worker now runs the offline pilot and calibration on a
  schedule, opens HITL `evaluation_dispute` review items for a seeded calibration sample (approve = the judge was wrong,
  reject = the judge was right) and turns decisions into human labels; reviewers see the item, the verdict and the
  rubric (`GET /api/v1/evaluation/domains/{domain}/calibration-samples`, restricted content withheld); an
  `EndpointJudge` for approved chat-completions endpoints (`NS_WORKER_EVAL_JUDGE=endpoint`, cloud-checked, unreadable
  usage charged at the full reservation; the live G16 run is still OPEN); sandbox telemetry carries a classification;
  `/quality` reads a bounded window and flags truncation; the Commercial Foundry base capability row is verified
  (availability only, no authorization claim). Proved on the compose emulators with synthetic data (pilot grounded rate
  0.719, 95% interval [0.546, 0.844], a pilot-set target, not a guarantee); nothing deployed.
- Catalog audit-gap closure (PRP-10, PR #192): the catalog projection now creates the agent, model-deployment and
  tool entities a trace references, so a real stack's catalog fills from telemetry (proved on the compose emulators
  through the ingest edge); lock-expiry lineage refresh, review-queue generations and replay ordering (#54);
  authorization and existence-signal hardening (#53: server-stamped curation actors, non-disclosing duplicate-ID
  errors, scope 403 before schema 422 on create); search hardening, a Government no-silent-fixture guard and
  `NS_SEARCH_PROVIDER` in hosted Bicep and Helm; scoped export p95 measured on the Cosmos emulator (bounded
  feasibility only). Live export p95 and in-region G03 stay open (#57); follow-ups #193-#195.
- APIM gateway manage audit-gap closure (PRP-34, PR #191): the actions worker role now wraps the executor in the
  publication recorder so grant and MCP publications record provenance after a verified apply; the dry-run API and
  confirmation dialog show per-step create/found for APIM plans. Cost-center attribution is descoped to #190 and the
  G17 manage live run stays open.
- Deployment intelligence audit-gap closure (PRP-08, PRs #186 and #188): scan opt-in (`NS_SCAN_ENABLED`) exposed in
  Helm, App Service and `.env.example`; consent no longer trusted from resource tags; scan, plan and consent audited;
  plans can reference a server-side `scan_id`; plan approval, apply and dry-run uninstall preview routes through the
  durable action executor (new `deploy_plan_apply` / `deploy_uninstall` kinds and `DeployConnector`), opt-in via
  `NS_DEPLOY_APPLY_ENABLED` and customer-scoped; deploy wizard Approve/Apply/Uninstall-preview step. Real apply is not
  end-to-end yet (no durable approval store or provisioners wired; routes return 503 unless enabled).
- API and worker runtime audit-gap closure (PRP-05, PR #184): SLO request metrics and traces are now wired
  into the API and worker entrypoints (exporters off in `NS_ENV=local`); non-ingestion worker roles use a
  durable Cosmos checkpoint store; the `lifecycle` role reports an explicit `idle` state
  (`lifecycle_no_job_source`) without failing readiness; the compose worker healthcheck probes `/readyz`.
- APIM gateway observe close-out (PRP-33 audit round): the `gateway_poll` worker role now runs under `all`
  and idles when unconfigured; gateway token usage gains cost-center attribution from App Insights
  `customMetrics` (optional `NS_GATEWAY_POLL_METRICS_APP_ID`, Commercial only); the Gateways page shows
  diagnostics, last sync and freshness, with a gateway detail inventory view and Grant and McpServer catalog
  renderers. The G17 live observe run and item 7 visual baselines remain open.
- Action executor and HITL audit close-out (PRP-17 audit gaps): a customer-scoped reconcile sweep closes
  review items whose intent is terminal or expired, and orphan items; the kill switch
  (`PUT /api/v1/actions/emergency-disable`) needs `config.manage` on the per-customer control domain
  (runbook `docs/runbooks/action-plane-kill-switch.md`); a rejection that hit a policy outage is
  resumable. The G05 live Foundry swap ran on one Commercial target (narrowed, not closed; no canary,
  Government not covered).
- Identity, authorization and audit close-out (PRP-06 audit gaps): denied attempts are audited in the
  composed app with the request correlation id, the SIEM exporter is wired (`NS_AUDIT_SIEM_SINK`,
  default `none`), the revocation hook registry no longer depends on the scope deriver, and the app
  refuses to boot with a route that has no declared permission (websockets need an exact-path guard
  entry). No admin revoke route yet; live token-expiry and revocation-TTL runs are open gates.
- Telemetry ingestion and cost ledger audit close-out (PRP-07 items 7-9): compose workers wired for
  ingestion with a synthetic price table, hardened normalizer ids and watermark, billing-only
  `invoiced`, collision-safe ledger ids (v2 id upgrade, no migration). Live Commercial run is an open gate.
- MCP server and client audit close-out (PRP-22 audit gaps): `tools/list` and `resources/list` are
  scope-derived, the RFC 9728 metadata route answers a preflight, SSRF blocks `::ffff:0:0:0/96` and
  `5f00::/16` and refuses non-ASCII hosts, an upstream 401/403 maps to `forbidden`
  (`mcp_auth_rejected`), sync revocations and blocked registrations are audited, and the injection
  corpus is reported as 18 exercised for real plus 60 not applicable. oauthlib 4.0.1 (CVE-2026-49272).
  The admin UI pass, Government MCP use and MCP-initiated writes (#132) are open gates.
- Runtime composition (PRP-35): ingest producers config for compose and Helm, an idempotent
  profile-gated catalog seeder that refuses outside `NS_ENV=local`, `NS_SEARCH_PROVIDER`
  (fixture, azure or unset) with a catalog indexer, and Foundry model-swap and APIM gateway
  connectors registered into the write registry only when enabled and configured. Live Azure AI
  Search and live Foundry/APIM writes are not run (open gates). See
  `docs/runbooks/runtime-composition.md`.
- Explainer video render (PRP-27): guarded render entry point (refuses without a filled
  `marketing/video/APPROVAL.md`), a zero-cost local backend (Playwright capture, offline Windows
  voice, ffmpeg), committed `captions.vtt` and spend log; the MP4 is stored outside git. The owner
  played it back and approved it on 2026-11-03; G09 stays waived, with no independent review. Some
  storyboard states are not drawn by the sandbox UI.
- Sales and marketing deliverables (PRP-26): `marketing/` walking deck source and a generated PPTX,
  five persona demo scripts tied to the sandbox walkthroughs, video storyboard and narration source
  (not rendered, see PRP-27), an honest asset manifest (nothing marked rendered), and a claims lint
  under `tests/marketing/`. G09 was waived by the owner for demo scope on 2026-11-03 (no independent review was performed).
- Docs site and public assistant (PRP-25): MkDocs Material 9.8.0 site with an explicit page
  allowlist and a Pages workflow (ADR-0008), generated API, SDK and MCP references with a drift
  test, install/migration/operations/DR/security runbooks and five persona walkthroughs (DRAFT
  until an independent new-user test is recorded), and a separate rate-limited read-only docs
  assistant service. Not done: the new-user test and the first Pages deploy are OPEN.
- Missing UI surfaces (PRP-31, #150): twelve governed, accessible routes for capabilities that
  were API-only (catalog explorer, entity, recertifications and stale agents; curation edge
  decisions bound to edge version/ETag; audit trail and chain verification; FinOps forecast;
  federation summary with currencies never summed; deploy scan, plan and capabilities with no
  apply control; evaluation results; execution control), a shared change-confirm dialog, and a
  small `ui_adapters` backend module with domain-path endpoints that never take scope keys or an
  actor from the browser. Known gaps: catalog deprecate/recertify reasons are not stored yet,
  real-API compatibility is proven against the in-memory API and the mock only, and the
  accessibility sign-off (G09) is still OPEN.
- APIM AI gateway, manage side (PRP-34, #149): an `apim-gateway` write connector with
  deterministic digest-bound plans, existence re-read before every write, ownership recorded
  per step and reverse rollback that deletes only what the run created; an audited
  observe/manage switch with a permissions preflight; backend and pool-weight model swaps with a
  priority-group canary cap, budget-cap changes, Grant publication and MCP server publication
  (Entra-only, credentials stripped, deny-first) as real gateway changes; Bicep v2 SKUs, a
  created-only diagnostics module and an optional own-MCP front; the manage UI; and the G17 manage
  live-gate script. Not deployed: no worker or API composition registers the connector yet, and
  the G17 manage live run is OPEN.
- APIM AI gateway, observe side (PRP-33, #146): capability-matrix tier and feature rows
  for API Management, cloud-profile gateway suffix with ARM and Log Analytics clients,
  Azure Monitor connector source kinds for gateway and LLM token logs (bodies never
  projected), `Grant` and `McpServer` catalog contracts with the `grants_access_to`
  relation, an observe-mode gateway registry with read-only preflight and inventory,
  the `gateway_poll` worker role, and the G17 observe live-gate script (live run OPEN).
- Repository hygiene baseline: version-controlled git hooks, gitleaks config,
  CI without suppressed failures, CodeQL, Dependabot, issue/PR templates,
  CODEOWNERS, SECURITY and CONTRIBUTING guides.
- Orchestrated-PRP kit onboarding (`PRPs/`, `.claude/hooks/config.ps1`).
- Local emulator stack (`docker-compose.yml`): Cosmos DB vNext, Event Hubs, Azurite.
- Architecture decision records and decisions log.
- Split PRPs `PRP-00` to `PRP-27` with master index.
- Telemetry ingestion and cost ledger (PRP-07): authenticated OTLP/JSON and CloudEvents
  push edge, normalizer worker with dedupe, watermarks and bounded retries, blob quarantine
  with replay CLI, redacted archive, cost ledger with double-count resolution and outbox.
- Deployment intelligence and IaC (PRP-08): per-cloud Bicep modules with reuse inputs, Helm 4
  chart and App Service profile, consented read-only Resource Graph scan, reuse/create/skip
  planner projecting to `DeploymentManifest`, ownership register with a live-inventory-guarded
  uninstall, matrix-gated Fabric provisioning adapter, and the G01 Commercial deploy smoke gate.
- Connector SDK and reference connectors (PRP-09): Python and TypeScript connector SDKs with
  health/rate-limit/coverage/freshness reporting, vault credential references with rotation,
  a contract test kit and cross-SDK manifest interop; `WriteConnector` protocol for the action
  executor; reference connectors for generic OpenTelemetry/CloudEvents push, bounded Azure
  Monitor polling, Foundry discovery and Azure Cost Management exports with a billing-vs-ledger
  variance report; `docs/connectors/coverage.md`.
- Catalog and relationship governance (PRP-10): versioned `CatalogRepository` on Cosmos NoSQL
  and in memory with ETag concurrency, canonical IDs and aliases, scope-filtered queries and a
  single partition-key configuration point; bounded `GraphQuery` with depth, fan-out, node, edge
  and time budgets and presented lineage; curation decisions and locks with a review queue;
  outbox projection worker producing inferred INVOKES/USES_MODEL edges; catalog API (CRUD,
  search, lineage, import/export, recertification, stale-agent reconcile); Azure AI Search
  `AuthorizedSearch` with a server-side scope filter. G03 live benchmark run on a private,
  Entra-only Commercial account (the harness now provisions through the control plane);
  G03 narrowed for Commercial.
- Analytics adapters (PRP-11): `TelemetryAnalytics` and `RecommendationCompute` contracts with
  required `AnalyticsBudget` (time, rows scanned, cost units; breach cancels and raises
  `rate_limited`), a shared whitelisted-identifier SQL renderer, a matrix-gated registry that
  lists disabled backends with reasons, a sandbox-only fixture adapter, and Fabric, Synapse
  (serverless/dedicated) and Azure Databricks adapters with per-cloud host checks and versioned
  migrations; stub-endpoint equivalence and profile-gating suites (contract conformance only);
  `scripts/gates/g01_analytics_live.py`. Live analytics runs are OPEN for every adapter.
- Threat model and security baseline (PRP-12): STRIDE threat model per trust boundary with
  abuse-case DFDs (`docs/security/`), `security.yml` supply-chain workflow (syft SBOM, Trivy and
  Grype blocking on High, sha256-pinned binaries), Bicep network module with private endpoints for
  created resources only and a release-scoped default-deny Helm NetworkPolicy, a shared
  78-case prompt-injection corpus and harness (`tests/security/injection/`), and secrets,
  rotation, leak-response and incident runbooks. Live what-if is OPEN.
- Release tooling (PRP-13): SemVer policy with the contract and migration version mapping
  (`docs/release/versioning.md`), the operator release process
  (`docs/release/release-process.md`), and `scripts/release/changelog.py`, which builds
  Keep-a-Changelog sections from conventional commits. Multi-stage non-root production
  Dockerfiles for api, workers and frontend; tag-triggered `release.yml` publishing to GHCR
  with syft CycloneDX SBOM attestations, cosign keyless signatures verified in-workflow, the
  Helm chart as OCI and a draft GitHub Release (exercised on `v0.1.0-rc.1`); a versioned
  Cosmos/analytics migrations runner with ledger, rollback, dry run and expand-then-contract
  lint; and a release Definition-of-Done checklist (`docs/release/dod-checklist.md`).
- Dashboards for cost, latency and coverage (PRP-14): a hot-aggregates projection worker
  (90-day rolling day/hour rollups from the outbox, idempotent, null never 0, `complete` and
  watermark on every document) with a core `AggregateReader` store; scoped
  `GET /api/v1/dashboards/domains/{domain}/{metric}` and
  `GET /api/v1/reconciliation/domains/{domain}` APIs (403 outside scope, 503 fail closed,
  bounded budgets, `Server-Timing`); cost, latency/errors, coverage and reconciliation pages
  with estimated/invoiced and price-version badges, lag indicator and analytics-state chip;
  Playwright e2e on the mock API and measured G07 latency evidence
  (`docs/evidence/G07/dashboards/`).
- Recommendations engine (PRP-15): advisory-only, evidence-backed recommendations. Versioned
  bounded rules (cost spike, latency, error rate, unused agent) with no-score
  `insufficient_evidence` on cold start or sparse data and `unknown` coverage never reported as
  unused; read-only duplicate consolidation-review candidates over the presented catalog;
  immutable content-hashed price snapshots and right-sizing estimates that always cite a price
  version; scoped `GET /api/v1/recommendations/domains/{domain}` list, detail and search,
  review routing, and an executions route that always refuses (`capability_unavailable`);
  list and detail pages with advisory badge and route-to-review; sandbox pipeline, Playwright
  e2e and measured G12 evidence (`docs/evidence/G12/recommendations/`).
- Agent evaluation and quality (PRP-16): append-only versioned datasets, rubrics and judge
  configs with fail-closed judge approval (unknown classification is restricted, judge cloud must
  match, capability-matrix availability); a stratified, seeded sampling worker that checks
  classification and reserves worst-case token/cost budget before every judge call and stops
  with `budget_exhausted`; recorded-fixture judges only (no paid calls in CI); human-label
  calibration (agreement with interval, bias, coverage), Wilson intervals and PSI drift alerts;
  scoped `GET /api/v1/evaluation/domains/{domain}/results` and `/quality`; a quality page where
  every score carries judge version, calibration state and uncertainty, unknown is never 0, and
  the grounded-answer rate is a pilot-set target with a confidence interval, not a guarantee;
  sandbox pipeline, Playwright e2e and measured G12 evidence (`docs/evidence/G12/evaluation/`).
- Action executor and human-in-the-loop workflow (PRP-17): one durable action plane for button,
  chat, REST and MCP. Allowlisted intent state machine, PRP-01 confirmation hash bound to target,
  version, diff, expiry and actor (channel excluded), idempotent intent store (in-memory and
  Cosmos), and an executor worker that is the only caller of connector apply/rollback: it
  rechecks permission (token-free, revocation-aware), target version and the emergency kill
  switch, then dry-run, apply, verify-only canary, verify and audit, with rollback on failure,
  crash-safe resume that never re-applies and a lease kept alive across long connector calls.
  Maker-checker review queue with self-approval refused on real principal ids, append-only
  hash-chained decisions, durable SLA/escalation timers and stub notifiers that only record.
  `/api/v1/actions` and `/api/v1/review` APIs, a Foundry deployment-swap write connector with
  advisory mode for read-only or Government targets, and a confirmation dialog showing exact
  target, version, diff and expiry. G05 stays OPEN (live swap not run); production action
  execution remains blocked.
- Live map and session replay (PRP-18): scoped WebSocket gateway at `/api/v1/realtime/ws` fed
  by hot aggregates, with `ns.bearer` subprotocol auth, send-time scope filtering, per-session
  budgets and revocation fan-out that closes sockets (4403). Bounded viewport API at
  `/api/v1/map` (2000-node cap, kind clusters, paginated expansion, pseudonymized people,
  coverage and lag). sigma.js 4 + graphology WebGL map that animates observed edges only while
  the session is live and coverage is fresh, with reduced motion, plus an accessible treegrid
  table on the same API. Read-only trace replay at `/api/v1/replay` with gap, sampling and
  late-span labels and a static ban on action, executor and connector imports. Measured, not
  guaranteed: freshness p95 about 2 s on emulators (poll-interval bound) against a 10 s target;
  38.6-41.8 fps mean at 2k nodes on one documented workstation, with p5 below 30 fps. G07 stays
  OPEN (no live run).
- Copilot and report creation (PRP-19): allowlisted server tool registry that only ever sees the
  server-derived `IdentityScope` (scope-shaped arguments refused and logged), with tool-produced
  citations carrying data freshness. Copilot API at `/api/v1/copilot` streams SSE with
  first-class `abstain` and `denied` terminals, an output guard, chat-only action drafting
  through the PRP-17 executor, and redacted, owner-only conversations with retention.
  `ModelAdapter` protocol with recorded-fixture, approved-endpoint and optional Foundry Agent
  Service adapters behind one action contract, gated by the capability matrix (Government never
  routed to Commercial). Server-validated Vega-Lite subset rendered by `vega-interpreter` in a
  sandboxed iframe under a sha256 CSP. Saved reports at `/api/v1/reports` store plan and query
  only, re-validate and re-authorize as the viewer on every run, and need a second
  `config.manage` principal to publish. Chat dock UI with context chip, citations and inline
  charts. The PRP-12 injection corpus passes 78/78 with 0 overscoped retrievals. First token
  measured, not guaranteed: p95 about 140 ms with recorded fixtures (provider time excluded)
  against a 3 s planning target; live model run OPEN.
- UI shell and usability (PRP-28): Fluent v9 app shell with header, user menu, skip link and
  grouped permission-aware navigation (hiding is not authorization; the API still denies). A
  domain switcher is fed by the new `GET /api/v1/me/domains`, which returns the caller's
  `data.read` domains, derived server-side only. `?domain_id=` stays the source of truth, and
  the last domain id is remembered under a pseudonymous key. Adds the real
  `GET /api/v1/workspaces/{role}` with an explicit role map. Shared page template, and Fluent
  controls on every feature page; a static test allows no native form controls beyond a
  2-entry allowlist. Role-aware overview tiles never sum currencies, never invent counts ("N+"),
  and never show 0 for unknown data. `pnpm demo` runs the UI against the mock API with stub
  sign-in and a demo banner; tests prove neither ships in production builds or deployment
  artifacts. The CI frontend job timeout is now 25 minutes.
- Government verification and sovereign deployment (PRP-20): Azure Government profile
  (`infra/bicep/params/government/sovereign-profile.yaml`, `infra/helm/values-government.yaml`)
  with Government endpoints, audiences, private DNS zones, egress allowlist, allowed regions and
  disabled-with-reason options; a dated per-dependency evidence register
  (`docs/evidence/G02/register.yaml`) with availability, GA and authorization kept separate, and
  a responsibility matrix (not FedRAMP authorized; the authorizing official decides); static
  and compose no-Commercial-egress tests; gated G02 AKS and App Service profile scripts. Live
  Government runs, in-cluster egress proof and agency ATO stay OPEN (no Government
  subscription, D7).
- Scale, federation, FinOps and DR (PRP-21): locust pilot/enterprise/stress load profiles with
  skew, hot-key and fan-out scenarios (`tests/load/profiles/`); per-domain admission control
  library (`neurosphere_core.admission`); scope-filtered, same-cloud federation summaries
  (`/api/v1/federation`); a trend cost forecast that cites its price version and keeps
  estimated, invoiced and unknown apart (`/api/v1/finops`); per-store backup/restore and a
  restore drill (`infra/dr/`) with a failover/failback runbook (`docs/ops/dr-runbook.md`).
  Compose-only measurements are bounded feasibility: the pilot missed its 1k events/s target
  (~240 events/s). Enterprise/stress runs, real failover and production restore stay OPEN (G07).
- MCP server and client (PRP-22): an OAuth 2.1 resource server on the Python `mcp` 2.3 SDK
  (spec 2026-07-28) with RFC 9728 metadata, an explicit `validate_token_resource=True`, a
  separate MCP audience, per-call scope derivation and no token passthrough, exposing read
  tools over the copilot tool registry plus draft/validate/present-confirmation/status action
  tools (no MCP confirm; a human confirms). Streamable HTTP only
  (`neurosphere_api.mcp.server`). An MCP client for administrator-registered HTTPS servers with
  SSRF checks on every resolved address, connections pinned to the vetted IP, bounded and hashed
  tool manifests, approve-before-use with revocation on hash change, and untrusted bounded
  results (`neurosphere_core.mcp`, `neurosphere_api.mcp.client`). Admin API
  `/api/v1/mcp/admin` and UI (`config.manage`, audited). Security suite in
  `tests/security/mcp/`. Government MCP use and live Entra audience behaviour stay OPEN
  (G01/G02); G08 stays NARROWED.
- ATO evidence and data lifecycle (PRP-23): a policy-driven lifecycle engine
  (`neurosphere_core.lifecycle`, `neurosphere_workers.lifecycle`) for retention,
  pseudonymization, deletion, export and legal hold, with a written conflict order (audit
  immutability, legal hold, minimum retention, subject request, maximum retention), fail-closed
  defaults, read-back-verified deletion and a legal hold that also defers subject erasure of
  held data. ATO accelerator documents under `docs/compliance/`: NIST 800-53 Rev 5 mapping and
  SSP narratives, SSP scope with customer inputs OPEN, POA&M template, rendered boundary and
  data-flow diagrams, and IR, contingency, change and continuous-monitoring plans. An idempotent
  evidence inventory (`scripts/compliance/collect_evidence.py`, `docs/evidence/inventory.md`)
  and a disclaimer/claim checker (`scripts/compliance/check_statements.py`). Not FedRAMP
  authorized; the authorizing official decides. G02 and G06 stay OPEN.
- Themes, sandbox mode and accessibility (PRP-24): agency theme packs
  (`frontend/src/design-system/themes/`) for light, dark and high-contrast, with a guarded
  high-contrast set, a logo-slot allowlist (PNG and WebP) and a test that themes never import API or
  auth code; pack and mode persisted per browser with a deployment default. Sandbox mode: an API
  module bound to a fixed allowlist of sandbox containers (`/api/v1/sandbox`), a persisted UI toggle and
  an isolation banner on every route. Accessibility: an axe suite across all 26 registered routes, three
  modes, both packs and sandbox mode, plus an automated keyboard and accessibility-tree pre-check,
  with zero serious or critical findings after fixing link contrast, a high-contrast badge, dialog
  focus restore and the chart frame focus indicator. Manual keyboard and screen-reader checklists
  are prepared and unsigned. No conformance claim; G09 stays OPEN.
- Visual redesign and switchable UI styles (PRP-30): two runtime-switchable styles, Enterprise
  Fluent (default) and Ops console, picked from the user menu or the `defaultUiStyle` runtime
  key and composed with the existing modes and packs. A style may only override allowlisted
  neutral tokens, and only while every PRP-24 contrast guard passes; high-contrast ignores style
  colours. Styles are presentation only, and a test proves both send identical requests. New
  design-system primitives: NeuroSphere mark and wordmark, KPI cards, status pills that wrap,
  health indicators (colour, icon and text), empty/loading/error states, relative timestamps,
  data table, panel, and in-house SVG charts with one chart per currency, estimated dashed vs
  invoiced solid, and unknown drawn as gaps, never 0 (no new dependency). Mockups were approved
  before every page was restyled. The demo banner no longer covers the assistant, the first
  visit lands on a populated domain, and `pnpm demo` runs a richer fixture profile whose mock
  authorizes exactly like the real API. Accessibility: 257 axe checks across styles, modes,
  packs and routes with zero findings; 26 Linux visual baselines compared in the pinned
  Playwright image; CI e2e sharded across two jobs. G09 stays OPEN.
- PRP-32 hosted Azure environment shipped (2026-10-28). It is a persistent Commercial demo in
  the operator's subscription: real Entra sign-in, the real API and workers, private Cosmos,
  Event Hubs, blob and Key Vault through hub private endpoints, and seeded synthetic data. The
  live run produced three fixes:
  - `deploy --resume-failed` recovers ownership after a partial deploy.
  - Seed grants use full role-definition ids; Key Vault references are refreshed after the
    pseudonym secret is created; revoke is register-bound.
  - The copilot defaults to `disabled` until a capability row exists, and the API `/readyz`
    probes target the private hosts instead of localhost.

  Smoke 11/11 and the hosted browser spec 1/1. Teardown and the 403-on-hidden-route check stay
  OPEN (#144). No FedRAMP, ATO or SLA claim is made about the environment.
- PRP-11: the API selects an analytics adapter from `NS_ANALYTICS_BACKEND` (`runtime/builders/analytics.py`), reports it as the optional component `analytics_adapter` and sets `app.state.analytics_adapter`. The product Databricks Statement Execution executor now lives in `neurosphere_core.analytics.databricks.executor`, PR #275.
- PRP-11: Synapse windowed `PERCENTILE_CONT` path for approximate quantiles (#59).
- PRP-15: `NS_WORKER_REC_SOURCE=archive` makes the recommendations worker read telemetry and cost from the redacted archive (`ArchiveSeriesSource`) and agents, owners and duplicate candidates from the live catalog, read-only. `NS_WORKER_REC_LOOKBACK_DAYS` sets the window. The default stays `sandbox`. Truncated or empty archives report unknown coverage and never emit `unused_agent` (PR #281).
- PRP-21 (round 2): per-domain admission limiter wired into the API through `require_permission` (off by default, `NS_ADMISSION_ENABLED`, `NS_ADMISSION_POLICY_FILE`; 429 `rate_limited` with `Retry-After`), peer cells through `NS_FEDERATION_PEERS_FILE` over `HttpCellClient` with boundary host allowlists, https-only and serving-cloud checks, a configurable summary cache TTL ceiling (`NS_FEDERATION_CACHE_MAX_TTL_SECONDS`), a t-quantile FinOps forecast band for small samples, a `/otlp/metrics` load scenario, compose and Helm quota mounts, the `docs/runbooks/admission-and-federation.md` runbook and compose pilot evidence under `docs/evidence/G07/pilot/` (bounded feasibility, 1 of 3 thresholds passed; PR #282).
- PRP-23: lifecycle API (`/api/v1/lifecycle/holds`, `/requests`, `/status`) behind the new `lifecycle.manage` permission, a Cosmos-backed lifecycle job store, and delete backends for the catalog, ledger and archive. The lifecycle worker now runs jobs, in dry-run by default (`NS_LIFECYCLE_MODE`, `NS_LIFECYCLE_POLICY_FILE`, `NS_LIFECYCLE_MAX_ATTEMPTS`), PR #276.
- PRP-23: bounded retry of FAILED queued lifecycle outcomes with backoff, then `failed_final`.
- PRP-38: `.github/workflows/real-stack.yml` runs the real-stack pytest suites against the compose emulators (job `real-stack`) and a headless Playwright run with the in-process dev issuer (job `real-stack-browser`), PR #278. Both are non-required until green for a week.
- PRP-38: `sbx_seed_stack.py --grants-only`, a seeded gateway registration, and headless flow specs for catalog and curation, quality, actions and copilot under `frontend/tests/real-stack/flows/`.
- PRP-39: audited identity admin API under `/api/v1/admin/identity` (list and detail principals, PUT/DELETE role assignments, domain memberships and resource-scoped grants with `If-Match`, scope, self-modification and customer-wide checks), principal revocation routes (POST, GET, DELETE) with `issued_before` and block-until-lifted (`until_lifted`) modes, a composed `RevocationService` with push fan-out, and the `docs/runbooks/identity-admin.md` runbook (PR #283).
- PRP-40: audit search (`GET /api/v1/audit/search`, time range required and capped at 31 days, cursor paging, up to 500 rows), export (`GET /api/v1/audit/export?format=ndjson|csv`, 10000 row cap, `audit.export` permission on every domain read, an `audit.export` chain record per domain before streaming, CSV formula-injection escaping), readable denials (`GET /api/v1/audit/denials`, customer-wide `audit.read` only) and `GET /api/v1/audit/siem/status`. An Event Hubs SIEM sink (`NS_AUDIT_SIEM_SINK=eventhubs`, managed identity only outside `NS_ENV=local`, cloud-profile host suffix, no cross-cloud send) with an optional `audit_siem` component, and auditing of failures before a scope exists (identity-known failures write a `<customer>.authz-denials` record; 401s produce a SIEM signal and a counter only). Runbook: `docs/runbooks/audit-siem.md` (PR #291).
- PRP-41: store-backed ingest producer registry. Admins create, rotate, disable and enable producers through audited routes under `/api/v1/admin/sources/producers` (secret returned once, only a SHA-256 digest stored, `If-Match` on mutations, customer-level `config.manage`). The ingest edge authenticates against the store layered over the producers file, which remains as a fallback; enable with `NS_INGEST_PRODUCER_STORE` and tune with `NS_INGEST_PRODUCER_REFRESH_SECONDS`. New optional readiness component `admin_producers` (PR #290).
- PRP-42: admin API `/api/v1/admin/sources/connectors` to configure the `gateway_poll`, `foundry_discovery`, `billing_export` and `otel` connector roles. Credentials are stored as references only (Key Vault secret URI or managed identity); worker roles read the stored config (stored wins over env, applied on restart) and resolve producer secrets from Key Vault over REST at startup. `NS_WORKER_CONNECTOR_CONFIG_SOURCE=env` restores env-only behaviour. See `docs/runbooks/connector-config.md` (PR #293).
- PRP-43: relationship review queue. `GET /api/v1/catalog/curation/review-queue` and `POST /api/v1/catalog/curation/review-queue/{item_id}/resolve` (needs `catalog.curate` on the item's domain, audited), and a `/catalog/review-queue` page under Governance. Projection candidates that are out of scope or collide with an entity id in another domain now go to a durable `catalog_quarantine` Cosmos container instead of memory; `NS_WORKER_CATALOG_QUARANTINE_WARN` (default 100) sets the one-time warning threshold. `PresentedEdge.provenance` is exposed on curation and map responses. See `docs/runbooks/catalog-review-queue.md` (PR #292).
- PRP-44: platform configuration under `/api/v1/admin/platform` (customer-level `config.manage`): domain registry (create, list, get, retire; reserved `customer-control` domain), budgets (stored, not evaluated), price-sheet upload that appends a content-hashed `PriceSnapshot` with a coverage report, and the review policy (`GET`/`PUT`).
- PRP-44: the ingestion worker merges stored price snapshots into its ledger price table at startup, and the API and the `actions`, `hitl_timers` and `evaluation` workers load the stored review policy at startup; with nothing stored behaviour is unchanged.
- PRP-44: identity routes return 422 `domain_not_registered` for an unregistered domain once at least one domain is registered; domain names that collide with a customer-wide audit chain (`is_reserved_chain_name`) are refused.
- PRP-45: deployment-scoped admin system plane under `/api/v1/admin/system`: `GET status` (every composition component with state, required flag and reason code, plus probe results, never a value), `GET checklist` (stable item ids, status, reason code, docs anchor) and `GET|PUT settings/{key}` for `copilot`, `judge`, `search`, `scan`, `mcp_server` and `write_targets`, with `If-Match` guarding, a returned diff, credential-name and cross-cloud refusal, and an audit record per accepted write.
- PRP-45: the API builders (copilot, search, MCP server, scan bootstrap) and the evaluation worker judge read stored settings once at startup, stored value over env; a restart applies a change and `restart_required` reports the pending one. With nothing stored, or the store unreachable, behaviour is unchanged (env) and the checklist shows `stored_settings_unavailable`.
- PRP-45: `admin_system` optional component in `/readyz` details; runbook `docs/runbooks/system-settings.md`.
- PRP-46: the `nscostcenter` CloudEvent extension now survives ingest. `HubMessage.cost_center`, `Observation.cost_center`, `LedgerEntry.cost_center` and `LedgerFilters.cost_center` carry it to the ledger (sanitised, never rejects an event, a record's own `tags.cost_center` wins). Entries stored before the change still load.
- PRP-46: `GatewayRegistration.poll_attribution` reports attributed, exact, subscription-only and unattributed rows and a failed metrics query per poll; the gateway detail API returns it.
- PRP-46: ingest reason `observation_source_mismatch` (per-item); counters for dropped non-billing invoiced records (`ns.outbox.cost_dropped`).
- PRP-48: role-gated route category (`require_role`), so `GET /api/v1/workspaces/{role}` is tenancy-bound and records a denial on `role_not_held`; `/me/domains` documents the empty-200 case and logs one count-only warning when the catalog page cap is hit.
- PRP-48: `require_deployment_admin` (`authz/deployment_scope.py`) gates every MCP admin route, deploy scan and plan, and the emergency-disable kill switch on the deployment-scoped admin assignment; `config.manage` in an ordinary domain no longer reaches them (403 `customer_scope_required` plus a denial record). Operators re-run `scripts/sandbox/sbx_grant_operator.py` on hosted environments.
- PRP-48: allowed catalog searches and dashboard reads append one `allowed` audit record (actor pseudonym, operation, domain, no query text); a failed audit write is logged and never blocks the read.
- PRP-48: `RESERVED_CHAIN_NAMES` and `is_reserved_chain_name` in core audit; a dotted `NS_AUTH_CUSTOMER_ID` fails the `authz` component with `customer_id_invalid`; denials whose member chain cannot be encoded fall back to `<customer>.authz-denials`.
- PRP-49: per-agent and per-model aggregate series. The aggregates worker rolls `model_call` events up per hour and day into a new `subject` metric (`SubjectPoint`, series keys `agent:<id>` and `model:<provider>/<model>`), and the aggregate stores gain a bounded batch read (`SubjectMetricsReader.latest_subject_points`), PR #301 (#243).
- PRP-49: agent and model nodes on `/map` now carry `frequency`, `latency_p95_ms`, `tokens` and `health` from the latest subject point; unknown stays `null` and `unknown`. The realtime delta source also pushes changed agent and model nodes.
- PRP-50: gateway poll records a distinct `stalled` status (with the stalled slice start in the log fields, watermark held) when a source reports `stalled_slice_start`.
- PRP-50: billing export counts restated closed days in `last_status.restated` and logs `billing_export.restated` with counts only; the first posted amount still wins.
- PRP-50: Foundry discovery counts deployment-name collisions between projects in `TickStats.collisions`.
- PRP-50: connector SDK exports `check_capable` and a shared `tracked` health decorator; `move` and `copy` without `from_` return `verifiable=False` with reason `missing_from`; the contract kit names the missing write-protocol member.
- PRP-52: `scripts/ci/install-scanners.sh` installs syft, trivy and grype by pinned version and sha256 for every security job; an aggregator check `images (all scans)` fails when images exist but a scan was skipped or failed.
- PRP-52: `scripts/render_mermaid.py --source-dir` renders every block in `docs/security/dfd`, run by the `mermaid` CI job.
- PRP-52: APIM module parameter `uiApiRateLimitCalls` (default 0, off) applies a service-level `rate-limit-by-key` policy, only when the service is created.
- PRP-52: the network module allows `AzureLoadBalancerInbound`; `vnetAddressPrefix` is a root parameter of `modules/main.bicep`.
- PRP-52: `licenses_report.py` resolves bumped platform-binary families from an installed sibling package and fails under `CI` when a row was carried forward and is not on the cited allowlist.
- PRP-53: the Admin workspace is a real console. `/admin/identity` manages principals, role assignments, domain memberships, resource grants and revocation; `/admin/domains` lists, creates and retires domains; `/admin/system` shows component state, the first-run checklist and stored-setting sources; `/admin/audit` searches, pages and exports audit records with a denials tab and SIEM status. Every write goes through the confirm dialog and the API decides access.
- PRP-54: with `NS_WRITE_TARGETS_FROM_STORE=true` the API and the `actions` worker register write targets from the stored `write_targets` entries (PRP-45) instead of only from `NS_FOUNDRY_*` and `NS_APIM_*` env; the env path is the fallback and the default.
- PRP-54: `WriteTargetRegistry` gains an additive `target_key` (the intent's domain id) on `register`, `get`, `supports` and `target_keys`, so several connectors of one kind (for example two APIM gateways) coexist; `get(name)` with several keys and none given refuses with `target_ambiguous`.
- PRP-54: compose, the Helm chart (`writeTargets.fromStore`, `writeTargets.{foundry,apim}`) and `infra/demo/main.bicep` (`writeTargetsFromStore`) carry the opt-in, default off; runbook `docs/runbooks/write-targets.md`.
- PRP-55: real deploy apply behind `NS_DEPLOY_APPLY_ENABLED`. A durable plan-approval store (`deploy_plan_approvals` Cosmos container, shared by API and workers), an allowlisted ARM provisioner (storage, Event Hubs, Log Analytics) with `neurosphere:created-by` tags, bounded LRO polling and the deployment cloud's management host, a bearer Fabric transport gated by the capability matrix, verify-by-change with register rows, customer binding, and `scripts/gates/deploy_apply_live.py` (refuses without `NS_LIVE_APPROVED=1`; the live run is OPEN, PRP-64). The Helm chart and App Service profile now pass the apply opt-in to the workers too, still off by default (PR #314).
- PRP-56: metadata-only compliance mapping. A versioned control library (NIST AI RMF, SR 11-7, HIPAA technical safeguards, OMB M-25-21) held as package data, five read-only evidence sources (catalog ownership, audit-chain integrity, HITL decisions, evaluation results, cost attribution) and a deterministic evidence bundle per domain and framework with a sha256 digest. It maps and collects evidence and never judges; no output says an estate is compliant or authorized.
- PRP-56: `GET /api/v1/compliance/frameworks`, `/frameworks/{framework_id}`, `/domains/{domain}/bundle` and `/domains/{domain}/bundle/export` (JSON or Markdown), gated by `evidence.read` on the domain, with an allowed-read audit entry.
- PRP-56: the `/compliance` and `/compliance/control` pages, the `compliance` contract family and runbook `docs/runbooks/compliance-evidence.md`.
- PRP-57: admin console part 2 under `/admin`: ingest producers with a show-once secret (`/admin/sources/producers`), connector configurations with credential references only (`/admin/sources/connectors`), gateway registration (`/admin/gateways`), catalog import with a required dry run and payload digest gate (`/admin/catalog-import`), price sheets and budgets (`/admin/pricing`), feature settings with restart-required notices (`/admin/features`) and the HITL review policy (`/admin/review-policy`).
- PRP-57: mock API module `frontend/tests/mock-api/features/admin-sources.ts`, Playwright specs under `frontend/tests/e2e/admin-sources/`, axe samples and visual baselines for the new pages.
- PRP-58: hosted data-path switches for the demo Bicep (`connectorRoles`, `recommendationsEnabled`, `foundryAccountIds`, `billingExportStorageAccountId`, evaluation pilot parameters), the App Service profile and the Helm chart, with least-privilege connector role assignments for the workers identity (`connector-rbac.bicep`), `NS_INGEST_PRODUCER_STORE` and `NS_WORKER_CONNECTOR_CONFIG_SOURCE` set in hosted profiles, and `scripts/gates/g04_connectors_live.py` (refusal-first live gate; the live run is OPEN, PRP-64). See `docs/deploy/hosted-demo.md` (PR #312).
- Azure AI Search index schema in code (`catalog_index_definition()`), an opt-in `NS_SEARCH_ENSURE_INDEX` startup create-or-update, and write-through indexing of catalog writes from the API and from the `projections` and `foundry_discovery` workers (PRP-60, PR #311).
- PRP-61: `detections` worker role with content-filter policy, APIM policy-fragment and shadow-AI account checks; findings are stored as the new recommendation kinds `configuration_finding` and `unregistered_ai_resource` (always advisory), appear in the recommendations list and review path, and feed a `configuration_findings` compliance evidence source. Metadata only. See `docs/runbooks/detections.md` (PR #318).
- PRP-62: read-only `aws-bedrock` reference connector (Bedrock inventory, CloudWatch usage, Cost Explorer daily cost, metadata only, Commercial AWS only) with a least-privilege IAM policy and a live-check script that refuses without `NS_LIVE_APPROVED=1`. Library only: no stored configuration or worker role yet (PR #317).
- PRP-63: `deploy-hosted.yml` delivery pipeline to the hosted environment (OIDC login, plan, approval in the protected `hosted-demo` environment, deploy of the release tag, smoke via `scripts/gates/hosted_smoke.py`, then publish of the draft release); a tag release stays a draft until the hosted smoke is green. Inert until the operator creates the federated credential, environments and their values. See `docs/deploy/delivery.md` (PR #316).
- PRP-65: `lifecycle.manage` (Admin) and `audit.export` (Security Auditor) permissions, `customer_control_domain_id` / `permits_customer_wide` for deployment-scoped authority, `PolicyAdminRepository` (in-memory and Cosmos, ETag preconditions, transactional `PolicyHead` bump) and the audited `admin_config` store (`neurosphere_core.admin`, new `admin_config` Cosmos container, monotonic version, If-Match replace, retire). Storage and authority layer only; routes and console arrive in PRP-39..57.
- PRP-68: changelog fragments (`changelog.d/<PRP file stem>.md`) assembled into `CHANGELOG.md` at release time by `scripts/changelog_assemble.py` (`--check`, `--preview`, `--write`, standard library only), so parallel close-outs no longer conflict on `[Unreleased]`.
- PRP-68: `scripts/prp_index_check.py`, a structural `PRPs/INDEX.md` freshness check run by `scripts/validate_planning.py`; the CI `planning` job also runs `prp_execution_plan.py --check` and the fragment check; `.githooks/pre-commit` blocks malformed staged fragments and warns on a stale execution plan.

### Changed
- PRP-11: the G01 live script imports the product executor and the shared equivalence workload, bounds setup and teardown with a time budget and uses plain `CREATE SCHEMA` (#60).
- PRP-11: the adapter registry keeps the `capability_unavailable` reason for refused Government regions.
- PRP-15: held-out recalibration of duplicate precision and pilot latency detection; the two targets are amended to the measured numbers in `docs/evidence/G12/recommendations/README.md`.
- PRP-18 (round 2): the map viewport reads edges through one bulk `RepositoryGraphQuery.edges_among` call (new `EdgesAmongQuery` protocol, per-node walk kept as fallback) instead of one neighbour read per node; the realtime pump sleeps the smaller of the poll interval and the scope refresh interval; the map client ignores deltas after a 4403 revoke; replay gap detail for a missing parent is generic and no longer reveals another domain; gap badges have unique keys; the map table no longer steals focus on `Load more` and falls back to a tabbable row; the mock API answers an unknown replay trace with problem+json 404 (PR #280).
- A federation cell that answers for another cell, cloud, boundary or customer is now reported `unavailable` instead of aborting the merge; the merged window is min start / max end; all cells `denied` returns 403.
- PRP-23: compliance statement checker negation is clause-scoped, evidence collector checks resolved-path containment, CA-7, CP-2 and PM-5 control statuses upgraded (#120).
- PRP-38: `make stack-up` now seeds the worker grants before the app profile starts, then runs the full seed (#205).
- An invalid `NS_AUDIT_SIEM_*` setting no longer fails the `audit` component. It marks only the optional `audit_siem` component `failed` (`audit_siem_settings_invalid`), so a misconfigured SIEM export does not block readiness.
- Graph traversal resolves endpoints with bounded concurrency (16) and reports `max_edges` only from in-scope edges; the entity write routes refuse a declared `Content-Length` over 64 KiB; `ChangeConfirmDialog` gains a `controls` slot and `reasonMode`.
- PRP-46: `POST .../mcp-servers/{id}/publication-record` now requires `catalog.curate` (was `action.propose`), matching the grant route.
- PRP-46: the APIM create step sends `If-None-Match: *` and refuses with `resource_appeared` when the resource appeared between plan and apply; grant publication records refuse a replayed older intent (`stale_intent`, 409).
- PRP-47: shell navigation supports ArrowUp and ArrowDown, the last-domain key is cleared whenever the account disappears, and the deployment default theme applies before the shell renders (sign-in redirect screen). Finance demo domain now holds `catalog.curate`, PR #298.
- PRP-47: Vitest fails on unhandled MSW frames, retries once in CI only, the demo build has a positive-control prod-exclusion test, and `paths.ts` exists for dashboards, actions and review.
- PRP-48: injection corpus README states where consumer suites live and that the stub's `follow_instruction` abstains are vacuous until a real adapter exists.
- PRP-49: `replace_bucket` skips unchanged documents, and the map client merges a metrics-only delta without overwriting labels; deltas for unknown agent, model and source ids are ignored.
- PRP-50: `FoundryDiscoveryPoller` refuses a `domain_id` without the runtime `cloud:customer:` prefix (`InvalidSchemaError`) and logs discovered names at debug level only.
- PRP-50: Azure Monitor slice halving works from the actual clipped span; the apim-gateway and foundry-actions connectors use the SDK `tracked`.
- PRP-51: deprecated path aliases now send RFC 9745 `Deprecation: @<epoch>`, `Sunset` and `Link` headers on every response including errors; test-only `CompositionOverrides` are refused outside `NS_ENV=local`; copilot and CORS startup refusals share `StartupRefusedError`; `NS_STORE_COSMOS_ACCOUNT` is validated; the Cosmos container verify runs in the background with a `pending` readiness state; new `NS_READYZ_DETAIL=full|summary` (default `full`). See `docs/runbooks/api-path-aliases.md` (PR #319).
- PRP-52: the Helm chart requires `env.NS_CLOUD` (`commercial` or `government`); values files that omit it no longer render. Set it in every values file.
- PRP-52: `security.yml` passes matrix values through `env:` and runs `trivy fs --include-dev-deps`; the `egress-compose` job dumps bounded compose logs on failure; the four copies of `skip_or_fail` are one shared helper.
- PRP-52: runtime images drop `sqlite-libs` and the four matching Grype ignore rules are removed; `neurosphere_core.analytics.base.stub` imports `sqlite3` lazily.
- PRP-52: Dependabot ignores `datamodel-code-generator` updates (the pin is a deliberate contracts decision).
- PRP-53: `/workspaces/admin` shows the console landing instead of the placeholder text.
- PRP-54: `ActionPlane.connector_for` takes the intent's domain id and all call sites pass it; a domain with no registered target stays advisory. Duplicate targets in one domain are refused (`write_target_duplicate_domain`).
- Deploy plan approvals are no longer held in API memory: approve is create-only per customer and plan, and apply routes are async. Re-approve plans after upgrading.
- PRP-59: `POST /api/v1/deploy/plan` refuses a request-body `scan` (422 `scan_body_not_accepted`); plan from the server-issued `scan_id`. The deploy UI and mock API send `scan_id`.
- PRP-59: the scan consent audit record carries the authenticated principal pseudonym as `consented_by` and a hash of the client attestation.
- PRP-59: `infra/scripts/uninstall.py` knows every top-level ARM type the Bicep tree declares (coverage test added); DoD regions are no longer treated as Government in copilot gating, capabilities and the mock.
- PRP-59: G02 profile teardown writes evidence on interrupt, re-checks resource tags before deleting the group and narrows the AKS cleanup exception; `confine_evidence_dir` is shared in `scripts/gates/_evidence_paths.py`.
- Azure document keys are URL-safe base64 of the canonical id; the canonical id lives in a filterable `entity_id` field. Indexes built before this change must be recreated.
- Catalog search refresh uses a bounded per-scope single-flight lock instead of one global lock.

### Removed
- Legacy Kong / Data API Builder / Artemis procurement demo scaffold.
- `pre-commit` framework config (replaced by `.githooks/`).
- PRP-38: the unused `OPT_IN_ROLES` tuple in the worker role registry (#180).

### Fixed
- PRP-11: analytics suite assertions tightened (#61) and adapter nits fixed (#62), including a Fabric migration ledger lock that no longer leaks or reuses recycled executor ids.
- PRP-15: two concurrent `HitlReviewRouter.route` calls for one recommendation now open exactly one review item (deterministic item id, create-only write), and a recommendation id converges on one copy across domain partitions in the Cosmos and in-memory stores (#133). A later `put` into a larger partition than an existing copy is silently discarded.
- PRP-38: `make replay` wraps valid telemetry lines in the `HubMessage` envelope instead of quarantining them as `invalid_wire` (#162); the first-seed `skipped_existing` assertion no longer depends on timing (#211).
- PRP-46: ARM ids with a `.`/`..`/trailing-dot resource group are refused; a failed gateway failure-record logs the exception type and never raises; a 403 on optional inventory lists degrades to empty with `unreadable`; the duplicates counter is created once per pipeline.
- PRP-50: the OTel connector rejects `evilvault.azure.net` and other non-dot-bounded Key Vault hosts (`unrecognized_vault_host`); the span exporter's closed check and pending registration now share one lock, closing an export-versus-shutdown race.
- The indexer deletes documents whose entity left every scope's enumeration (ref-counted), and no longer skips the re-upsert when a concurrent scope deletes the same id.

### Security
- The replay read-only import guard now also catches relative imports, `importlib.import_module` and `__import__` calls.

## [0.1.0-rc.2] - 2026-10-26

Contract schemas shipped: actions v1, audit v1, catalog v1, chart v1, connectors v1, cost v1,
deployment v1, errors v1, evaluation v1, query v1, recommendations v1, scope v1, telemetry v1.

Migration ids per target: TODO(operator): record the highest applied migration id per target
(Cosmos document types, analytics adapters) from the migration ledger before tagging.

### Added
- **infra:** compose the hosted demo template (PRP-32 item 3)
- **hosted:** post-deploy smoke, hosted Playwright spec, nginx Host/SNI and opt-in health proxy
- **sandbox:** hosted seeding mode and registered-endpoint guard (PRP-32 item 5)
- **infra:** hosted demo data, messaging, RBAC and network Bicep modules (PRP-32 item 1)
- **gates:** gated hosted-demo deploy script with register-guarded teardown (PRP-32 item 4)
- **infra:** extend App Service profile for the hosted demo (PRP-32 item 2)
- **map:** style-aware map canvas, deterministic spaced layout, restyled map table and replay (PRP-30 item 9)
- **reports:** restyle quality, recommendations, reports and chart frame (PRP-30 item 8)
- **shell:** style-aware chrome, demo profile and route audit (PRP-30 item 5)
- **actions:** restyle actions, review, workspaces, sandbox and MCP admin (PRP-30 item 7)
- **dashboards:** redesign home, dashboards and reconciliation (PRP-30 item 6)
- **design-system:** PRP-30 mockup rework round 1
- **demo:** PRP-30 item 4 mockup gallery and approval renders
- **design-system:** chart primitives (PRP-30 item 3)
- **design-system:** brand mark and component primitives (PRP-30 item 2)
- **design-system:** UI style foundation (PRP-30 item 1)
- **prp-29:** compose app profile, stack-up/down and manifest route smoke (item 11)
- **sandbox:** seed the local real stack through the real paths (PRP-29 item 10)
- **workers:** NS_WORKER_ROLES runtime with supervised roles and readiness (PRP-29 item 9)
- **runtime:** compose action plane, reports, copilot and MCP builders (PRP-29 item 8)
- **api:** build the data plane from settings (PRP-29 item 7)
- **frontend:** same-origin edge with nginx /api proxy and start-time config.json (PRP-29 item 5)
- **prp-29:** Entra local sign-in script and operator policy grant
- **api:** compose the app from settings with authz, readiness and a container registry
- **api:** serve catalog, curation, audit, ingest and deploy under /api/v1 with deprecated aliases
- **stores:** add Cosmos recommendation, evaluation and price snapshot stores
- **stores:** Cosmos HITL, decision, review-queue and lifecycle stores plus HitlReviewRouter
- **app:** wire theme packs and sandbox mode (PRP-24 item 4)
- **sandbox:** server-enforced sandbox API, toggle and isolation banner (PRP-24 item 2)
- **themes:** agency theme pack schema, resolver, logo allowlist, registry (PRP-24 item 1)
- **lifecycle:** retention, pseudonymization, deletion, export and legal hold engine
- **compliance:** evidence inventory collector and statement checker (PRP-23 item 3)
- **mcp:** registration admin API and UI, plus MCP server/client hookup (PRP-22 item 3)
- **mcp:** external MCP client with registry, SSRF pinning and tool approval
- **mcp:** scoped MCP resource server over the tool registry and action API
- **dr:** runbook, caveat tests and committed compose restore drill evidence
- **dr:** per-store backup and restore scripts and compose restore drill harness
- **wiring:** attach federation and finops routers (PRP-21 item 6)
- **finops:** add trend forecast service, scoped router and evidence hook
- **federation:** scope-filtered cell summaries and cloud-bounded merge (PRP-21 item 3)
- **admission:** per-domain quota config, token-bucket limiter and ASGI middleware
- **gates:** G02 Government AKS and App Service profile gates (PRP-20 item 4)
- **prp-20:** Government evidence register and responsibility matrix
- **infra:** Azure Government sovereign profile and static tests (PRP-20 item 2)
- **frontend:** role-aware overview tiles and static no-native-controls test
- **frontend:** PRP-28 item 3 local demo mode and CI headroom
- **frontend:** fluent app shell, domain switcher and page template (PRP-28 item 2)
- **api:** add /me/domains and /workspaces/{role} endpoints (PRP-28 item 1)
- **copilot:** chat dock UI with streaming client and first-token measurement
- **wiring:** attach copilot and reports to the app and the shell (PRP-19 item 7)
- **prp-19:** saved reports API and UI with per-run re-authorization (item 5)
- **copilot:** orchestrator API with SSE stream, citations, abstention and redacted conversations
- **prp-19:** chart plan validator and sandboxed Vega-Lite renderer
- **copilot:** allowlisted tool registry with server-derived scope (PRP-19 item 1)
- **copilot:** model adapters with a shared action contract (PRP-19 item 3)
- **map:** sigma 4 WebGL live map renderer (PRP-18 item 3)
- **map-table:** accessible table view of the live map (PRP-18 item 4)
- **wiring:** attach realtime, map and replay to the app and the shell (PRP-18 item 7)
- **replay:** read-only trace replay API and tree viewer (PRP-18 item 5)
- **realtime:** scoped WebSocket gateway fed from hot aggregates (PRP-18 item 1)
- **map:** bounded viewport API with clustering and paginated expansion (PRP-18 item 2)
- **prp-17:** wire actions/review shell, mock API, e2e and UI-fixture hash test
- **prp-17:** wire action plane, review completion hook, vertical slice and G12 evidence
- **prp-17:** review queue and action confirmation UI
- **actions:** shared action API and review queue API (PRP-17 item 4)
- **prp-17:** action executor worker and policy-store permission recheck
- **actions:** durable action plane core (PRP-17 item 1)
- **prp-17:** HITL review workflow and durable timer worker (item 3)
- **prp-17:** foundry model-swap write connector, advisory mode, G05 live script (OPEN)
- **prp-16:** wire evaluation pipeline, quality route, in-process slice and evidence
- **prp-16:** sampling worker with restricted guard and evaluator budgets
- **quality:** agent quality UI (PRP-16 item 5)
- **evaluation:** scoped evaluation store and quality API (PRP-16 item 4)
- **evaluation:** versioned datasets, rubrics, judge registry and fixture judge (PRP-16 item 1)
- **evaluation:** judge calibration, label ingestion and drift alerts (PRP-16 item 3)
- **recommendations:** pipeline, in-process vertical slice and G12 evidence
- **recommendations:** wire router, route, nav, mock API and Playwright specs
- **recommendations:** duplicate consolidation-review candidates (PRP-15 item 2)
- **recommendations:** advisory recommendations list and detail UI (PRP-15 item 5)
- **recommendations:** bounded rules engine (PRP-15 item 1)
- **recommendations:** advisory recommendations API and store (PRP-15 item 4)
- **pricing:** versioned price snapshots and right-sizing projections (PRP-15 item 3)
- **dashboards:** wire dashboards and reconciliation into the API, app shell and mock API
- **reconciliation:** reconciliation view API and UI (PRP-14 item 4)
- **dashboards:** cost/latency/errors/coverage API from hot aggregates (PRP-14 item 2)
- **aggregates:** hot-aggregates projection worker and read store (PRP-14 item 1)
- **dashboards:** cost, latency and coverage pages with unknown/estimated/price-version rendering

### Changed
- **frontend:** fold feature stand-ins into design-system primitives
- **frontend:** quality, recommendations and reports on PageTemplate and Fluent (PRP-28 item 6)
- **frontend:** dashboards and reconciliation use PageTemplate and the shell domain
- **frontend:** move actions and review onto PageTemplate and Fluent controls
- **frontend:** map, map table and replay use PageTemplate and the shared domain

### Deprecated
- true only (operationIds unchanged), no component added,

### Fixed
- **infra:** hosted workers run the six roles that need no mounted data
- **gates:** abort deploy when the pre-deploy budget snapshot fails
- **gates:** hosted_demo ownership, Entra restore, plan binding, smoke wiring (PRP-32 item 4 rework)
- **infra:** use EnableServerless capability for Cosmos serverless on 2024-11-15
- **charts:** attach the width observer whenever the chart div mounts
- **charts:** lay out time-series and bar charts in real pixels
- **shell:** Enterprise Fluent canvas uses colorNeutralBackground2
- **demo:** faithful authorization in the demo mock profile
- **design-system:** keep only data-* row attributes in DataTable
- **design-system:** info pill contrast, row/test-id hooks, plain null-kind legends
- **frontend:** null-safe recommendation fields; real-stack run fixes
- **gates:** run the az CLI bundled python on Windows, not az.cmd
- **workers:** a crash-looping role is never ready
- **codeql:** module TypeVar for shared lookups; pass fake database via base
- **stack:** bind-mount relative SANDBOX_DIR; give the seed drain 900s
- **seed:** rebase world to run time, seed catalog entities and operator report (PRP-29 E2)
- **platform:** PRP-29 E1 api workers dep, idempotent containers, worker data mounts, sandbox seed
- **workers:** refresh the aggregates price table at runtime (PRP-29 9b)
- **stores:** align PRP-29 item 2 Cosmos stores with the container registry
- **stores:** move HITL Cosmos store out of hitl/ and align keys with the registry
- **catalog:** stamp the curation decision actor from the authenticated principal
- **a11y:** restore dialog focus and chart iframe focus indicator (PRP-24 item 5b)
- **a11y:** theme-token link colour and HC badge contrast (PRP-24 item 5)
- **lifecycle:** legal hold blocks subject erasure of held data (PRP-23)
- **lifecycle:** type the compose test page result as Mapping (PRP-23)
- **infra:** correct audience provenance in Government sovereign profile (PRP-20 item 2)
- **frontend:** show no-domains message for empty list and default domain_id in URL
- **ci:** avoid a match capture CodeQL reports as uninitialised
- **ci:** clear gitleaks and CodeQL findings on PRP-19
- **copilot:** stop offering Save as report on chat charts without a query
- **prp-19:** require If-Match on the report publication decision
- **map:** link map and map table through path-only modules
- **map:** stop edge animation when data is not live and fresh
- **map-table:** make focus after "Load more" deterministic
- **realtime:** finish gateway cleanup when a disconnect races a task cancel
- **prp-17:** CI security gates - certifi bump, curl removal, CodeQL raise, gitleaks fixture
- **prp-17:** action detail header is a div, not a p containing a Badge div
- **prp-17:** keep the executor lease alive across long connector calls
- **hitl:** fail closed on on-behalf-of maker without principal id
- **prp-17:** item 5 merge fixes
- **prp-17:** restore deployment on post-PUT failure; G05 script always rolls back
- **evaluation:** trust registry data_state in run_offline, reject relabelled datasets
- **quality:** key trend rows by bucket and judge; board, item 5 merged
- **recommendations:** pooled-window latency rule with insufficient-evidence floor (PRP-15 item 7)
- **recommendations:** badge row is a div, not a p (nested div warning)
- **recommendations:** label the list filter submit "Apply filters"
- **dashboards:** address the domain as a path segment, not a domain_id query

### Security
- **security:** fingerprint PRP-29 planes test idempotency key
- **security:** fingerprint PRP-29 evaluation store gitleaks false positives
- **security:** no-Commercial-egress tests for the Government profile (PRP-20 item 3)

_174 maintenance commits omitted._
