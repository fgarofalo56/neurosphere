### Added
- PRP-50: gateway poll records a distinct `stalled` status (with the stalled slice start in the log fields, watermark held) when a source reports `stalled_slice_start`.
- PRP-50: billing export counts restated closed days in `last_status.restated` and logs `billing_export.restated` with counts only; the first posted amount still wins.
- PRP-50: Foundry discovery counts deployment-name collisions between projects in `TickStats.collisions`.
- PRP-50: connector SDK exports `check_capable` and a shared `tracked` health decorator; `move` and `copy` without `from_` return `verifiable=False` with reason `missing_from`; the contract kit names the missing write-protocol member.

### Changed
- PRP-50: `FoundryDiscoveryPoller` refuses a `domain_id` without the runtime `cloud:customer:` prefix (`InvalidSchemaError`) and logs discovered names at debug level only.
- PRP-50: Azure Monitor slice halving works from the actual clipped span; the apim-gateway and foundry-actions connectors use the SDK `tracked`.

### Fixed
- PRP-50: the OTel connector rejects `evilvault.azure.net` and other non-dot-bounded Key Vault hosts (`unrecognized_vault_host`); the span exporter's closed check and pending registration now share one lock, closing an export-versus-shutdown race.
