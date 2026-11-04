# Runbook: ingest producers

The ingest edge (`/v1/ingest/...`) authenticates producers with `Authorization: Bearer <producer_id>.<secret>`. The api stores SHA-256 digests only, in a JSON producers file. The file is opt-in: with `NS_INGEST_PRODUCERS_FILE` unset, every ingest route fails closed.

## Unset behavior

- Ingest routes answer `503` with code `ingest_not_configured`.
- `/readyz` lists `composition.ingest.disabled`. This is not blocking: ingest is an optional component and `disabled` means "deliberately off, no producers file configured".
- A set but unreadable or malformed file fails api startup (fail fast); it never silently disables ingest.

## File shape

```json
{ "producers": [ { "producer_id": "...", "secret_sha256": "<64 hex>", "customer_id": "...",
  "cloud": "commercial", "sources": { "<source_id>": "application" } } ] }
```

Only `secret_sha256` digests belong in the file. Generate one with
`python -c "import hashlib,sys;print(hashlib.sha256(sys.argv[1].encode()).hexdigest())" <secret>`
and hand the plaintext secret to the producer through your secret channel, never through a repo or Helm values.

## Local compose (dev only)

`docker-compose.yml` mounts `infra/dev/ingest-producers.dev.json` read-only into the `api` service at `/etc/neurosphere/ingest-producers.json` and sets `NS_INGEST_PRODUCERS_FILE`. It registers producer `dev-ingest` (customer `synthco`, source `dev-source`).

DEV ONLY, throwaway: the secret for that digest is `ns-dev-only-ingest-secret`, so the bearer token is `dev-ingest.ns-dev-only-ingest-secret`. It protects an emulator-only stack; never register it in a hosted environment.

## Helm (operator-supplied file)

Both values are empty by default (ingest disabled). Set exactly one; setting both fails `helm template`.

- `ingest.producersFile`: path inside the api pod. Use it with the Key Vault CSI mount: add the producers file as an object under `secretProviderClass.objects` and point this at `/mnt/vault/<object name>`.
- `ingest.producersConfigMap`: name of an operator-created ConfigMap holding the file under key `producers.json`; it is mounted read-only at `/etc/neurosphere/ingest/` in the api pod and `NS_INGEST_PRODUCERS_FILE` is set to `/etc/neurosphere/ingest/producers.json`.

The ConfigMap holds digests only, so it is acceptable; plaintext secrets must never go in one.

## Verify

1. `curl -s localhost:8000/readyz`: `composition.ingest.disabled` is absent when configured, present when not.
2. POST an OTLP trace to `/v1/ingest/otlp/traces` with the producer bearer token: `202` when configured, `401` for a wrong secret, `503 ingest_not_configured` when unset.
