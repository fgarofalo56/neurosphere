### Added
- PRP-38: `.github/workflows/real-stack.yml` runs the real-stack pytest suites against the compose emulators (job `real-stack`) and a headless Playwright run with the in-process dev issuer (job `real-stack-browser`), PR #278. Both are non-required until green for a week.
- PRP-38: `sbx_seed_stack.py --grants-only`, a seeded gateway registration, and headless flow specs for catalog and curation, quality, actions and copilot under `frontend/tests/real-stack/flows/`.

### Changed
- PRP-38: `make stack-up` now seeds the worker grants before the app profile starts, then runs the full seed (#205).

### Fixed
- PRP-38: `make replay` wraps valid telemetry lines in the `HubMessage` envelope instead of quarantining them as `invalid_wire` (#162); the first-seed `skipped_existing` assertion no longer depends on timing (#211).

### Removed
- PRP-38: the unused `OPT_IN_ROLES` tuple in the worker role registry (#180).
