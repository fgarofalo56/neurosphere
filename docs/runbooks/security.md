# Security runbook (pointer)

> **Status: DRAFT.** Not yet validated by an independent new-user test. See [new-user-test.md](new-user-test.md).

This page does not restate security procedures. Use the owning documents:

| Situation | Go to |
|---|---|
| Any security incident | [incident-response-plan.md](../security/runbooks/incident-response-plan.md) |
| A credential reached a commit or remote | [credential-leak-response.md](../security/runbooks/credential-leak-response.md) (rotate first, then clean history) |
| Planned rotation | [secret-rotation.md](../security/runbooks/secret-rotation.md) |
| Wiring a secret into a workload | [key-vault-references.md](../security/runbooks/key-vault-references.md) |
| Before committing or pushing | [pre-push-checklist.md](../security/runbooks/pre-push-checklist.md) |
| Threat model | [threat-model.md](../security/threat-model.md) |
| Compliance planning artifacts | [docs/compliance/](../compliance/plans/README.md) and [responsibility-matrix.md](../compliance/responsibility-matrix.md) |

Index of the security runbooks: [README.md](../security/runbooks/README.md). Nothing here claims FedRAMP authorization, ATO or compliance parity; Government availability is gated, see [RESEARCH-AND-GATES.md](../RESEARCH-AND-GATES.md).

Local pre-push guard install:

```bash
bash scripts/install-git-hooks.sh
```
