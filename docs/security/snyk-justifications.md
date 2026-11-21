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

## Path traversal on `--registration` (hosted gate scripts, PRP-139)

- Where: `scripts/gates/hosted_demo_seed.py` (`_demo_environment_refusal`) and
  `scripts/gates/hosted_purge_synthetic.py` (`_checks`), reported low by the scan of
  `scripts/gates` on 2026-11-21. The other six findings of that scan are in code this PRP did not
  write (`g04_connectors_live.py`, `hosted_smoke.py`, `hosted_demo.py`, and the role id constant in
  `_hosted_demo_common.py` above) and were not triaged here.
- Why it is accepted: both are operator-run command line tools, and the value is the path of the
  operator's own registration file, given by the same person who runs the script. The file is only
  read and parsed as JSON; nothing is written to that path and no part of its content is printed.
  A missing or malformed file is a refusal with a fixed message.
- Status: not fixed, justified. No `.snyk` file was added. The new packages
  `neurosphere_core.sources_status`, `neurosphere_workers.sources_status` and
  `neurosphere_api.sources_status` scanned clean on the same date.
