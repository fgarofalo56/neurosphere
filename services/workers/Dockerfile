# Production image for the workers. Build context is the REPO ROOT (uv workspace):
#   docker build -f services/workers/Dockerfile -t ns-workers:dev .
# No secrets are baked in; configuration arrives via environment at runtime.
# Runs as uid 10001 and starts under readOnlyRootFilesystem with /tmp as a tmpfs.

# python:3.12-alpine, digest observed 2026-10-18
FROM python:3.12-alpine@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4 AS builder

# ghcr.io/astral-sh/uv:0.11, digest observed 2026-10-18
COPY --from=ghcr.io/astral-sh/uv:0.11@sha256:77280f2f771df71f90786c314fe1bbc1e023feac652969bbf139c280babf2eb7 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY packages ./packages
COPY services ./services
COPY connectors/sdk-python ./connectors/sdk-python
RUN uv sync --frozen --no-dev --no-editable --package neurosphere-workers

# python:3.12-alpine, digest observed 2026-10-18
FROM python:3.12-alpine@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NS_ENV=prod \
    PATH="/app/.venv/bin:$PATH"

RUN apk upgrade --no-cache && adduser -S -H -D -u 10001 -s /sbin/nologin ns
COPY --from=builder /app/.venv /app/.venv

WORKDIR /tmp
USER 10001

EXPOSE 8090
CMD ["python", "-m", "neurosphere_workers.runtime"]
