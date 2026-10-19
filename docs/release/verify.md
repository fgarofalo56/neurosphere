# Verifying a NeuroSphere release

`.github/workflows/release.yml` publishes three images (`api`, `workers`, `frontend`) and the
Helm chart to GHCR. Images are signed keylessly with cosign through GitHub OIDC (no signing key
is stored anywhere) and carry a syft CycloneDX SBOM attached as a cosign attestation. This page
gives the operator commands to check them. It makes no compliance, authorization or ATO claim:
a valid signature proves which workflow built an image, nothing more.

Placeholders: `<owner>` is the lowercase GitHub owner, `<repo>` the repository name,
`X.Y.Z` the version without the leading `v`, `<tag>` the git tag (for example `v0.1.0`).

## Status and approvals

- The first real tag push needs operator approval. Nothing here has been run against a real tag
  yet; until then the dry run is the only exercised path.
- GHCR packages stay private until the operator changes package visibility. The repository
  itself is public; a new package is private by default and inherits the linked repository's
  access permissions but not its visibility
  (https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility,
  observed 2026-10-19). Check each package's visibility after the first real tag run. Pulling
  and verifying needs `docker login ghcr.io` with a token that has `read:packages`.

## Find the digests

Each real run records `<ref>@sha256:...` per image (job `images`, step "Push image and record
digest") and the `sign` job logs it again. To look one up afterwards:

```bash
docker login ghcr.io -u <github-user>   # token via stdin: echo "$TOKEN" | docker login ghcr.io -u <user> --password-stdin
docker buildx imagetools inspect ghcr.io/<owner>/neurosphere/api:X.Y.Z    # shows "Digest: sha256:..."
```

Or read it from the package page in GitHub. Always verify the digest, never the mutable tag.

## Verify image signatures

The signing identity is the release workflow at the tag ref, issued by the GitHub Actions OIDC
provider:

```bash
IDENTITY="https://github.com/<owner>/<repo>/.github/workflows/release.yml@refs/tags/<tag>"
ISSUER="https://token.actions.githubusercontent.com"

for svc in api workers frontend; do
  cosign verify \
    --certificate-identity "$IDENTITY" \
    --certificate-oidc-issuer "$ISSUER" \
    ghcr.io/<owner>/neurosphere/$svc@sha256:<digest>
done
```

## Verify and read the SBOM attestation

```bash
cosign verify-attestation --type cyclonedx \
  --certificate-identity "$IDENTITY" \
  --certificate-oidc-issuer "$ISSUER" \
  ghcr.io/<owner>/neurosphere/api@sha256:<digest>
```

The verified output is a DSSE envelope; the CycloneDX document is base64 in `.payload` (an
in-toto statement whose `predicate` is the SBOM).

## Pull the Helm chart

```bash
echo "$TOKEN" | helm registry login ghcr.io -u <github-user> --password-stdin
helm pull oci://ghcr.io/<owner>/charts/neurosphere --version X.Y.Z
```

The chart `version` and `appVersion` both equal the product version. `infra/helm/values.yaml`
uses `repository: neurosphere/<svc>` under registry `ghcr.io/<owner>`, matching the image
paths above. For production, pin `image.digest` values rather than tags.

## Run the dry run

A dry run builds the images, makes the SBOMs, lints and packages the chart and drafts release
notes. It pushes nothing, signs nothing and creates no GitHub Release. Pull requests that touch
the release inputs run it automatically. After the workflow is on `main`:

```bash
gh workflow run release.yml -f dry_run=true
```

Dry runs are versioned `0.0.0-dryrun.<run number>`. A manual run with `dry_run=false` fails
unless the ref is a `v*.*.*` tag, so an untagged publish is impossible.

## Tag runs

Pushing `vX.Y.Z` (or `vX.Y.Z-rc.N`, published as a pre-release) publishes, signs, verifies in
the workflow itself (a verify failure fails the run), pushes the chart and creates a **draft**
GitHub Release with notes from `scripts/release/changelog.py`. A human publishes the draft.

## Cosign details observed (cosign v3.1.3)

Flags confirmed with `docker run --rm ghcr.io/sigstore/cosign/cosign:v3.1.3 <cmd> --help` on
2026-10-19: `sign --yes`; `attest --yes --type <predicate type> --predicate <file>` where
`cyclonedx` is an accepted type; `verify` and `verify-attestation` take
`--certificate-identity` and `--certificate-oidc-issuer`, and `verify-attestation` takes
`--type`. `sign` also exposes `--registry-referrers-mode` (`legacy` or `oci-1-1`) and
`--use-signing-config` (default true, the v3 bundle format). The workflow uses the defaults.
Whether GHCR serves the OCI 1.1 referrers API directly or cosign falls back to its tag-based
referrers scheme was not observed (no registry push is possible before the first approved tag);
the verify steps in the `sign` job prove the round trip on the first real run.

Docs relied on (observed 2026-10-19):

- https://docs.sigstore.dev/cosign/signing/overview/
- https://docs.github.com/packages/working-with-a-github-packages-registry/working-with-the-container-registry
