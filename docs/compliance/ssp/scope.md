# SSP scope and customer inputs

- Scope: what the NeuroSphere control mapping covers, the customer inputs it depends on, and where FedRAMP and DoD scope are tracked. Machine-readable mapping: [control-mapping.yaml](control-mapping.yaml). Per-family narratives: [families/](families/).
- Status vocabulary: `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`. No status is an assessment result or an authorization decision.
- Statement: not FedRAMP authorized; the authorizing official decides. No certification date or authorization date is promised, and no compliance percentage is given.

## What the NIST mapping covers

The mapping lists the NIST SP 800-53 Rev 5 controls NeuroSphere plausibly implements or inherits, across the families AC, AT, AU, CA, CM, CP, IA, IR, MA, PE, PL, PM, PS, PT, RA, SA, SC, SI and SR. It is source material for the customer's own system security plan. It is not an assessment, and a control listed as `implemented_tested` means a repository test exercises the behaviour, not that an assessor accepted it.

Controls inherited from the cloud platform are recorded in the [responsibility matrix](../responsibility-matrix.md) and the dated register at `docs/evidence/G02/register.yaml`. Inherited controls do not automatically authorize this application.

## Customer inputs (all OPEN)

The following are required from the customer and are not guessed here. Until each is provided, the dependent gate stays OPEN (G06 for privacy and retention, G02 for the boundary and ATO).

| Input | Owner | Status | Why it is needed |
|---|---|---|---|
| Data classification | Customer data owner | OPEN | A missing classification is treated as restricted; nothing is assumed |
| Payload opt-in (prompt and response bodies) | Customer privacy officer | OPEN | Bodies are off by default and are retained only by explicit opt-in |
| Retention periods | Customer records officer | OPEN | The lifecycle engine ships no built-in values and fails closed |
| Legal hold process | Customer legal and records office | OPEN | The engine honors holds set through its interface; the process is the customer's |
| Authorizing official | Customer agency | OPEN | The authorization decision is the authorizing official's |
| Agency baseline (Low, Moderate or High, plus overlays) | Customer authorizing official | OPEN | No baseline is selected in this repository |

## FedRAMP and DoD scope (tracked separately)

This section is deliberately not part of the NIST mapping and the two must not be merged.

- Azure Government, GCC, GCC High and DoD impact levels are different environments. They are not interchangeable, and a statement about one says nothing about another.
- A service appearing in a FedRAMP or DoD audit-scope listing is a fact about that service. It is not an authorization of this workload.
- Per-dependency availability, GA or preview status and authorization-boundary status are kept as separate facts in `docs/evidence/G02/register.yaml`.
- Government data is never bridged to Commercial to fill a feature gap.
- Agency authorization, any FedRAMP or DoD determination and the in-cluster no-Commercial-egress proof remain OPEN (gate G02 in `docs/RESEARCH-AND-GATES.md`).

## Related documents

- [Plan of action and milestones template](../poam.md)
- [Threat model](../../security/threat-model.md)
- [Responsibility matrix](../responsibility-matrix.md)
