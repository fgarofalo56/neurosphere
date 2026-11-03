# Docs assistant image. Built from the repo root like every other service image (CI runs
# `docker build -f <Dockerfile> .`), but only paths under services/docs-assistant/ are copied:
#   docker build -f services/docs-assistant/Dockerfile -t ns-docs-assistant:dev .
# Optionally bake in the built site (BuildKit named context):
#   docker build -f services/docs-assistant/Dockerfile --build-context site=temp/site -t ns-docs-assistant:dev .
# Without --build-context the `site` stage is empty; mount the site at /srv/site instead.
# No secrets and no product configuration are baked in. Runs as uid 10001.

FROM scratch AS site

# python:3.12-alpine (Python 3.12.16), digest observed 2026-11-02
FROM python:3.12-alpine@sha256:e6dae589c1c05976188fd3bd019afd091445fc533ed2ea29001beddc7368a9c8

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DOCS_ASSISTANT_SITE_DIR=/srv/site

RUN apk upgrade --no-cache && adduser -S -H -D -u 10001 -s /sbin/nologin ns

WORKDIR /app
COPY services/docs-assistant/pyproject.toml services/docs-assistant/README.md ./
COPY services/docs-assistant/docs_assistant ./docs_assistant
RUN pip install --no-cache-dir .

COPY --from=site / /srv/site/

USER 10001
EXPOSE 8000
CMD ["uvicorn", "--factory", "docs_assistant.app:create", "--host", "0.0.0.0", "--port", "8000"]
