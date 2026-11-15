### Added
- PRP-23: lifecycle API (`/api/v1/lifecycle/holds`, `/requests`, `/status`) behind the new `lifecycle.manage` permission, a Cosmos-backed lifecycle job store, and delete backends for the catalog, ledger and archive. The lifecycle worker now runs jobs, in dry-run by default (`NS_LIFECYCLE_MODE`, `NS_LIFECYCLE_POLICY_FILE`, `NS_LIFECYCLE_MAX_ATTEMPTS`), PR #276.
- PRP-23: bounded retry of FAILED queued lifecycle outcomes with backoff, then `failed_final`.

### Changed
- PRP-23: compliance statement checker negation is clause-scoped, evidence collector checks resolved-path containment, CA-7, CP-2 and PM-5 control statuses upgraded (#120).
