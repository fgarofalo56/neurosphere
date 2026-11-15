### Added
- PRP-68: changelog fragments (`changelog.d/<PRP file stem>.md`) assembled into `CHANGELOG.md` at release time by `scripts/changelog_assemble.py` (`--check`, `--preview`, `--write`, standard library only), so parallel close-outs no longer conflict on `[Unreleased]`.
- PRP-68: `scripts/prp_index_check.py`, a structural `PRPs/INDEX.md` freshness check run by `scripts/validate_planning.py`; the CI `planning` job also runs `prp_execution_plan.py --check` and the fragment check; `.githooks/pre-commit` blocks malformed staged fragments and warns on a stale execution plan.
