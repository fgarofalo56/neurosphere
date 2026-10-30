# Docs assistant image. Build context is THIS DIRECTORY only (never the repo root):
#   docker build -t ns-docs-assistant:dev services/docs-assistant
# Optionally bake in the built site (BuildKit named context):
#   docker build --build-context site=temp/site -t ns-docs-assistant:dev services/docs-assistant
# Without --build-context the `site` stage is empty; mount the site at /srv/site instead.
# No secrets and no product configuration are baked in. Runs as uid 10001.

FROM scratch AS site

# python:3.12-alpine, digest observed 2026-10-18
FROM python:3.12-alpine@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DOCS_ASSISTANT_SITE_DIR=/srv/site

RUN apk upgrade --no-cache && adduser -S -H -D -u 10001 -s /sbin/nologin ns

WORKDIR /app
COPY pyproject.toml README.md ./
COPY docs_assistant ./docs_assistant
RUN pip install --no-cache-dir .

COPY --from=site / /srv/site/

USER 10001
EXPOSE 8000
CMD ["uvicorn", "--factory", "docs_assistant.app:create", "--host", "0.0.0.0", "--port", "8000"]
