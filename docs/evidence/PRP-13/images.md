# PRP-13 item 1: production images evidence

Observed 2026-10-18 (container clock showed 2026-10-19 UTC), Docker 29.8.2, build context = repo root.

## Base images (pinned by digest in each Dockerfile)

| Use | Tag | Digest |
|-----|-----|--------|
| api, workers (builder and runtime) | `python:3.12-alpine` | `sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4` |
| uv (copied into builder) | `ghcr.io/astral-sh/uv:0.11` | `sha256:77280f2f771df71f90786c314fe1bbc1e023feac652969bbf139c280babf2eb7` |
| frontend builder | `node:24-alpine` | `sha256:44fce696f38ba8c987c4db89954051000bbd05ffd8d8659ba15ed4a8602e937f` |
| frontend runtime | `nginxinc/nginx-unprivileged:stable-alpine` | `sha256:782bb89768cc87b7f95c18b95baa1af250e5d451f26794f59363540161147c01` |

Why alpine: the first attempt used `python:3.12-slim` (digest `sha256:a6e34c59...`). Trivy 0.76.0
failed it with 44 HIGH findings in Debian 13.7 packages (util-linux, libsystemd0, ncurses, perl-base)
for which no fix was available. Alpine with `apk upgrade --no-cache` is clean. The frontend runtime
needed `apk upgrade` too (libexpat CVE-2026-77214, libx11 CVE-2026-88806 had fixes in the repo).
The `apk upgrade` layers mean a rebuild can pick newer Alpine packages than the pinned digest alone.

## Builds

```text
docker build -f services/api/Dockerfile -t ns-api:dev .        -> built (sha256:97a90623...)
docker build -f services/workers/Dockerfile -t ns-workers:dev . -> built (sha256:fb3e7c2e...)
docker build -f frontend/Dockerfile -t ns-frontend:dev .        -> built (sha256:2420987c...)
```

Frontend build needs the root `tsconfig.base.json` in the context (the first attempt omitted it and
Vite silently transformed only 3 modules).

## User

`docker run --rm --entrypoint id <img> -u` printed `10001` for ns-api:dev, ns-workers:dev and
ns-frontend:dev. `docker inspect -f '{{.Config.User}}'` printed `10001` for all three.

## Read-only start (`--read-only --tmpfs /tmp`)

- api (`NS_CLOUD=commercial`, `NS_ENV=prod` from the image): `Application startup complete.`, `GET /healthz` returned 200.
- workers (`NS_CLOUD=commercial`): `neurosphere.workers.runtime worker started`, container stayed Up.
- frontend (also `--tmpfs /var/cache/nginx --tmpfs /var/run`, matching the Helm mounts): `/` 200 (index.html),
  `/config.json` 200 with `Cache-Control: no-store`, `/x/y` 200 (SPA fallback).

## Contents

`docker export | tar -t` filtered for `.env*`, `.git*`, `tests/`, `docs/`: only `app/.venv/.gitignore`
(a uv-generated file inside the venv) in the Python images; nothing in the frontend image. Third-party
`site-packages` test directories were excluded from the filter.

## Scans (trivy 0.76.0, grype v0.120.1, run through Docker)

| Image | `trivy image --scanners vuln --severity HIGH,CRITICAL --exit-code 1` | `grype <img> --fail-on high` |
|-------|------|------|
| ns-api:dev | exit 0, 0 findings (alpine 3.24.2) | exit 0, 0 High/Critical; 14 Medium, plus Low/Negligible |
| ns-workers:dev | exit 0, 0 findings | exit 0, 0 High/Critical; 14 Medium |
| ns-frontend:dev | exit 0, 0 findings | exit 0, 0 High/Critical; 3 Medium |

No findings were suppressed, no ignore files were added, and `security.yml` was not edited.
