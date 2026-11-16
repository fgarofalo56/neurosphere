---
name: PRP-136-governance-live-gates-campaign
status: backlog
priority: P2
order: 136
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-01, NS-04, NS-06, NS-08, NS-09
depends_on: [PRP-102-encrypted-interaction-store-and-retention, PRP-107-notification-channels-and-subscriptions, PRP-109-north-star-scenario-acceptance, PRP-111-interaction-capture-sources-sdk-and-gateway, PRP-112-gateway-policy-enforcement-apim, PRP-118-agent-identity-and-entra-entitlements, PRP-120-purview-labels-classifications-and-lineage, PRP-121-unity-catalog-connector-and-lineage-push-back, PRP-122-m365-copilot-and-copilot-studio-connector, PRP-123-github-copilot-and-cursor-connectors, PRP-124-openai-chatgpt-enterprise-connector, PRP-125-anthropic-claude-connector, PRP-126-shadow-ai-discovery-identity-and-cloud-apps, PRP-129-cicd-registration-and-policy-gate, PRP-133-ticketing-integration]
wave: W33
branch: prp-136-governance-live-gates
allow_parallel: true
issues: []
---

# PRP-136: Governance live gates campaign (operator-attended)

## Goal
Turn the governance gates that the build PRPs left OPEN into evidence, or into an honest OPEN with a reason, in one operator-attended session after the build waves. Each item runs one live gate: the exact script or procedure, the approval the operator gives, the evidence file under `docs/evidence/governance/`, a spend-cap line (a proposal the operator sets or replaces), and the register row it updates. Items are independent and any of them may end OPEN; a run that failed is committed as a failure, never as a pass; a skipped test is OPEN. The agent drives and records; the operator approves every billable or consent-bearing step, supplies every target name, installs every credential and grants every role and consent (nothing secret ever enters the conversation, a file or the repo, which is public). This PRP changes no product code; the only code edit allowed is a fix to a gate script that is needed to finish a run, recorded as a deviation. It is the governance counterpart of PRP-64 (Azure service gates) and PRP-66 (operations and sign-off).

Out of scope: building anything the gates exercise (PRP-100 to PRP-135 own the code and the scripts); the Azure service gates, G17 observe and manage, G16 judge, the copilot live turns (PRP-64); load, DR, deploy apply and accessibility sign-off (PRP-66); AWS and GCP key-wrap, KMS and conformance runs (PRP-94 and PRP-98 hand theirs to the multi-cloud live gates); Government runs (always recorded OPEN here, no Government subscription is assumed); editing product docs or capability data a run suggests changing (a follow-up issue each); granting Purview roles, Entra consent or tenant settings (operator only).

## Why
- Every governance PRP records its live step as OPEN and hands it here: key wrap and hosted capture (`PRPs/backlog/PRP-102-*.md` "Live and open gates", `PRP-103-*.md`, `PRP-104-*.md`), notification delivery (`PRP-107-*.md`), the hosted north-star run (`PRP-109-*.md`), gateway enforcement and the gateway content source (`PRP-112-*.md`, `PRP-111-*.md`), the Graph and ARM entitlement read (`PRP-118-*.md`), Purview and Unity reads and lineage push (`PRP-120-*.md`, `PRP-121-*.md`), five estate connectors (`PRP-122-*.md` to `PRP-126-*.md`), the CI gate (`PRP-129-*.md`), GitHub Issues (`PRP-133-*.md`) and the embedding endpoint (`PRP-135-*.md`).
- Without a campaign these stay OPEN indefinitely and "built" would be read as "works"; `CLAUDE.md` says live gates need `NS_LIVE_APPROVED=1` and are reported OPEN when they did not run.
- The shape is proven: PRP-64 and PRP-66 run each gate as an independent item with an approval line, an evidence path and a register row (`PRPs/backlog/PRP-64-live-gates-campaign.md` items 2 to 12). The evidence conventions already exist (`docs/evidence/G17/observe-20261106T203521Z.md`, whitelisted fields, tokenised ids).
- Several of these touch shared enterprise resources (an Entra tenant consent, a Purview account, a SaaS organisation, a shared gateway). The session must never decide to proceed on one of those; only the operator's own message counts.
- The register `docs/RESEARCH-AND-GATES.md` has no rows for interaction capture, notification delivery, estate coverage beyond G04, or the CI gate; this PRP adds them so the open state is visible in the one place everything else looks.

## Acceptance criteria
- [ ] Every item has an outcome row (PASS, FAIL, PARTIAL or OPEN) with its evidence path, spend and register row; no item is left without an outcome; an item whose approval was not given is `OPEN (not run)` with the reason.
- [ ] Every script that refuses without approval was run only with `NS_LIVE_APPROVED=1` set by the operator for that item; an exit code that means "refused, nothing ran" is recorded as OPEN, and the item is never retried with a weaker flag.
- [ ] Evidence files contain only whitelisted fields: outcome, counts, timings, status bodies with ids tokenised, component states and reason codes; no tenant, subscription, object or resource GUID, no URL with a token, no credential, no captured content, no user identifier, no email address; `git grep` for GUID-shaped strings in `docs/evidence/governance` is clean.
- [ ] A PASS is claimed only for what ran: key wrap PASS means one wrap and one unwrap through a real Key Vault key in Commercial, not "capture works"; a connector PASS lists exactly which signals returned data and which stayed unavailable; Government, AWS and GCP stay OPEN.
- [ ] Every failed or partial item states the observed behaviour and the follow-up (issue text drafted, not filed without the operator); nothing is edited to turn a failure into a pass.
- [ ] Only the register rows listed under Ownership change, in one close-out commit made after PRP-64's close-out merged.
- [ ] No product source file changed (a gate-script fix, if any, is listed as a deviation with the diff summary).
- [ ] Teardown is recorded for every resource the session or operator created for a run (deleted, or intentionally retained with the reason), and no live resource is left running unnoticed.
- PRP exit: `python scripts/validate_planning.py`, `tests/unit/gates` and `tests/docs` pass; PR open with CI green; the completion note table is filled.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Where the evidence goes | Each PRP's own directory; one governance directory | `docs/evidence/governance/<gate>-<UTC>.{md,json}`. A script that writes elsewhere (for example `docs/evidence/G17/enforce-*.md`, PRP-112 item 7) is run with its output redirected here or its result is copied here and the original is not committed, because `docs/evidence/G17/**` is PRP-64's |
| 2 | New register rows | Reuse G04, G06, G17; add rows | ASSUMPTION: reuse G04 (estate, identity, label connectors), G06 (capture on the hosted app, retention) and G17 (enforcement sentence); add G18 "Interaction content store and key wrap", G19 "Notification delivery", G20 "CI registration gate", G21 "Embedding and hybrid search". Item 1 confirms the ids are free |
| 3 | The hosted north-star run | Here; PRP-66 only | Run here (PRP-109 hands it here); PRP-66 lists the evidence in its sign-off table and does not rerun it. Evidence stays under PRP-109's `docs/evidence/north-star/` only if PRP-109 owns the run; this PRP's rerun record goes to `docs/evidence/governance/` and links it |
| 4 | Procedure versus script | Write scripts here; use the delivered ones | Use what each PRP delivered (`scripts/gates/gateway_capture_live.py`, `g17_apim_enforce_live.py`, each connector's `live_check.py`, `scripts/gates/g04_connectors_live.py`). Where none exists the item is an ASSUMPTION: manual procedure through the product's own API and the admin UI, with the same evidence layout |
| 5 | Spend caps | Fixed; operator-set | Each cap below is a proposal; the operator sets or replaces it in the approval sheet, and the cap line is copied into the evidence header |
| 6 | Government | Try; record OPEN | Always OPEN. Where a build PRP verified Government availability, that is noted; no run is attempted without a Government subscription the owner names |
| 7 | Targets | Any available; named | Limitlessdata subscriptions only, throwaway resources with `project` and `owner` tags, never another team's account, gateway, tenant settings or SaaS organisation; the reused Loom APIM is never a target |
| 8 | Key wrap unavailable in a cloud | Build a weaker fallback; disable capture | ASSUMPTION (GD-18, recommended default): if Key Vault key wrap is unavailable in a cloud, content capture is disabled there (`key_wrap_unavailable`); no weaker fallback (such as a Key Vault secret as the key-encryption key) is built. Here: item 2 records a cloud without wrap as OPEN with that reason, and builds no fallback |
| 9 | Who signs in on the hosted north-star run | The pipeline; the operator | ASSUMPTION (GD-43, recommended default): the hosted north-star run is operator-attended: the operator supplies two steward identities, an auditor and a webhook endpoint stored in Key Vault; the deploy pipeline runs only a non-interactive readiness check. Here: this session is that attended run |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-64-live-gates-campaign.md` - the item shape to copy (items 2 to 6), its Gotchas and Ownership; and `PRP-66-operations-and-sign-off-gates.md` item 12 (close-out ordering).
- `docs/RESEARCH-AND-GATES.md` - the gate register (rows G04, G06, G12, G17) and the evidence conventions.
- `docs/evidence/G17/observe-20261106T203521Z.md` and `docs/evidence/G05/20261105T173214Z-foundry-swap-live.json` - whitelisted, tokenised evidence.
- `scripts/gates/g04_connectors_live.py`, `g17_apim_manage_live.py` - refusal shape and per-step approval flags.
- The "Live and open gates" and completion note of each PRP in `depends_on`, read at item 1 for the exact script paths and the verification files under `docs/connectors/verification/`.
- `docs/connectors/estate-coverage.md` (generated by PRP-117) - which connectors are built or `not_built`.
- `docs/evidence/north-star/` (PRP-109) - what the hosted run must produce.

### Interfaces consumed
- Delivered scripts and procedures named in each upstream PRP (PRP-111 `scripts/gates/gateway_capture_live.py`; PRP-112 `scripts/gates/g17_apim_enforce_live.py`; PRP-109 `scripts/gates/north_star_seed.py` and `north_star_evidence.py`; PRP-122 to PRP-126 and PRP-133 `live_check.py` per package; PRP-129 `integrations/github-action/` and `docs/integrations/cicd.md`; PRP-135's live embedding check).
- PRP-64's G17 manage result (item 5 here needs it PASS or PARTIAL, else OPEN).
- The admin APIs the procedures drive: PRP-107 `POST /api/v1/admin/notifications/channels/{id}/test` and `GET /deliveries`; PRP-103 system setting `interaction_capture`; PRP-104 investigator read; PRP-108 approval actions.
- Shipped: `NS_LIVE_APPROVED` convention, `/readyz`, audit search.

### Interfaces provided
- Evidence files under `docs/evidence/governance/` and the register rows G18 to G21 plus the G04, G06 and G17 sentences; the OPEN list that PRP-66 and the owner read.

### Patterns to match
- Evidence with whitelisted fields and tokenised ids: `docs/evidence/G17/observe-20261106T203521Z.md`.
- Cap and spend line in the header: `docs/evidence/PRP-25/docs-assistant-live-smoke-2026-11-14.md`.
- Item layout (command, approval, evidence, cap, register row, "ends OPEN when"): `PRPs/backlog/PRP-64-live-gates-campaign.md:132-200`.

### Gotchas
- `MSYS_NO_PATHCONV=1` for `az` and for `uv run` arguments that start with `/subscriptions`; not for `pnpm`.
- Memory notes to honour: resource group tag policy needs `project` and `owner`; Limitlessdata only; deprecated Foundry models fail deploys; never touch another team's Foundry account; the operator machine cannot resolve `api.loganalytics.io` (query through ARM); Key Vault purge protection means a deleted vault name cannot be reused, so use a fresh vault name per run; Defender may auto-create a topic that blocks teardown (check before deleting the resource group).
- Do not run `docker compose` or `make stack-up` in two sessions at once.
- Do not read `.env*`; the operator exports secrets into their own shell; verify presence with a count (`printenv NAME | wc -c`), never print values.
- Sign-in, consent and licence screens are the operator's: open the page headed, ask the operator to complete only that step, continue.
- Captured-content rule: the hosted capture run uses the synthetic demo domain only; evidence never contains interaction text, only counts and finding categories.
- No polling loops: wait once with a bounded timeout or use the script's own budget.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - docs/evidence/governance/**
  - changelog.d/PRP-136.md
tier1: []
tier2_appends:
  - docs/RESEARCH-AND-GATES.md
must_not_touch:
  - docs/evidence/G17/**
  - docs/evidence/G03/**
  - docs/evidence/G04/**
  - docs/evidence/G16/**
  - docs/evidence/north-star/**
  - docs/accessibility/**
  - docs/connectors/verification/**
  - packages/**
  - services/**
  - frontend/src/**
  - infra/**
  - connectors/**
  - .github/**
  - pyproject.toml
  - uv.lock
```
Register rows this PRP edits in `docs/RESEARCH-AND-GATES.md`: new G18 to G21 (ids confirmed at item 1), one sentence each in G04 (estate, identity and label connectors, not the Azure ones PRP-64 owns), G06 (hosted capture and content retention) and G17 (enforcement). PRP-64 and PRP-66 edit other rows of the same file; item 18 runs after PRP-64's close-out. A gate-script fix, if one is needed, edits only that script under `scripts/gates/` or `connectors/reference/*/` (the one allowed code change) and is listed as a deviation.

## Implementation blueprint

Every item is independent and operator-attended: the dependency noted is a shipped PRP or an earlier item's output, not a shared file. Commands use angle-bracket placeholders the operator fills. Outcomes are PASS, FAIL, PARTIAL or OPEN.

### Item 1 - Preflight and approval sheet
- Deliverable: confirm each delivered script exists and prints `--help` (list from "Interfaces consumed"); read each upstream completion note and `docs/connectors/estate-coverage.md` and mark `not_built` connectors `OPEN (not built)` up front; check `az account show` is the Limitlessdata target and `AzureCloud`; confirm G18 to G21 are unused in the register; write `temp/campaign/approvals.md` (one block per item: target, cap, approval line) for the operator; record `git status`.
- Owned files: none committed (temp only).
- Acceptance criteria: a table of item to script presence and connector status; missing scripts mark their items `OPEN (not run)`.
- Tests: none; evidence is the printed output in the completion note.

### Item 2 - Key Vault key wrap and interaction store (PRP-102)
- Procedure (ASSUMPTION: manual through the product API; PRP-102 ships no live script): operator creates a throwaway vault and an RSA key named in the approval, grants the API identity the least-privilege wrap and unwrap role the PRP-102 verification file names, sets the `interaction_capture` setting with that key identifier on a composed or hosted API; the agent stores one synthetic interaction through the store path, reads it back as an investigator with a stated purpose, then the operator disables the key version and the agent confirms the read fails closed with a reason code; teardown of the vault (purge protection noted).
- Evidence: `docs/evidence/governance/key-wrap-<UTC>.md` (key identifier tokenised, wrap and unwrap counts and latencies, the fail-closed result, `/readyz` component states). Spend cap (proposal): USD 5. Register row: G18 (Commercial only; Government OPEN).
- Ends OPEN when no vault is approved, the identity lacks the role, or the setting cannot be applied.

### Item 3 - Hosted north-star run (PRP-109)
- Depends on: PRP-63 pipeline and PRP-82 hosted profile deployed.
- Procedure: operator runs the approved pipeline with `governance_profile=north-star`, supplies a webhook receiver and two steward identities and an auditor (sign-in steps are theirs); the agent runs `scripts/gates/north_star_seed.py`, drives the scenario through the product and runs `scripts/gates/north_star_evidence.py` on the output; capture is enabled for the synthetic domain only through the approval action.
- Evidence: `docs/evidence/governance/north-star-rerun-<UTC>.md` linking PRP-109's own evidence directory; the governance trail as ids and step timings only. Spend cap (proposal): USD 30 incremental on the deployed environment (a new environment is PRP-82's budget). Register rows: G06 (hosted capture sentence), G18 (hosted store sentence).
- Ends OPEN when the pipeline run is not approved or a step fails (the failing step is recorded as a defect against its owner PRP).

### Item 4 - Notification delivery per channel (PRP-107)
- Procedure: per channel the operator supplies a receiver, then the agent creates the channel and a subscription through the admin API, triggers `POST .../channels/{id}/test`, and reads `GET .../deliveries`; the operator confirms arrival independently. Channels: generic webhook with HMAC (operator-run receiver that checks the signature), Teams webhook (an operator-named tenant and channel), email (the verified transport from PRP-107's verification file, if built).
- Evidence: `docs/evidence/governance/notifications-<channel>-<UTC>.md` (delivery status, attempts, time to arrival, signature check result, no message body beyond ids and titles). Spend cap (proposal): USD 0 Azure; any relay cost stated by the operator. Register row: G19.
- Ends OPEN per channel not approved; a channel `not_built` in PRP-107 is OPEN (not built).

### Item 5 - Gateway enforcement on a throwaway gateway (PRP-112)  [serial-after: PRP-64]
- Depends on: PRP-64 item 3 (G17 manage) PASS or PARTIAL; otherwise OPEN (not run).
- Command: `NS_LIVE_APPROVED=1 uv run python scripts/gates/g17_apim_enforce_live.py <arguments from its --help>` with `--approve-step` per step the operator approves (apply to one canary product, call a disallowed deployment and expect a deny, call an allowed one, rollback, verify removal); throwaway Standard v2 APIM only.
- Evidence: script output copied to `docs/evidence/governance/gateway-enforce-<UTC>.md` (deny and allow status codes, fragment diff digest, rollback verified). Spend cap (proposal): USD 40. Register row: G17 (enforcement sentence).
- Ends OPEN when any step is unapproved or fails; resumable through the state file; Government stays OPEN.

### Item 6 - Gateway content source (PRP-111)
- Command: `NS_LIVE_APPROVED=1 uv run python scripts/gates/gateway_capture_live.py <arguments from its --help>` against a throwaway APIM with message logging enabled and a synthetic prompt; a capture policy covering that gateway must exist and be approved first.
- Evidence: `docs/evidence/governance/gateway-capture-<UTC>.md` (log table columns present or absent, rows read, redaction states, nothing raw stored; no content in the file). Spend cap (proposal): USD 25. Register row: G06 sentence.
- Ends OPEN when logging cannot be enabled or the columns are absent (record which; the gateway is then not a content source).

### Item 7 - Entra entitlement read (PRP-118)
- Command: the connector's `live_check.py` (path in PRP-118's completion note) with `NS_LIVE_APPROVED=1`, a tenant the operator names and a read-only application whose admin consent the operator granted.
- Evidence: `docs/evidence/governance/entra-identity-<UTC>.md` (which signals returned data, counts, pages, throttling, coverage state shown by the product; identities tokenised). Spend cap: USD 0 (read only). Register row: G04 sentence.
- Ends OPEN when consent is not granted by the operator; the session never grants or requests consent itself.

### Item 8 - Purview read (PRP-120)
- Command: the connector's `live_check.py` with `NS_LIVE_APPROVED=1`, a Purview account and the read role the operator granted; no scan is started and no label, collection or asset is edited.
- Evidence: `docs/evidence/governance/purview-<UTC>.md` (labels and classifications seen as counts by type, assets matched to catalog resources, lineage edges read, coverage banner state). Spend cap: USD 0. Register row: G04 sentence.
- Ends OPEN when no account or role is approved; Government OPEN unless PRP-120 verified it and the owner names a subscription.

### Item 9 - Unity Catalog read and lineage push-back (PRP-121)
- Command: read check with `NS_LIVE_APPROVED=1` and a workspace the operator names (read privilege only). The push-back is a separate step with its own `--approve-step`: dry-run, push of one synthetic lineage edge to a throwaway target, read-back, rollback, only for targets PRP-121 verified.
- Evidence: `docs/evidence/governance/unity-<UTC>.md` and `lineage-push-<UTC>.md` (counts, dry-run digest, read-back result, rollback result). Spend cap (proposal): USD 10 for a serverless 2X-Small warehouse. Register row: G04 sentence.
- Ends OPEN per step not approved; the push never targets a shared enterprise catalog.

### Item 10 - Microsoft 365 Copilot and Copilot Studio (PRP-122)
- Command: `live_check.py` with `NS_LIVE_APPROVED=1`, a tenant the operator names, an admin-consented application and a Copilot licence the owner holds.
- Evidence: `docs/evidence/governance/m365-copilot-<UTC>.md` (per signal: returned, empty, forbidden or not licensed; aggregates only; no per-user data). Spend cap: USD 0. Register row: G04 sentence.
- Ends OPEN without tenant, consent or licence; a signal that returned nothing is recorded as such, not as zero.

### Item 11 - GitHub Copilot and Cursor (PRP-123)
- Command: `live_check.py` per vendor with `NS_LIVE_APPROVED=1`, an organisation or team the operator names and a scoped credential the operator installed in the vault.
- Evidence: `docs/evidence/governance/github-copilot-<UTC>.md`, `cursor-<UTC>.md`. Spend cap: USD 0 plus any seat or plan cost the owner already carries. Register row: G04 sentence.
- Ends OPEN per vendor; Cursor stays `GAP` when no admin API was verified.

### Item 12 - OpenAI ChatGPT Enterprise (PRP-124)
- Command: `live_check.py` with `NS_LIVE_APPROVED=1`, a workspace the operator names and a credential the operator installed; compliance records only if PRP-124 verified them and the licence is held.
- Evidence: `docs/evidence/governance/openai-enterprise-<UTC>.md`. Spend cap (proposal): USD 5 (usage endpoints can be billable or rate limited; the script states its call cap). Register row: G04 sentence.
- Ends OPEN without workspace, credential or licence.

### Item 13 - Anthropic organisation usage (PRP-125)
- Command: `live_check.py` with `NS_LIVE_APPROVED=1`, an organisation the operator names and a credential the operator installed.
- Evidence: `docs/evidence/governance/anthropic-<UTC>.md`. Spend cap (proposal): USD 5. Register row: G04 sentence.
- Ends OPEN without organisation or credential.

### Item 14 - Entra shadow-AI sources (PRP-126)
- Command: `live_check.py` with `NS_LIVE_APPROVED=1`, a tenant the operator names and a read-only application with the consent the operator granted; sign-in data is personal data, so the evidence holds only application-level counts.
- Evidence: `docs/evidence/governance/shadow-ai-<UTC>.md` (sources that returned data, applications found as counts, pseudonymisation check). Spend cap: USD 0. Register row: G04 sentence.
- Ends OPEN per source not approved or unavailable.

### Item 15 - CI registration gate with workload identity federation (PRP-129)
- Procedure: operator creates an Entra application with a federated credential for a named private test repository and grants it the role that holds `registration.check`; the agent runs the sample workflow from `docs/integrations/cicd.md` once for a registered, approved agent version (expect exit 0) and once for an unregistered one (expect exit 1) against a deployed environment, and once with the credential removed (expect a refusal and exit 2 or the documented code).
- Evidence: `docs/evidence/governance/ci-gate-<UTC>.md` (workflow run reference tokenised, the three exit codes, reason codes, token never printed). Spend cap (proposal): USD 2. Register row: G20.
- Ends OPEN without a repository or application; Government OPEN.

### Item 16 - GitHub Issues ticket creation (PRP-133)
- Command: `live_check.py` with `NS_LIVE_APPROVED=1`, a private test repository the operator names and a narrowly scoped credential the operator installed; one issue is drafted through the executor, approved, created, read back and closed.
- Evidence: `docs/evidence/governance/github-issues-<UTC>.md` (dry-run digest, read-back result, closure; no issue body beyond ids and links). Spend cap: USD 0. Register row: G04 sentence (ticketing).
- Ends OPEN without repository or credential; ServiceNow and Jira are not run.

### Item 17 - Embedding endpoint and hybrid search (PRP-135)  [serial-after: PRP-135]
- Procedure: operator approves an embedding deployment inside the deployment's own boundary and sets `NS_SEARCH_MODE=hybrid` and the `NS_EMBEDDING_*` values in their shell; the agent runs PRP-135's live check (name in its completion note), then the retrieval evaluation with real embeddings (lexical versus hybrid on the PRP-80 groundedness retrieval questions), recording recall at k and the budget counters.
- Evidence: `docs/evidence/governance/embedding-<UTC>.md`. Spend cap (proposal): USD 10; the script states its own item cap and expected cost first. Register row: G21.
- Ends OPEN when no deployment is approved; a lexical-better result is recorded as found.

### Item 18 - Integration and close-out  [serial-after: PRP-64]
- Deliverable: after PRP-64's close-out has merged, edit only the register rows listed under Ownership in one close-out commit; write `changelog.d/PRP-136.md`; regenerate `PRPs/INDEX.md` and the status table (`python scripts/prp_status.py --write`); fill the completion note table (item, outcome, evidence, spend, row); file follow-up issues (drafted text, filed only with the operator's go-ahead); tell the operator which gates remain OPEN and which follow-ups exist.
- Owned files: `docs/RESEARCH-AND-GATES.md` (rows listed under Ownership only), `changelog.d/PRP-136.md` (new), this PRP file.
- Acceptance criteria: every item has an outcome row; no register row outside this PRP's list is touched; the GUID grep in Validation gates is clean.
- Tests: `uv run pytest -q tests/unit/gates tests/docs`.

## Cut line
The session is attended and each item stands alone, so any subset merges safely: items with no approval are recorded `OPEN (not run)` and the close-out still commits the rows for what ran. If the operator's time is short, the order of value is items 2, 3, 4, 5, 15 (the north-star chain and the enforcement and CI controls), then the connectors (7 to 14, 16), then 17. Nothing needs to be rerun to merge the rest later.

## Validation gates
```bash
python scripts/validate_planning.py
uv run pytest -q tests/unit/gates tests/docs
python scripts/prp_status.py --check
git grep -nE "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}" -- docs/evidence/governance
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
The `git grep` must print nothing.

## Migration and rollback
None: evidence files and register text only. Rollback is reverting the close-out commit; a live resource created for a run is torn down in its item and the teardown is recorded.

## Live and open gates
This PRP is the live step. Every item needs `NS_LIVE_APPROVED=1` set by the operator and a named target; with no approval an item is OPEN (not run). Government subscriptions, AWS and GCP key-wrap, ServiceNow and Jira, and any connector that PRP-117's coverage page shows as `not_built` stay OPEN with the reason. Nothing here is a compliance, authorization or availability claim.

## NOT building
Product code, new scripts (a gate-script fix only), a CI job that runs live gates, a scheduled live check, Purview or Entra role grants, tenant or consent changes, scans or edits in any customer catalog, a Government run, parity or authorization claims, and any evidence that contains captured content or personal data.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (row 2, the register ids, is an ASSUMPTION for plan approval)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | serial-after PRP-64 |
| 6 | todo | | |
| 7 | todo | | |
| 8 | todo | | |
| 9 | todo | | |
| 10 | todo | | |
| 11 | todo | | |
| 12 | todo | | |
| 13 | todo | | |
| 14 | todo | | |
| 15 | todo | | |
| 16 | todo | | |
| 17 | todo | | serial-after PRP-135 |
| 18 | todo | | serial-after PRP-64 |

## Completion note (filled at ship)
- Date, PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
