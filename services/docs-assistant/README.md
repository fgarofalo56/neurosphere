# NeuroSphere docs assistant

A separate, read-only, rate-limited service that answers questions from the published
documentation site only. It shares nothing with the product: no product API URL, no
database, no production credentials, and no import of `neurosphere_api` or
`neurosphere_core`. GitHub Pages is static, so this service is hosted separately by the
operator; hosting it is not done by this repository.

## Corpus boundary

The index is built from a built-site artifact directory (HTML files) and never from the
repository tree. Build the site, then point the service at it:

```
NO_MKDOCS_2_WARNING=1 uv run --no-project --with mkdocs-material==9.8.0 mkdocs build --strict --site-dir temp/site
python -m docs_assistant.index temp/site            # prints chunk and page counts
DOCS_ASSISTANT_SITE_DIR=temp/site uvicorn --factory docs_assistant.app:create
```

Only `*.html` files inside the site directory are indexed (symlinks are skipped). Pages are
split by heading; each chunk keeps its published docs URL, derived from its path under the
site directory and `docs_base_url`. Retrieval is local BM25 scoring, with no network and no
vector service.

## API

- `GET /healthz` returns `{"status":"ok","chunks":N}`.
- `POST /ask` with `{"question": "..."}` returns `{"answer", "abstained", "citations":[{"url","title"}]}`.

There is no write path. `/docs` and `/openapi.json` are disabled. When no retrieved chunk
passes the support thresholds (`min_score`, `min_coverage`) the response is an explicit
abstention (`abstained: true`, no citations). Every non-abstained answer cites docs URLs.

Errors use one envelope: `{"error":{"code","message"}}`. Codes: `rate_limited` (429, with
`Retry-After`), `request_too_large` (413), `invalid_request` (422), `model_unavailable` (503).

## Model client

Generation goes through the `ModelClient` protocol. With no `model_endpoint` the default is
`StubModel`, a deterministic extractive client that quotes the top passage; tests use it, and
there are no paid calls in tests or CI. Setting `model_endpoint` switches to
`AzureOpenAIModel`, which calls the Azure OpenAI v1 Chat Completions API
(`POST {endpoint}/openai/v1/chat/completions`, `model` = your deployment name).

Hosting the service and approving the model deployment are operator actions; this repository
does not deploy either. Live checks need `NS_LIVE_APPROVED=1` (see
`tests/test_live_model_smoke.py`) and are reported OPEN when they did not run.

Model settings (all `DOCS_ASSISTANT_` environment variables):

| Setting | Default | Meaning |
|---|---|---|
| `model_endpoint` | unset (stub) | HTTPS Azure OpenAI endpoint; requires `model_deployment` |
| `model_deployment` | unset | Deployment name sent as `model` |
| `cloud` | `commercial` | `commercial` or `government`; selects the host allowlist and token scope |
| `model_auth` | `entra` | `entra` (bearer token) or `key` (`api-key` header) |
| `model_api_key_env` | unset | NAME of the environment variable holding the key; required for `key` |
| `model_timeout_seconds` | 20 | Per-request timeout |
| `model_max_completion_tokens` | 1024 | Sent as `max_completion_tokens`; reasoning tokens count against it, so keep headroom |
| `model_reasoning_effort` | `minimal` | `minimal`, `low`, `medium`, `high`, or unset to omit the field |

Auth. `entra` uses `azure.identity.aio.DefaultAzureCredential` (managed identity in Azure)
with scope `https://cognitiveservices.azure.com/.default`, or the `.azure.us` scope when
`cloud=government`; grant the identity the `Cognitive Services User` role. `key` reads the key
from the named environment variable at call time. The key is never a config value and is never
logged or echoed in an error.

Endpoint allowlist. The endpoint must use HTTPS and its parsed hostname must end with a
dotted suffix allowed for the cloud. Commercial: `.openai.azure.com`, `.services.ai.azure.com`,
`.cognitiveservices.azure.com`. Government: `.openai.azure.us`, `.cognitiveservices.azure.us`.
Anything else (other hosts, lookalikes such as a host that merely contains the Azure name,
plain HTTP, embedded userinfo, a Commercial host under `cloud=government`) fails at startup.

Request and result handling. Only `model`, `messages`, `max_completion_tokens` and, when set,
`reasoning_effort` are sent: no `temperature`, no `tools` or `functions`. The system message
holds the rules; the user message holds the fenced passages and the question. If the model
replies `ABSTAIN` (or starts with it) or the provider reports `content_filter`, the response
is the normal abstention (`abstained: true`, no citations). Citations always come from the
retrieved chunks, never from model text. Any non-2xx status, timeout, transport error,
credential failure, malformed JSON or an empty completion (for example the budget was spent on
reasoning) returns `503` with code `model_unavailable`. The service never falls back to the
stub silently, and the error text never includes the key, a token or the provider body.

Corpus text is untrusted input. The service has no tools and runs no code from the corpus. Its
only outbound request is the configured model call. `build_messages` escapes angle brackets in
passages so they cannot close the fence, and tells the model to treat them as data.

## Configuration

All settings are environment variables prefixed `DOCS_ASSISTANT_` (see `config.py`);
unknown settings are rejected. Defaults:

| Setting | Default | Meaning |
|---|---|---|
| `site_dir` | required | Built-site directory |
| `docs_base_url` | `https://fgarofalo56.github.io/neurosphere/` | Public base URL used for citations |
| `rate_limit_requests` / `rate_limit_window_seconds` | 20 / 60 | Sliding window per client; a configuration default, not a performance claim |
| `trusted_proxy_hops` | 0 | 0 uses the socket peer and ignores `X-Forwarded-For`; N uses the Nth entry from the right |
| `max_body_bytes` / `max_question_chars` | 2048 / 500 | Request size limits |
| `top_k`, `min_score`, `min_coverage` | 3, 2.0, 0.5 | Retrieval and abstention thresholds |

Rate-limit state is in memory per process; run one replica or enforce a limit at the edge
as well. Behind a proxy, set `trusted_proxy_hops` to the number of trusted proxies;
otherwise every client appears as the proxy address.

## Privacy statement basis

The service does not log or retain full user prompts. For each request it logs only the
question length and a truncated SHA-256 hash, plus whether it abstained. No request body,
IP-to-question link or conversation history is stored. Rate-limit counters hold client
addresses in memory only, for the window duration. If an operator configures an external
model endpoint, the question and retrieved passages are sent to that provider; the
operator's privacy notice must say so.

## Image

The Dockerfile is built from the repo root (`docker build -f services/docs-assistant/Dockerfile .`,
the same as CI) but copies only files under `services/docs-assistant/`. It runs as uid 10001 and
holds no secrets. The site can be added at build time with `--build-context site=<dir>` or mounted
at `/srv/site`.

## Tests

```
python -m pytest services/docs-assistant/tests
```
