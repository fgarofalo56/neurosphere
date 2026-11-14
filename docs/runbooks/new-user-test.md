# New-user test record (template)

> **Status: OPEN.** No independent test has been performed. The author of a runbook walking their own steps does not count (PRP-25 clarification 12). Do not fill this in unless someone who did not write the runbooks completed the install from the published docs alone.

Runbook under test: [install.md](install.md)

## Record

- Tester: OPEN
- Date: OPEN
- Machine (OS, clean install?): OPEN
- Result: OPEN
- Deviations (every undocumented step, wrong command or surprise): OPEN
- Fixes made to the runbook as a result: OPEN

## Automated clean-room run (2026-11-14)

This is an automated run. It does not satisfy the human new-user test, which stays OPEN above.

Tester (automated): automated agent (Claude Sonnet, fresh context), not a human; does not satisfy the human new-user test.

Date: 2026-11-14. Machine: Windows 11 + Git Bash, Docker Desktop. The neurosphere emulators were already running from another checkout, so this was not a clean machine for Docker and the emulator cold start was not exercised.

Tested: a fresh single-branch clone of the integration branch `prp-25-round2` (merge commit 49e260a), read from the built site pages `runbooks/install` and `dev/local-setup` only. Host tools: Docker 29.9, uv 0.13.1, Node 26.13, pnpm 11.17, Python 3.13, GNU Make 4.4.1.

| Step | Command | Result | Note |
| --- | --- | --- | --- |
| 1 Prerequisites | `docker --version`, `node --version`, ... | deviation | Page lists versions but no way to check them; host had Node 26 and Python 3.13 instead of 24 and 3.12 |
| Get the code | none on the page | deviation | The page never says how to obtain the repository |
| 2 One-time setup | `uv sync && pnpm install && bash scripts/install-git-hooks.sh` | ok | pnpm printed `Unsupported engine` warnings (Node 26); install took about 90 s |
| 3 Demo | `pnpm demo` | ok | App answered 200 on 5180 with the Vite page; mock API on 5181 answers 404 at `/` (no page). Stopped afterwards; ports 5180 and 5181 free |
| 4 Emulators | `make dev-up` | skipped | `docker compose up --dry-run` showed it would recreate the running Event Hubs emulator (compose definition changed), which would break other work on this machine |
| 4 Emulators | `make dev-ps` | ok | All four containers healthy |
| 4 Seed | `make seed` | skipped | Would write into the shared running emulators |
| 5 Full platform | `make stack-up` | skipped | Needs a real Entra app registration; only the refusal without `NS_ENTRA_TENANT_ID` was checked (ok, clear message) |
| 6 Verify | `python scripts/validate_planning.py` | ok | PASS |
| 6 Verify | `make lint` | ok | ruff and eslint clean |
| 6 Verify | `make test` | deviation | Stopped by the 10 minute timebox at about 54%, no failures seen up to then |
| 7 Stop | `make stack-down`, `make dev-down` | skipped | Would stop or drop the shared emulators |

Deviations:

1. Prerequisite versions could not be checked and Node 24 matters. The page named versions only. Changed: added version-check commands and a note that Node must be 24.x and that newer Node prints engine warnings.
2. No clone step. The page assumed the repository was already on disk. Changed: install section 2 and local-setup now give `git clone https://github.com/fgarofalo56/neurosphere.git` and `cd neurosphere`.
3. `make dev-up` would recreate an already running emulator whose compose definition changed. Changed: a note in section 4. Not fixed in code (an environment effect of sharing the fixed compose project name).
4. `pnpm demo` gave no hint that the mock API port has no page and that startup takes a short while. Changed: added a sentence and the port override variables.
5. `make test` takes more than 10 minutes and the page did not warn. Changed: added a note and a quick-check alternative.
6. `make dev-down` drops volumes, but the stop section did not say so. Changed: added a note that `make stack-down` already stops the emulators.
7. Port 8080 was held by another process on this machine. Environmental, not run (the real stack was skipped); the page already documents `NS_FRONTEND_PORT`.

Not exercised: emulator cold start, seeding, the real stack with Entra sign-in, hosted Azure deployment, the second half of `make test`.

Overall result: COMPLETED WITH DEVIATIONS

## How to complete

When the test is done, replace each `OPEN` above with the real value, set `Result: PASSED` or `Result: FAILED`, and change the banner of this file. The runbook DRAFT banners may then be removed (the docs test only accepts that once Tester, Date and Result are filled and Result is `PASSED`).
