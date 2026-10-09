# Security policy

## Reporting a vulnerability

Email the maintainer listed in `.github/CODEOWNERS` (GitHub profile contact) or
open a **private** GitHub security advisory on this repository. Do not open a
public issue for a suspected vulnerability. Expect an acknowledgement within
five working days.

NeuroSphere is pre-release. There is no deployed instance to report against yet;
reports about the design in `docs/SECURITY.md` and `docs/ARCHITECTURE.md` are
welcome.

## What this repository guards against

The design baseline (`docs/SECURITY.md`) is the product's security model. This
file covers the repository itself.

### Secrets and PII never reach the remote

Three layers, each independent, because any one of them can be bypassed:

| Layer | Where | Catches |
|---|---|---|
| Local pre-commit | `.githooks/pre-commit` | credential-shaped filenames, key/token/JWT/connection-string patterns, SSN and card numbers in the staged diff |
| Local pre-push | `.githooks/pre-push` | the same patterns across the **whole range** being pushed, not just the tip |
| CI | `.github/workflows/secret-scan.yml` | gitleaks over **full history** (digest-pinned binary), tracked credential-shaped paths, PII scan; weekly re-scan |

Install the local layers once per clone: `bash scripts/install-git-hooks.sh`.

If a real secret is ever committed: **rotate it first**, then clean history.
Removing it in a later commit does not make it safe; a push is publication even
on a private repository.

### Code and dependency scanning

- CodeQL (`.github/workflows/codeql.yml`) on Python and TypeScript, weekly and per PR.
- `pip-audit --strict` and `pnpm audit --audit-level high` in CI.
- Dependabot with a cooldown so freshly published versions are not auto-adopted.

### Agent guardrails

`.claude/settings.json` denies reading `.env*`, `secrets/`, key files, and
denies force-push, hard reset, and Azure deployment commands. `CLAUDE.md`
requires operator approval for pushes, paid calls and cloud changes.

## Known limitations

- Local hooks only run on machines that installed them.
- gitleaks and the regex guards detect shapes, not intent. A credential that
  looks like prose will pass; treat the scanners as a backstop, not a licence.
- No SBOM or container signing exists until PRP-13 lands.
