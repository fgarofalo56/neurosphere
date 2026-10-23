# Continuous monitoring plan

> **Scope:** What is monitored in the repository, pipeline and a customer-hosted deployment, by whom, and which monitoring depends on customer decisions.
> **Status vocabulary:** `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
> **Statement:** NeuroSphere is not FedRAMP authorized; the authorizing official decides. This document supports the customer security team and the authorizing official. It is not an assessment, makes no authorization, ATO, parity or certification claim, and carries no authorization date or compliance score.
> **Provenance:** PRP-23 item 4. Customer-owned inputs are recorded as `customer` and OPEN; they are never guessed here.

Links: [incident response plan](incident-response-plan.md), [change management plan](change-management-plan.md), [contingency plan](contingency-plan.md), [boundary and data-flow diagrams](boundary-and-data-flow.md), [responsibility matrix](../responsibility-matrix.md), [threat model](../../security/threat-model.md), [DoD checklist](../../release/dod-checklist.md), [SLO notes](../../ops/slo.md). Security runbooks: [rotation](../../security/runbooks/secret-rotation.md), [incident response](../../security/runbooks/incident-response-plan.md).

## 1. What is monitored

| Area | Mechanism | Frequency | Owner | Status |
|---|---|---|---|---|
| Secrets in source | Gitleaks over full history, tracked credential-shaped files, PII pattern scan (`.github/workflows/secret-scan.yml`); weekly re-scan | each push and weekly | maintainers | `implemented_tested` |
| Code and dependency vulnerabilities | CodeQL, `pip-audit`, `pnpm audit`, dependency and licence gate (`.github/workflows/codeql.yml`, `security.yml`, `dependabot-licences.yml`) | per change and scheduled | maintainers | `implemented_tested` |
| Supply chain | SBOM and scan outputs from the security workflow | per release | maintainers | `implemented_tested` locally; deployed-image scanning `planned` |
| Contracts and schemas | contracts workflow | per change | maintainers | `implemented_tested` |
| Planning and claims | `scripts/validate_planning.py`; statement checker for `docs/compliance/` (PRP-23 item 3) | per change | maintainers | `implemented_tested` |
| Application actions | Append-only audit store: intent, approval, before and after, denied actions; exportable to a SIEM | continuous | customer SOC | event content `implemented_tested`; SIEM wiring `customer` |
| Telemetry pipeline health | Ingestion lag, quarantine depth, coverage and freshness shown in the product; cost freshness labelled estimated vs invoiced | continuous | customer operations | `designed` |
| Cloud resources | Azure Monitor, Log Analytics, Application Insights, Key Vault diagnostics, Defender where the customer enables them; Government connection-string endpoint override | continuous | customer | `customer` |
| Service availability changes | Dated G02 register (`docs/evidence/G02/register.yaml`); availability, GA and authorization tracked as separate facts | re-verify before each release and on Microsoft announcements | maintainers and customer | `implemented_tested` as register; refresh `planned` |
| Backups and restore | Restore drill evidence in `docs/evidence/G07/dr/`; see the contingency plan for what is and is not measured | per exercise | customer | compose drill done; production cadence `customer`, OPEN |
| Retention and deletion | Lifecycle job results with read-back verification; blocked requests queued and audited | continuous | records officer (customer) | engine `implemented_tested`; policy `customer`, OPEN (G06) |
| Key and credential rotation | [secret-rotation.md](../../security/runbooks/secret-rotation.md) | per schedule the customer sets | customer | procedure `designed`; schedule `customer` |

## 2. Evidence for the authorizing official

The PRP-23 evidence inventory (`docs/evidence/inventory.md`) indexes scan outputs, test evidence and configuration baselines with path, hash and source date, and lists missing evidence as `missing`. The POA&M template tracks weaknesses found by the monitoring above; the plan does not pre-fill completion dates. Both are inputs to the customer's own reporting.

## 3. Review triggers

Re-review this plan, the boundary diagrams and the SSP narratives when: a new cloud, region or analytics adapter is enabled; a new connector or write target is added; the action executor, audit store or lifecycle conflict rules change; a Microsoft service changes availability or audit-scope listing; or a security incident closes with a boundary lesson. What counts as a significant change that requires the authorizing official's reassessment is decided by that official.

## 4. Known gaps (OPEN)

- No deployed instance has been monitored; this plan is a design plus repository and pipeline monitoring that exists today.
- In-cluster proof of no Commercial egress from a Government deployment has not run (G02).
- Production-sized restore and Event Hubs failover have not been measured (G07).
- Retention periods and legal hold process are not provided (G06).

## 5. Customer inputs (OPEN, not guessed)

| Input | Status |
|---|---|
| Monitoring frequency and reporting cadence required by the agency baseline | `customer`, OPEN |
| Alert thresholds, on-call and escalation | `customer`, OPEN |
| Vulnerability remediation timelines | `customer`, OPEN; agency baseline decides |
| Authorizing official and reporting recipients | `customer`, OPEN |
| Log retention periods and SIEM destination | `customer`, OPEN |
| Third-party assessor involvement, if any | `customer`, OPEN |
