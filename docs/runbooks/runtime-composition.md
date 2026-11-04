# Runbook: runtime composition (ingest, seed, search, write targets)

PRP-35 wires four seams so a fresh stack holds data and can act on it. Each is opt-in by
environment; this page lists every variable, its default, and what it does. Related runbooks:
[ingest.md](ingest.md), [seeding.md](seeding.md).

## Local compose quick start

```bash
docker compose --profile app up -d --build --wait api   # emulators + api
docker compose --profile seed run --rm --build seed     # catalog (idempotent, NS_ENV=local only)
uv run pytest -q -m integration tests/integration/runtime_composition   # local smoke, not in CI
```

Export the same `NS_ENTRA_TENANT_ID` for the seed and the smoke test (the seed grants the workers'
scope under that tenant; without it the test uses a placeholder GUID and so must you for the seed).

## Environment variables

### Ingest (api)

| Variable | Default | Effect |
|---|---|---|
| `NS_INGEST_PRODUCERS_FILE` | unset | Path to the producers file (sha256 digests only). Unset: ingest routes answer `503 ingest_not_configured` and `/readyz` lists `composition.ingest.disabled`. Set but unreadable/malformed: api startup fails. Compose sets it to the read-only dev file. |
| `NS_INGEST_RATE_LIMIT_RPS`, `NS_INGEST_RATE_LIMIT_BURST` | code defaults | Per-producer rate limit. |

Dev bearer token (emulator stack only): `dev-ingest.ns-dev-only-ingest-secret`. See ingest.md.

### Seed (`seed` compose service)

| Variable | Default | Effect |
|---|---|---|
| `NS_ENV` | `local` in compose | The seeder refuses (exit 2) unless exactly `local`. |
| `NS_CLOUD` | `commercial` | Refuses any other cloud. |
| `NS_AUTH_TENANT_ID` (from `NS_ENTRA_TENANT_ID`) | empty | Tenant the worker grants are written under; must be a GUID. |
| `NS_WORKER_OBJECT_ID` | synthetic GUID in compose | Worker principal granted; must equal the workers' value. |

### Search (api)

| Variable | Default | Effect |
|---|---|---|
| `NS_SEARCH_PROVIDER` | compose: `fixture`; code: unset | unset: no search, catalog graph search answers `503 search_unavailable`. `fixture`: in-process BM25 index fed from the catalog. `azure`: Azure AI Search behind a fallback; the in-process index answers (and Azure is never called) while the capability matrix row `ai_search.base` is unsupported for the cloud and `NS_SEARCH_REGION`, or no service is configured. |
| `NS_SEARCH_SERVICE` | unset | Azure AI Search service name (host comes from the cloud profile). |
| `NS_SEARCH_INDEX` | `neurosphere-catalog` | Index name. |
| `NS_SEARCH_REGION` | unset | Region used for the capability lookup. |
| `NS_SEARCH_REFRESH_SECONDS` | `30` | Per-scope re-index interval. |

Search runs only with the caller's own scope; hits are re-fetched through the repository with that
scope. Auth to Azure is `DefaultAzureCredential` only (no keys).

### Write targets (api and workers, same names)

| Variable | Default | Effect |
|---|---|---|
| `NS_FOUNDRY_ENABLED` | `false` | `true` registers `foundry-model-swap`, but only with the four values below. |
| `NS_FOUNDRY_SUBSCRIPTION_ID`, `NS_FOUNDRY_RESOURCE_GROUP`, `NS_FOUNDRY_ACCOUNT`, `NS_FOUNDRY_LOCATION` | unset | The one Foundry account. Its cloud is always `NS_CLOUD`. |
| `NS_APIM_ENABLED` | `false` | `true` registers `apim-gateway`, but only with the two values below. |
| `NS_APIM_GATEWAY_ID`, `NS_APIM_DOMAIN_ID` | unset | The one registered gateway (from the gateway registry). |

Consequences: with nothing enabled the registry is empty and an action dry-run reports "no write
target", never a silent pass. Enabling a flag makes a model swap or gateway change *executable* by
the action executor (after approvals and permission recheck), so enable it only against an
approved environment. Government, advisory or permission-short connectors are skipped with a
logged reason and never registered. Credentials are the workload identity; no secret is
configured.

## Limits

- One connector per manifest name: one Foundry account and one APIM gateway per deployment. A
  second is skipped (`write_target_duplicate`, first wins).

## OPEN (not run, not verified)

- Live Azure AI Search (index, indexer, security trimming) needs an approved environment and
  `NS_LIVE_APPROVED=1`.
- Live Foundry / APIM writes need `NS_LIVE_APPROVED=1` and an operator-approved target.
- The Azure index needs a `text` field that is not yet defined (IaC creates the service only).
- Worker catalog writes do not invalidate the API's search index; freshness is the
  `NS_SEARCH_REFRESH_SECONDS` interval.
- No aliases are seeded (the sandbox generator emits none).
- Multiple APIM gateways in one registry (needs a registry keyed by gateway).
- `/v1` catalog search over HTTP needs an Entra token; the smoke test exercises it in-process
  with the workers' scope instead.
