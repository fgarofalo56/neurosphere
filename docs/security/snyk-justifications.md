# Snyk Code justifications

Findings the maintainers reviewed and accepted. A `.snyk` ignore is added only when Snyk Code
accepts one for a concrete finding id; otherwise the justification lives here and the ignore is an
operator action in the Snyk UI.

## Path traversal on `--evidence-dir` (G01 live gate scripts)

- Where: `scripts/gates/g01_analytics_live.py` and `scripts/gates/g01_deploy_smoke.py`, both
  through `confine_evidence_dir` in `scripts/gates/_evidence_paths.py` (PRP-59, #214).
- Why it is safe: the CLI value is resolved with `Path.resolve()` and must be inside an allowed
  root (`docs/evidence/G01` or `docs/evidence/G01/analytics`) before any directory is created or
  file written; traversal and out-of-root absolute paths are refused with exit 2. Tests:
  `tests/unit/gates/test_g01_path_confinement.py`.
- Status: the scan of `scripts/gates` on 2026-11-16 reported no path-traversal finding after the
  two copies were merged into one helper, so no `.snyk` file was added. If a low reappears, ignore
  it in the Snyk UI citing `confine_evidence_dir` (operator action, UNVERIFIED whether Snyk Code
  honours a `.snyk` ignore for it).

## Hardcoded non-cryptographic secret in `_hosted_demo_common.py`

Reported by the same scan, outside PRP-59 ownership and unchanged by it. Not triaged here.
