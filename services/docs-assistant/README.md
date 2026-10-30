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
`Retry-After`), `request_too_large` (413), `invalid_request` (422).

## Model client

Generation goes through the `ModelClient` protocol. The default is `StubModel`, a
deterministic extractive client that quotes the top passage; tests use it, and there are no
paid calls in tests or CI. `model_endpoint` and `model_api_key_env` (the NAME of an
environment variable) are reserved for an operator-configured provider; no provider client
ships yet, so setting `model_endpoint` fails at startup with a clear error.

Corpus text is untrusted input. The service has no tools, runs no code from the corpus and
makes no outbound requests. `build_prompt` fences passages and tells the model to treat
them as data.

## Configuration

All settings are environment variables prefixed `DOCS_ASSISTANT_` (see `config.py`);
unknown settings are rejected. Defaults:

| Setting | Default | Meaning |
|---|---|---|
| `site_dir` | required | Built-site directory |
| `docs_base_url` | `https://docs.example.invalid/` | Public base URL used for citations; set it to the real site |
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

The Dockerfile uses only this directory as build context, runs as uid 10001, and holds no
secrets. The site can be added at build time with `--build-context site=<dir>` or mounted
at `/srv/site`.

## Tests

```
python -m pytest services/docs-assistant/tests
```
