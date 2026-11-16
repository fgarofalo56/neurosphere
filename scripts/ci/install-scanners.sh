#!/usr/bin/env bash
# Install syft, trivy and grype as release binaries pinned by version AND sha256.
#
# The versions and checksums live in the calling workflow's env (SYFT_VERSION,
# SYFT_SHA256, TRIVY_*, GRYPE_*) so Dependabot-style bumps stay in one reviewable place.
# The vendor scan actions are deliberately not used (Trivy action compromise, March 2026,
# GHSA-69fq-xp46-6x23). Used by .github/workflows/security.yml; later image jobs may reuse it.
#
# Usage: scripts/ci/install-scanners.sh
# Requires: RUNNER_TEMP, GITHUB_PATH, and the six *_VERSION / *_SHA256 variables.
set -euo pipefail

: "${RUNNER_TEMP:?RUNNER_TEMP is required}"
: "${GITHUB_PATH:?GITHUB_PATH is required}"
for var in SYFT_VERSION SYFT_SHA256 TRIVY_VERSION TRIVY_SHA256 GRYPE_VERSION GRYPE_SHA256; do
  if [ -z "${!var:-}" ]; then
    echo "::error::${var} is not set" >&2
    exit 1
  fi
done

dl="${RUNNER_TEMP}/scanners"
mkdir -p "${dl}/bin"

fetch() {
  # fetch <name> <url> <sha256> <archive member>
  local name="$1" url="$2" sha="$3" member="$4"
  curl -sSfL -o "${dl}/${name}.tgz" "${url}"
  echo "${sha}  ${dl}/${name}.tgz" | sha256sum -c -
  tar -xzf "${dl}/${name}.tgz" -C "${dl}/bin" "${member}"
}

fetch syft \
  "https://github.com/anchore/syft/releases/download/v${SYFT_VERSION}/syft_${SYFT_VERSION}_linux_amd64.tar.gz" \
  "${SYFT_SHA256}" syft
fetch trivy \
  "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" \
  "${TRIVY_SHA256}" trivy
fetch grype \
  "https://github.com/anchore/grype/releases/download/v${GRYPE_VERSION}/grype_${GRYPE_VERSION}_linux_amd64.tar.gz" \
  "${GRYPE_SHA256}" grype

echo "${dl}/bin" >> "${GITHUB_PATH}"
