# Compliance evidence

NeuroSphere maps the metadata it already observes about a customer's AI estate to the controls of
four frameworks and exports that mapping as an evidence bundle per domain and framework. It maps
and collects. It does not determine compliance, give a score or reach a finding about the estate.

Status: NeuroSphere is not FedRAMP authorized; the authorizing official decides. Nothing in a
bundle, the page or this runbook is an assessment, an attestation or a legal opinion.

## What is mapped

| Framework | Library id | What the library names |
|---|---|---|
| NIST AI Risk Management Framework 1.0 | `nist_ai_rmf` | Core categories (GOVERN, MAP, MEASURE, MANAGE) |
| SR 11-7 model risk management guidance | `sr_11_7` | Guidance sections IV to VI (development, validation, governance) |
| HIPAA Security Rule technical safeguards | `hipaa_technical_safeguards` | 45 CFR 164.312 and the information system activity review specification of 164.308(a)(1)(ii)(D) |
| OMB M-25-21 | `omb_m_25_21` | Governance roles and the minimum practices for high-impact AI |

Control ids and titles were read from the official sources on the date recorded on every control
(`source_retrieved`) and are short paraphrases with a link, never copied text. The library is YAML
package data under `packages/core/neurosphere_core/compliance/library/`. Control ids are stable;
other features cite them.

## Evidence sources

Five read-only sources return counts, timestamps and ids only. No entity body, prompt, response or
principal name is read into a bundle.

| Source id | Reads | Main measures |
|---|---|---|
| `catalog_ownership` | active owner entities of the domain | owners, owners with a recertification date, owners past it, recertified in the window |
| `audit_chain` | the domain's audit hash chain, verified up to a cap | records, whether the chain verified |
| `hitl_decisions` | review items of the domain | decisions taken in the window |
| `evaluation_results` | evaluation results completed in the window | results, completed, partial or failed |
| `cost_attribution` | ledger entries of the domain in the window | entries with and without a cost center |

Every read takes a window (default 30 days) and a cap, and reports when the cap cut it off.

## How to read a bundle

Each mapped control carries two words that are not verdicts.

- NeuroSphere support: `designed`, `implemented_tested`, `inherited`, `customer`, `planned` or
  `not_applicable`. `customer` means the control stays with the customer.
- Evidence summary: `evidence_present` (every mapped source answered with records),
  `evidence_partial` (some did, or a source was capped), `no_evidence` (none did) or
  `customer_responsibility`.

Each observation has a status: `observed`, `partial` (capped), `unavailable` (the store is missing
or down; the reason code says why) or `not_collected` (the source cannot count this). An unknown
count is shown as unknown and is never 0. `evidence_present` means records were observed, not that
a control is met.

## What a bundle does not say

- It does not say any control is met or that the estate meets a framework, and it names no
  authorization decision.
- It holds no score, percentage, pass or fail.
- It does not cover controls that live outside the observed stores. Controls marked
  `customer_responsibility` need the customer's own evidence.
- It is computed per request and stored nowhere. The digest (sha256 over the canonical JSON) lets
  you check a saved copy; attestation and history are not part of this feature.

## Using it

1. Sign in as a Security Auditor. `evidence.read` on the domain is required; Admin does not hold it.
2. Open Compliance evidence, pick a domain and a framework.
3. Open a control for its official source link and the observations behind it.
4. Download the bundle (JSON). The API also serves Markdown:

```text
GET /api/v1/compliance/frameworks
GET /api/v1/compliance/frameworks/{framework_id}
GET /api/v1/compliance/domains/{domain}/bundle?framework_id=...
GET /api/v1/compliance/domains/{domain}/bundle/export?framework_id=...&format=json|md
```

Every allowed bundle read appends one allowed-read audit record naming the domain and the number of
mapped controls. A refused read (403) is recorded as a denial. A missing store degrades that
source to `unavailable`; it does not fail the bundle.

## Environment variables

None. The feature reads the stores the API already has.

## Open items

- A live read of a hosted deployment's bundle is OPEN until the hosted data path runs.
- Visual baselines for the pages are Docker-only and are OPEN until generated in the pinned image.
