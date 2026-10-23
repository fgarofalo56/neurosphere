# PT: PII Processing and Transparency (SSP narratives)

- Scope: NeuroSphere application controls mapped to NIST SP 800-53 Rev 5 family PT. Baseline selection is a customer input, see [scope.md](../scope.md). Machine-readable source: [control-mapping.yaml](../control-mapping.yaml).
- Status vocabulary: `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
- Statement: not FedRAMP authorized; the authorizing official decides. Inherited entries follow [the responsibility matrix](../../responsibility-matrix.md) and do not automatically authorize this application.

These narratives are source material for the customer's SSP. They are generated from `control-mapping.yaml`; edit the YAML, not this file.

## PT-2 Authority to Process Personally Identifiable Information

- Status: `customer`
- Implementing PRPs: PRP-07
- Owner: Customer privacy officer (privacy policy for real ingestion; gate G06)
- Evidence:
  - `packages/core/neurosphere_core/payload/guard.py`

Real ingestion is permitted only with authorized connectors and a customer privacy policy. People
are pseudonymized, and prompt and response bodies are off by default.

## PT-3 Personally Identifiable Information Processing Purposes

- Status: `planned`
- Implementing PRPs: PRP-23
- Owner: Customer privacy officer (purposes and lawful basis); PRP-23 item 1 (export filtering)
- Evidence: none yet

Lawful-basis handling for export is specified under PRP-23 item 1 and not yet in the repository.
