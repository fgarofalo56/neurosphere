# PRP-12 item 2 - supply-chain scan evidence (local run, 2026-10-18)

Nothing here is committed except this transcript. The scanned image and binaries live in `temp/`.

## Pinned tools (same versions as `.github/workflows/security.yml`)

| Tool | Version | Licence | linux_amd64 sha256 (used in CI) |
|------|---------|---------|----------------------------------|
| syft | 1.54.1 | Apache-2.0 | c069905b391cc4c20a5ba65ad5c10be2a7ba074f8ea6ad203e24d14e303dad47 |
| trivy | 0.76.0 | Apache-2.0 | e24b1c51293c1b15e4ba8d45bbc7891ba053f90278ec2698f3562c993e145fe7 |
| grype | 0.120.1 | Apache-2.0 | 0a9ee97ef5ae2ee953b0a80098105052e846cdbe319a57d808b519c33cd1343d |

Locally the Windows builds of the same versions were used. Their zip checksums were compared with the
release `checksums.txt` files and matched:
syft 8b56e828...e19f, trivy 7b4762a5...7be6, grype 32e3c811...d65d.

Trivy advisory check (`gh api repos/aquasecurity/trivy/security-advisories`): GHSA-69fq-xp46-6x23 covers
the March 2026 compromise (binary v0.69.4; DockerHub images v0.69.5 and v0.69.6; trivy-action and
setup-trivy tags). v0.76.0 is outside it, is above the patched versions of GHSA-mcj4-mphf-j9ff (0.71.1)
and GHSA-8rc5-4fr6-64pw (0.72.0), and no vendor scan action is used.

## High-CVE proof: `debian:buster` (EOL base image, pulled, not committed)

Image saved with `docker save debian:buster -o temp/buster.tar`; scanners read the archive.

```
$ syft docker-archive:buster.tar -o cyclonedx-json=sbom-buster.cdx.json
syft exit=0          # CycloneDX 1.7 SBOM, 435 components

$ trivy image --input buster.tar --scanners vuln --severity HIGH,CRITICAL --exit-code 1
Detected OS family="debian" version="10.13"
Total: 28 (HIGH: 26, CRITICAL: 2)
trivy exit=1

$ grype docker-archive:buster.tar --fail-on high
libsystemd0  241-7~deb10u10  (won't fix)  deb  CVE-2023-50387  High
gzip         1.9             1.12          binary CVE-2022-1271  High
... (151 lines)
ERROR discovered vulnerabilities at or above the severity threshold
grype exit=2
```

Both scanners exit non-zero with exactly the flags the workflow uses, so the image job fails on a High/Critical.

## Dependency scan of the current tree (clean `git archive HEAD` export)

```
$ syft dir:. -o cyclonedx-json=sbom-source.cdx.json     -> exit 0, 572 components
$ trivy fs --scanners vuln --severity HIGH,CRITICAL --exit-code 1 .
  uv.lock 0, pnpm-lock.yaml 0 (plus test fixture lockfiles 0)   -> exit 0
$ grype dir:. --fail-on high                              -> "No vulnerabilities found", exit 0
$ pnpm audit --audit-level high                           -> "No known vulnerabilities found", exit 0
```

Result: no High or Critical findings in current dependencies; nothing was suppressed or ignored.

## Not run locally

The `docker build` and upload-artifact steps and the no-image notice path execute only in GitHub Actions
(no `services/*/Dockerfile` exists until PRP-13). `actionlint .github/workflows/security.yml` exits 0.
