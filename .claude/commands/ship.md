---
description: Lint, test, commit, and push the current work
---

Prepare the current work to ship:

1. Run lint / format and fix any issues (never bypass with `--no-verify`).
2. Run the test suite; ensure it is green for the touched surface.
3. Stage and commit with a clear conventional-commit message.
4. Push to the current branch.

If the work is on `main`/`master` or branch protection / review is expected,
stop and confirm before pushing.
