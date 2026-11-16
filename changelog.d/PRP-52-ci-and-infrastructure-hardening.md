### Added
- PRP-52: `scripts/ci/install-scanners.sh` installs syft, trivy and grype by pinned version and sha256 for every security job; an aggregator check `images (all scans)` fails when images exist but a scan was skipped or failed.
- PRP-52: `scripts/render_mermaid.py --source-dir` renders every block in `docs/security/dfd`, run by the `mermaid` CI job.
- PRP-52: APIM module parameter `uiApiRateLimitCalls` (default 0, off) applies a service-level `rate-limit-by-key` policy, only when the service is created.
- PRP-52: the network module allows `AzureLoadBalancerInbound`; `vnetAddressPrefix` is a root parameter of `modules/main.bicep`.
- PRP-52: `licenses_report.py` resolves bumped platform-binary families from an installed sibling package and fails under `CI` when a row was carried forward and is not on the cited allowlist.

### Changed
- PRP-52: the Helm chart requires `env.NS_CLOUD` (`commercial` or `government`); values files that omit it no longer render. Set it in every values file.
- PRP-52: `security.yml` passes matrix values through `env:` and runs `trivy fs --include-dev-deps`; the `egress-compose` job dumps bounded compose logs on failure; the four copies of `skip_or_fail` are one shared helper.
- PRP-52: runtime images drop `sqlite-libs` and the four matching Grype ignore rules are removed; `neurosphere_core.analytics.base.stub` imports `sqlite3` lazily.
- PRP-52: Dependabot ignores `datamodel-code-generator` updates (the pin is a deliberate contracts decision).
