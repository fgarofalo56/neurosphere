# Runbook: public docs assistant (build, run, configure a model)

> **Status: DRAFT.** Not yet validated by an independent new-user test. See [new-user-test.md](new-user-test.md).

The docs assistant is a separate, read-only, rate-limited service that answers questions from the
published documentation site only. It shares nothing with the product: no product API URL, no
database, no production credentials. Every answer cites published docs URLs, and when the site does
not support an answer it abstains (`abstained: true`, no citations) instead of guessing. It has no
write path and runs no code from the corpus. Hosting it publicly is an operator action; this
repository builds and publishes the image but does not deploy it. Service details:
[README](https://github.com/fgarofalo56/neurosphere/blob/main/services/docs-assistant/README.md).

## Build the site

The assistant indexes the built site (HTML), never the repository tree. Build it with the command
from [ADR-0008](../adr/0008-docs-site-tool.md):

```bash
NO_MKDOCS_2_WARNING=1 uv run --no-project --with mkdocs-material==9.8.0 mkdocs build --strict --site-dir temp/site
```

## Run with Compose

The `docs` profile adds one service, `docs-assistant`, on `http://127.0.0.1:8091`. It has no
dependency on the emulators, so nothing else needs to be running.

```bash
docker compose --profile docs up -d --build --wait docs-assistant
curl -s http://127.0.0.1:8091/healthz
curl -s -X POST http://127.0.0.1:8091/ask -H 'content-type: application/json' -d '{"question":"Which tool builds the docs site?"}'
docker compose --profile docs down docs-assistant
```

`/healthz` returns `{"status":"ok","chunks":N}`. `/ask` returns `answer`, `abstained` and
`citations`. A question the site cannot support, for example one about baking bread, returns
`abstained: true` with no citations.

If `temp/site` was not built first, Compose creates an empty `temp/site` directory on the host
and mounts it. The service then starts with an index of zero chunks and abstains from every
question, so check that `/healthz` reports a non-zero `chunks` count after you build the site.
Rebuild the site, then restart the service so it re-reads the directory.

The service is hardened: read-only root filesystem, a `/tmp` tmpfs, all capabilities dropped,
`no-new-privileges`, port bound to loopback only.

## Configure a model

With no model settings the service uses a deterministic stub that quotes the top passage. To use an
Azure OpenAI deployment, export these in the host shell before `up`. Compose passes them through
only when they are set.

| Variable | Meaning |
|---|---|
| `DOCS_ASSISTANT_MODEL_ENDPOINT` | HTTPS endpoint, for example `https://<resource>.openai.azure.com` |
| `DOCS_ASSISTANT_MODEL_DEPLOYMENT` | Deployment name, sent as `model` |
| `DOCS_ASSISTANT_MODEL_AUTH` | `entra` (default) or `key` |
| `DOCS_ASSISTANT_MODEL_API_KEY_ENV` | NAME of the variable holding the key (key auth only) |
| `DOCS_ASSISTANT_MODEL_KEY` | The one key pass-through the compose service forwards |
| `DOCS_ASSISTANT_CLOUD` | `commercial` (default) or `government` |
| `DOCS_ASSISTANT_DOCS_BASE_URL` | Public base URL used for citations |

Entra auth, the default, is the right choice in a host. Give the host's managed identity the
`Cognitive Services User` role on the Azure OpenAI resource. The endpoint must be HTTPS and its
host must end with an allowed suffix for the cloud (Commercial: `.openai.azure.com`,
`.services.ai.azure.com`, `.cognitiveservices.azure.com`; Government: `.openai.azure.us`,
`.cognitiveservices.azure.us`). Anything else fails at startup. The service calls the v1 API
(`/openai/v1/chat/completions`), so no `api-version` setting is needed.

Under Compose on a workstation there is no managed identity, so Entra auth cannot get a token
and requests answer 503. Either leave the model unset and use the stub, or use key auth if the
resource allows local auth. Export the key under the single pass-through name, never in a file:

```bash
export DOCS_ASSISTANT_MODEL_AUTH=key
export DOCS_ASSISTANT_MODEL_API_KEY_ENV=DOCS_ASSISTANT_MODEL_KEY
```

Then export `DOCS_ASSISTANT_MODEL_KEY` in the same shell by whatever means your secret handling
allows, set the endpoint and deployment, and run `up` again. The key is read at call time and is
never logged or echoed in an error.

`gpt-5` family notes: these models count reasoning tokens against `max_completion_tokens`, so the
service sends `reasoning_effort: minimal` and a 1024-token budget by default. If a deployment
returns empty completions, the budget was spent on reasoning; raise `model_max_completion_tokens`
or the effort setting in the service configuration. No `temperature` is sent.

## Troubleshooting: 503 `model_unavailable`

The service never falls back to the stub silently. Any non-2xx status, timeout, credential
failure, malformed response or empty completion returns `503` with code `model_unavailable`. The
error text never includes the key, a token or the provider body, so check the container logs and
the provider side. Common causes:

- No credential: Entra auth with no managed identity (see above), or a missing role assignment.
- Wrong deployment name or endpoint.
- 429 from a deployment with too little capacity. A GlobalStandard capacity of 1 (1K tokens per
  minute) was observed to return 429 on the second request. Raise the deployment capacity.
- An empty completion because the reasoning budget used the whole token limit.

## Published image

A release tag builds, SBOMs, signs and pushes the image as
`ghcr.io/<owner>/neurosphere/docs-assistant:<version>` alongside the api, workers and frontend
images. See [verify.md](https://github.com/fgarofalo56/neurosphere/blob/main/docs/release/verify.md)
for verifying signatures. The image holds no secrets and no site; mount the built site at
`/srv/site` or add it at build time.

## Hosting is an operator action

This repository does not host the assistant. GitHub Pages is static, so run the image where you
control it (for example a container host with a managed identity), mount the built site, set the
model variables above, and keep to one replica or enforce rate limits at the edge as well, because
rate-limit state is in memory. If you configure an external model, the question and retrieved
passages go to that provider, and your privacy notice must say so. Availability of a hosted
instance is a separate gate and is not claimed here.
