### Added
- PRP-21 (round 2): per-domain admission limiter wired into the API through `require_permission` (off by default, `NS_ADMISSION_ENABLED`, `NS_ADMISSION_POLICY_FILE`; 429 `rate_limited` with `Retry-After`), peer cells through `NS_FEDERATION_PEERS_FILE` over `HttpCellClient` with boundary host allowlists, https-only and serving-cloud checks, a configurable summary cache TTL ceiling (`NS_FEDERATION_CACHE_MAX_TTL_SECONDS`), a t-quantile FinOps forecast band for small samples, a `/otlp/metrics` load scenario, compose and Helm quota mounts, the `docs/runbooks/admission-and-federation.md` runbook and compose pilot evidence under `docs/evidence/G07/pilot/` (bounded feasibility, 1 of 3 thresholds passed; PR #282).

### Changed
- A federation cell that answers for another cell, cloud, boundary or customer is now reported `unavailable` instead of aborting the merge; the merged window is min start / max end; all cells `denied` returns 403.
