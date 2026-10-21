# Production image for the frontend SPA. Build context is the REPO ROOT (pnpm workspace):
#   docker build -f frontend/Dockerfile -t ns-frontend:dev .
# Runtime config is read from /config.json; mount a deploy-time file over
# /usr/share/nginx/html/config.json. Serves on 8080 as uid 10001.

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

# nginxinc/nginx-unprivileged:stable-alpine, digest observed 2026-10-18
FROM nginxinc/nginx-unprivileged:stable-alpine@sha256:782bb89768cc87b7f95c18b95baa1af250e5d451f26794f59363540161147c01

# Pull in fixed Alpine package versions that postdate the pinned base image, then drop curl:
# nginx never uses it and it carried an unfixed High CVE (CVE-2026-92392, 2026-10-21).
USER root
RUN apk upgrade --no-cache && apk del --no-cache curl

COPY frontend/nginx.conf /etc/nginx/nginx.conf
COPY --from=builder /app/frontend/dist /usr/share/nginx/html

USER 10001

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
