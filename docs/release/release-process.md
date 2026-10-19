# Release process

How an operator cuts a NeuroSphere release. Version rules are in
[versioning.md](versioning.md). Pushing a tag publishes images, so it needs operator
approval every time. Releases never deploy anything automatically: installing a release into
an environment is a separate, operator-run step.

## Cut a release

1. **Branch.** From an up-to-date `main`, create `release/vX.Y` (for example
   `release/v0.2`). Patch releases for the same minor reuse that branch.
2. **Generate the changelog section.** Use the previous tag as `--from` (for the first
   release, the root commit: `git rev-list --max-parents=0 HEAD`). Preview first:

   ```bash
   python scripts/release/changelog.py --from vX.Y.(Z-1) --to HEAD --version X.Y.Z
   ```

   Then write it into `CHANGELOG.md`:

   ```bash
   python scripts/release/changelog.py --from vX.Y.(Z-1) --to HEAD --version X.Y.Z --write
   ```

   Options: `--date YYYY-MM-DD` overrides today, `--include-maintenance` lists chore, ci,
   docs, test, build and style commits instead of only counting them.

   **Insertion rule.** The `## [Unreleased]` block runs from its heading to the next line
   that starts with `## [` (or to end of file when no release exists yet). The new section is
   inserted exactly at that boundary: directly below the Unreleased block and above any older
   release, with blank-line padding. Every existing byte of `CHANGELOG.md` is kept; the
   result is the original text with the new section spliced in. If `## [X.Y.Z]` already
   exists the script exits non-zero and changes nothing.

   Check the `### Unclassified` list and the `### Breaking changes` note. Add the contract
   versions per area and the migration ids per target to the section by hand (see
   versioning.md). The Unreleased block is curated by hand: move the entries that belong to
   this release into the new section in the same commit.
3. **Set versions and open a PR.** Set the Helm chart `version` and `appVersion` to
   `X.Y.Z`, commit the changelog and version changes, and open a PR from `release/vX.Y`
   to `main`. Wait for CI to pass.
4. **Tag.** On the release branch tip (after the PR is approved) create the tag:

   ```bash
   git tag -a vX.Y.Z -m "NeuroSphere vX.Y.Z"
   ```

   **Pushing the tag requires operator approval.** Do not push it without that approval.
   The push is what starts publishing.
5. **Workflow.** Pushing `vX.Y.Z` triggers `release.yml`, which builds the api, workers and
   frontend images, pushes them to GHCR, attaches the SBOM, signs the images with cosign
   (keyless, GitHub OIDC), packages the Helm chart and creates a **draft** GitHub Release
   whose notes come from `scripts/release/changelog.py`. Review the draft and publish it
   yourself.
6. **Verify.** Verify the image signatures and SBOM attestations as described in
   [verify.md](verify.md) before announcing or installing the release.

## Pre-release tags

Tag `vX.Y.Z-rc.N` on the release branch to produce a release candidate. It follows the same
workflow and is published as a pre-release. Generate its notes with
`--version X.Y.Z-rc.N`. When the candidate is good, tag `vX.Y.Z` on the same branch; do not
move or reuse an rc tag.

## Dry run

To exercise the workflow without publishing:

```bash
gh workflow run release.yml -f dry_run=true
```

`dry_run` defaults to true on manual dispatch. A dry run builds and checks but does not push
images or create a Release. A real publish from manual dispatch requires setting
`dry_run=false`, which also needs operator approval.

## Scope

A release is a versioned, signed set of artifacts. It makes no statement about authorization
or compliance of any environment where it is installed, and nothing in this process deploys
to production.
