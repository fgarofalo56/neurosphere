# Versioning policy

This policy covers the NeuroSphere product version, the contract schema versions and the
migration versions, and how they relate. It is a build rule, not a compliance statement.

## Product version (SemVer)

- The product follows [Semantic Versioning 2.0.0](https://semver.org/): `MAJOR.MINOR.PATCH`.
- **One product version** covers the three container images (api, workers, frontend) and the
  Helm chart. Chart `version` and `appVersion` both equal the product version, image tags
  equal it, and the git tag is `vX.Y.Z`. There is no per-component version.
- Pre-release tags use `vX.Y.Z-rc.N`. They publish like a release but are marked as
  pre-releases and are never the default install target.
- **Pre-1.0 rules (`0.y.z`)**: a MINOR bump may contain breaking changes; a PATCH bump is
  fixes only. Breaking changes are still called out in the release notes (see below). From
  `1.0.0`, breaking changes require a MAJOR bump.
- Bump choice: `feat` commits move MINOR, `fix`/`perf` commits move PATCH, and any commit
  marked `!` or carrying a `BREAKING CHANGE:` footer moves MINOR before 1.0 and MAJOR after.

## Contract schema versions

- Contract schemas live under `packages/contracts/schemas/<area>/v<major>/` (ADR-0004).
  Each area has its own `vN` directory and evolves independently of the product version.
- **Additive-only within a `vN` directory.** Allowed: new optional fields, new enum values
  that consumers are documented to tolerate, new schema files. Not allowed: removing or
  renaming a field, tightening a type, making an optional field required.
- A breaking contract change is never an edit of `v1`. It is a new `v2` directory next to
  `v1`; both are served until `v1` consumers are gone (see expand-then-contract below).
- Product releases do not renumber schemas. The release notes record the contract versions
  shipped (for example "catalog v1, actions v1, telemetry v1, evaluation v2").

## Migration versions

Migrations (PRP-13 item 4) carry ordered ids per target, recorded in a ledger. Targets are
Cosmos documents (a `schema_version` per document type) and analytics schema versions
behind the analytics adapters. Migration versions advance only when a persisted shape
changes, so they are independent of the product version and of the contract `vN`.

## Mapping

| Product release | Contract schemas | Migration ledger |
|---|---|---|
| `0.y.z` | Each area at its highest `vN` present in `packages/contracts/schemas/` | Highest applied migration id per target |
| Patch (`0.y.Z+1`) | Unchanged | Unchanged unless a fix needs a data repair, which ships as its own migration id |
| Minor (`0.Y+1.0`) | May add optional fields or a new `vN+1` directory | May add migration ids |

Every release's notes list the contract versions per area and the migration ids per target
that the release expects. An operator upgrading from release A to release B applies the
migrations between those ledgers before switching traffic.

## Expand then contract (two releases)

Removing something persisted or published always takes at least two releases:

1. **Release N (expand and deprecate).** Add the new field, schema version or migration
   id. Keep the old one working. Mark the old one deprecated in code, in the release notes
   (`### Deprecated`, via a `Deprecated:` commit footer) and in docs.
2. **Release N+1 or later (contract).** Remove the deprecated field or retire the old `vN`
   directory, with a migration where stored documents change.

A migration may never remove a field in the same release that deprecates it. Rollback
paths stay valid because release N still reads and writes both shapes.

## How versions reach the release notes

Release notes come from conventional commits (`CONTRIBUTING.md`) through
`scripts/release/changelog.py`:

| Commit | Section |
|---|---|
| `feat` | Added |
| `fix` | Fixed |
| `perf`, `refactor` | Changed |
| `revert` | Removed |
| `deprecate` type, or `Deprecated:` footer | Deprecated |
| `fix(security):`, `sec` type, or `Security:` footer | Security |
| `!` after the type, or `BREAKING CHANGE:` footer | Entry marked **BREAKING** plus a `### Breaking changes` note |
| `chore`, `ci`, `docs`, `test`, `build`, `style` | Omitted but counted; `--include-maintenance` lists them |
| Anything else | Listed verbatim under `### Unclassified`, never dropped |

Merge commits are skipped. Review the Unclassified list before tagging; fix it by editing
the generated section, not by rewriting history.

The operator process is in [release-process.md](release-process.md).
