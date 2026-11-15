# Changelog fragments

Each PRP close-out (and each change with no PRP) writes one fragment here instead of
editing `CHANGELOG.md`. Fragments are assembled into the `[Unreleased]` block at release
time by `python scripts/changelog_assemble.py --write` (see `docs/release/release-process.md`).

## File name

- `<PRP file stem>.md`, for example `PRP-68-changelog-fragments-and-index-freshness.md`
- `issue-<n>.md` for a change with no PRP

A second round of the same PRP appends to its own fragment while it is unreleased.

## Content

Only the Keep a Changelog headings `### Added`, `### Changed`, `### Deprecated`,
`### Removed`, `### Fixed`, `### Security`, each with at least one list item. No `## `
headings. Check with `python scripts/changelog_assemble.py --check`.

```markdown
### Added
- Changelog fragments under `changelog.d/` (PRP-68, PR #NNN).

### Fixed
- Planning checks fail when `PRPs/INDEX.md` is stale.
```

## Rule in this repository

The global `/prp:prp-close` step "add a line under `[Unreleased]`" is replaced here by a
fragment. Never edit `CHANGELOG.md` in a PRP branch.
