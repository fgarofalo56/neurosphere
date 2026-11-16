### Added
- PRP-54: with `NS_WRITE_TARGETS_FROM_STORE=true` the API and the `actions` worker register write targets from the stored `write_targets` entries (PRP-45) instead of only from `NS_FOUNDRY_*` and `NS_APIM_*` env; the env path is the fallback and the default.
- PRP-54: `WriteTargetRegistry` gains an additive `target_key` (the intent's domain id) on `register`, `get`, `supports` and `target_keys`, so several connectors of one kind (for example two APIM gateways) coexist; `get(name)` with several keys and none given refuses with `target_ambiguous`.
- PRP-54: compose, the Helm chart (`writeTargets.fromStore`, `writeTargets.{foundry,apim}`) and `infra/demo/main.bicep` (`writeTargetsFromStore`) carry the opt-in, default off; runbook `docs/runbooks/write-targets.md`.

### Changed
- PRP-54: `ActionPlane.connector_for` takes the intent's domain id and all call sites pass it; a domain with no registered target stays advisory. Duplicate targets in one domain are refused (`write_target_duplicate_domain`).
