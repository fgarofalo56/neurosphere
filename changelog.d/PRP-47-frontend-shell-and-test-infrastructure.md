### Changed
- PRP-47: shell navigation supports ArrowUp and ArrowDown, the last-domain key is cleared whenever the account disappears, and the deployment default theme applies before the shell renders (sign-in redirect screen). Finance demo domain now holds `catalog.curate`, PR #298.
- PRP-47: Vitest fails on unhandled MSW frames, retries once in CI only, the demo build has a positive-control prod-exclusion test, and `paths.ts` exists for dashboards, actions and review.
