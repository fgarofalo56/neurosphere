# Production image for the workers. Build context is the REPO ROOT (uv workspace):
#   docker build -f services/workers/Dockerfile -t ns-workers:dev .
# No secrets are baked in; configuration arrives via environment at runtime.
# Runs as uid 10001 and starts under readOnlyRootFilesystem with /tmp as a tmpfs.

# python:3.12-alpine (Python 3.12.16), digest observed 2026-11-02
FROM python:3.12-alpine@sha256:e6dae589c1c05976188fd3bd019afd091445fc533ed2ea29001beddc7368a9c8 AS builder

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
COPY connectors/reference/azure-monitor ./connectors/reference/azure-monitor
COPY connectors/reference/apim-gateway ./connectors/reference/apim-gateway
COPY connectors/reference/foundry-actions ./connectors/reference/foundry-actions
RUN uv sync --frozen --no-dev --no-editable --package neurosphere-workers

# python:3.12-alpine (Python 3.12.16), digest observed 2026-11-02
FROM python:3.12-alpine@sha256:e6dae589c1c05976188fd3bd019afd091445fc533ed2ea29001beddc7368a9c8

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NS_ENV=prod \
    PATH="/app/.venv/bin:$PATH"

RUN apk upgrade --no-cache && adduser -S -H -D -u 10001 -s /sbin/nologin ns
COPY --from=builder /app/.venv /app/.venv
# SYNTHETIC benchmark registry (datasets, rubrics, judge configs, judge fixtures) for the
# `evaluation` role: NS_WORKER_EVAL_DATA_DIR=/app/evaluation-data. Sandbox data only, no real
# or production content. Nothing else from sandbox/ is copied.
COPY sandbox/evaluation/data /app/evaluation-data

WORKDIR /tmp
USER 10001

EXPOSE 8090
CMD ["python", "-m", "neurosphere_workers.runtime"]
