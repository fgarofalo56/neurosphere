#!/usr/bin/env bash
# Point git at the version-controlled hooks. Run once per clone.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
chmod +x .githooks/pre-commit .githooks/pre-push
git config core.hooksPath .githooks
echo "core.hooksPath=$(git config core.hooksPath)"
echo "Installed: .githooks/pre-commit, .githooks/pre-push"
