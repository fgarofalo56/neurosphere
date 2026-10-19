# Security runbooks

Operational runbooks for secrets and incident handling (PRP-12 Item 5). They
describe what the repository does today and make no FedRAMP/ATO claim.

| Runbook | Use it when |
|---|---|
| [key-vault-references.md](key-vault-references.md) | Wiring a secret into a workload (CSI, App Service, Bicep) |
| [secret-rotation.md](secret-rotation.md) | Scheduled or planned credential rotation |
| [credential-leak-response.md](credential-leak-response.md) | A credential reached a commit or remote: rotate first, then clean history |
| [incident-response-plan.md](incident-response-plan.md) | Any security incident: severity, roles, flow |
| [pre-push-checklist.md](pre-push-checklist.md) | Before committing or pushing |

Rules common to all: placeholders only (`<vault-name>`), verify by presence and
behaviour never by value, and see `SECURITY.md` at the repo root.
