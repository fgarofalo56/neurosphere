# Runbook: credential reached a commit or remote

**Rotate/revoke the credential first, then clean history.**

Removing a secret in a later commit does not make it safe. A push is
publication: treat anything that reached a remote as compromised even if you
force-push it away, and even on a private repository (`SECURITY.md`,
`.githooks/pre-push`). Part of the broader [incident-response-plan.md](incident-response-plan.md).

## 1. Triage (minutes)

- Stop: do not push further, do not delete and re-push to "hide" it.
- Decide: is it **real** or a **synthetic fixture** (scrubber test data)? When
  unsure, treat as real.
- Identify the type, owner and where it grants access, without copying the
  value anywhere (no chat, ticket or new file).

## 2. Real secret: rotate or revoke first

1. Revoke or rotate at the provider (see [secret-rotation.md](secret-rotation.md)).
   Disable the exposed credential immediately; do not wait for the overlap
   window if exposure is confirmed.
2. Replace consumers with the new Key Vault version.
3. Verify by behaviour: the old credential must fail, the new must succeed.

Only after this step is the exposure contained.

## 3. Scope assessment

- Was it only local (never pushed)? Do not search for the value with
  `git log -S <value>`: that writes the secret into shell history. Use
  `gitleaks git . --config .gitleaks.toml --redact` to locate commit, file and
  rule without printing it.
- Pushed? Which branches, forks, PRs, CI logs and artifacts? Cached clones are
  presumed to hold it.
- What can the credential reach (data, tenant, cloud: Commercial versus
  Government)? Note any cross-cloud implication.

## 4. Audit-log review

For the exposure window (first commit time to revocation):

- Provider and Azure activity logs / sign-in logs for the identity or key.
- Azure Monitor and Key Vault diagnostic logs for access to the secret.
- The NeuroSphere audit store (PRP-06): append-only records of actions by the
  principal. Do not edit or delete audit records; export copies for evidence.

Any unexplained use escalates to a higher severity in the incident plan.

## 5. History cleanup (after rotation)

- **Real secret:** it is already compromised and rotated, so a rewrite is
  hygiene, not containment. Coordinate with the operator before any rewrite:
  rewriting disturbs open PRs, forks and signatures, and force-push is not
  allowed without explicit operator approval. Options: leave in place and
  document; or operator-run history rewrite (for example `git filter-repo`) on
  a fresh mirror clone, followed by re-cloning for all contributors and a
  provider-side cache purge request where available.
- **Synthetic fixture** (verified non-secret): do not rewrite history. Add a
  fingerprint-exact entry to `.gitleaksignore` in the form
  `<commit>:<path>:<rule>:<line>`. No path or rule wildcards, and the allowlist
  in `.gitleaks.toml` stays narrow.
- Prefer `<placeholder>` style fixtures that the hooks' placeholder filter
  already ignores.

## 6. Verify

```
gitleaks git . --config .gitleaks.toml --redact --no-banner
```

Expect no leaks (or only fingerprint-allowlisted synthetic ones). CI re-runs the
same full-history scan (`.github/workflows/secret-scan.yml`, job `gitleaks`).

## 7. Follow up

- Add or tighten the detection that should have caught it (hook pattern, rule),
  through the owner of `.githooks/` or `.gitleaks.toml`.
- Record a lessons-learned note in the incident record (no secret values).
