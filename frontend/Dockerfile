# Production image for the frontend SPA. Build context is the REPO ROOT (pnpm workspace):
#   docker build -f frontend/Dockerfile -t ns-frontend:dev .
# Same-origin edge: nginx serves the SPA and proxies /api/, /readyz and /healthz to
# NS_UI_API_UPSTREAM (e.g. http://api:8000). /config.json is rendered at start from
# NS_UI_CLOUD / NS_UI_TENANT_ID / NS_UI_CLIENT_ID / NS_UI_API_SCOPE (apiBaseUrl is always "/");
# no IDs are baked in. A deploy-time file mounted at /usr/share/nginx/html/config.json wins and
# then only NS_UI_API_UPSTREAM is required. Serves on 8080 as uid 10001.

# node:24-alpine, digest observed 2026-10-18
FROM node:24-alpine@sha256:44fce696f38ba8c987c4db89954051000bbd05ffd8d8659ba15ed4a8602e937f AS builder

# pnpm version comes from the root package.json packageManager field.
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY frontend ./frontend
COPY packages/contracts/ts ./packages/contracts/ts
COPY connectors/sdk-ts ./connectors/sdk-ts
RUN pnpm install --frozen-lockfile --filter "@neurosphere/frontend..."
RUN pnpm --filter @neurosphere/frontend build

# nginxinc/nginx-unprivileged:mainline-alpine (nginx 1.31.7), digest observed 2026-11-25. Mainline,
# not stable: stable-alpine still ships nginx 1.30.6 with six High advisories fixed in 1.30.7, and
# no patched stable tag of the unprivileged image is published. Return to stable-alpine once it
# carries nginx >= 1.30.7 if a stable branch is preferred.
FROM nginxinc/nginx-unprivileged:mainline-alpine@sha256:b5047b9b76845eac124358373c6852377c52e4b05834a47647e955dd91cb8f1e

# Pull in fixed Alpine package versions that postdate the pinned base image, then drop curl:
# nginx never uses it and it carried an unfixed High CVE (CVE-2026-92392, 2026-10-21).
USER root
RUN apk upgrade --no-cache && apk del --no-cache curl

COPY frontend/nginx.conf /etc/nginx/nginx.conf
COPY frontend/nginx/templates/default.conf.template /etc/nginx/templates/default.conf.template
COPY --chmod=0755 frontend/docker/render-config.sh /docker-entrypoint.d/18-ns-render-config.sh
COPY --from=builder /app/frontend/dist /usr/share/nginx/html
# The dev placeholder config.json must not ship: its absence is how a mounted file is detected.
RUN rm -f /usr/share/nginx/html/config.json

# Render the template into /tmp (read-only root fs) and substitute only NS_UI_* variables.
ENV NGINX_ENVSUBST_OUTPUT_DIR=/tmp/ns-conf.d \
    NGINX_ENVSUBST_FILTER=^NS_UI_

USER 10001

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
