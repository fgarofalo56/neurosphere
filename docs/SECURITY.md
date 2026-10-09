# NeuroSphere security baseline — v1.1
Entra authentication/resource-scoped RBAC/ABAC at API, queries, search, copilot/tools, exports, caches, MCP and push. Managed identities where supported; vault credential references. Development identity never authenticates production.
Copilot treats untrusted content as data. Bounded allowlisted tools and query/chart schemas prevent arbitrary code/query execution. Current permission checks at execution, exact expiring confirmation, maker-checker policy, idempotency, verified outcome and rollback.
Private networking/default-deny egress with supported exceptions; MCP OAuth scope/audience validation, no token passthrough, approved servers and SSRF/confused-deputy defenses. Revocation invalidates push/cache sessions.
Redact before persistence/transmission; prompts/responses off by default. Pseudonymize people; payload opt-in and bounded retention/legal holds. Append-only before/after/denied-action audit evidence with SIEM export.
Threat model, SBOM/dependency/container/secret scans, incident response, rotation, backup restores and continuous monitoring required. Public docs assistant isolated from production and read-only over published content.
ATO accelerator is not authorization. Service availability/authorization does not authorize NeuroSphere. See RESEARCH-AND-GATES.md G02/G06/G08.
