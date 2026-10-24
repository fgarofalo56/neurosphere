# ATO accelerator plans (index)

> **Scope:** Index of the boundary diagrams and the incident, contingency, change management and continuous monitoring plans for a customer-hosted NeuroSphere deployment.
> **Status vocabulary:** `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`.
> **Statement:** NeuroSphere is not FedRAMP authorized; the authorizing official decides. This document supports the customer security team and the authorizing official. It is not an assessment, makes no authorization, ATO, parity or certification claim, and carries no authorization date or compliance score.
> **Provenance:** PRP-23 item 4. Customer-owned inputs are recorded as `customer` and OPEN; they are never guessed here.

| Document | Purpose |
|---|---|
| [boundary-and-data-flow.md](boundary-and-data-flow.md) | Government and Commercial boundaries drawn separately, data flow, rendered SVGs |
| [incident-response-plan.md](incident-response-plan.md) | Deployment-level incident handling; links the PRP-12 runbooks |
| [contingency-plan.md](contingency-plan.md) | Recovery order, measured DR results (compose only), Event Hubs caveat |
| [change-management-plan.md](change-management-plan.md) | Product and runtime change control; links the PRP-13 DoD checklist |
| [continuous-monitoring-plan.md](continuous-monitoring-plan.md) | What is monitored, by whom, and what is OPEN |

Diagram sources and rendered SVGs: [diagrams/](diagrams/). The responsibility split is the [PRP-20 matrix](../responsibility-matrix.md). Open gates this set touches: G02 (boundary and agency decision) and G06 (retention and legal hold) stay OPEN and G07 (DR) stays OPEN; closure belongs to the customer and the authorizing official.
