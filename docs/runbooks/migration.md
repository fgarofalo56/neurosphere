# Migration runbook

> **Status: DRAFT.** Not yet validated by an independent new-user test. See [new-user-test.md](new-user-test.md).

This covers upgrading between releases when persisted shapes change. Policy is in [versioning.md](../release/versioning.md); this page is the operator view and does not restate it.

## What exists today

- A migrations library with an ordered ledger, dry run, forward and rollback, and a lease so only one runner applies steps: `packages/core/neurosphere_core/migrations/`.
- There is no standalone migration CLI in the repository. Migrations are exercised through the library and its tests. If your release needs a command-line runner, that is OPEN: do not invent one.
- Forward then rollback, idempotent second run and concurrent runners are verified on the emulator only. Migrations against a live account are OPEN (gate G12). Evidence: [migrations-emulator.md](../evidence/PRP-13/migrations-emulator.md).

## Procedure

1. Read the release notes for the target release: they list the contract versions per area and the migration ids per target the release expects (see [release-process.md](../release/release-process.md)).
2. Take a backup first. Procedure and caveats: [dr-runbook.md](../ops/dr-runbook.md).
3. Check the migration library against the emulator before touching a real environment:

```bash
make dev-up
uv run pytest packages/core/tests/migrations -q
uv run pytest tests/integration/migrations -m integration -q
```

4. Apply the steps between your ledger and the target ledger with the migrations library under operator control, dry run first, before switching traffic.
5. Removing anything persisted takes two releases (expand, then contract). Never skip a release when a deprecation is involved.
6. Roll back by running the step rollbacks, then restore from the backup if verification fails.

## Verify

```bash
curl -fsS http://127.0.0.1:8080/readyz
```
