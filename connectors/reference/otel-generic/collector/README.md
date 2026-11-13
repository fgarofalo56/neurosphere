# OpenTelemetry Collector example for the NeuroSphere ingest edge

`otel-collector.example.yaml` is configuration only and is not deployed by this repository (the
compose-profile derivative below is exercised against a real collector); validate it with your collector distribution
(`otelcol validate --config otel-collector.example.yaml`) before use. The `transform` processor
needs the contrib distribution.

What it does:

- Receives OTLP (gRPC 4317, HTTP 4318).
- Deletes prompt/response body attributes (`prompt`, `response`, `gen_ai.prompt`,
  `gen_ai.completion`, `gen_ai.input.messages`, `gen_ai.output.messages`,
  `gen_ai.system_instructions`, bare `completion` and `messages`, and any `*.prompt` / `*.response`) before export. The ingest
  edge drops them too; this keeps them off the wire.
- Sends OTLP/JSON, uncompressed, to `/api/v1/ingest/otlp/traces` and
  `/api/v1/ingest/otlp/metrics` with `Authorization: Bearer <producer_id>.<secret>`.
- The old `/v1/ingest/...` paths still work for one release as deprecated aliases: they answer
  with `Deprecation: true`, `Sunset: Fri, 30 Apr 2027 00:00:00 GMT` and a `Link` header naming
  the `/api/v1/ingest/...` successor. Move existing collectors before the sunset date.

Things to know:

- **Credential**: set `NS_PRODUCER_CREDENTIAL` in the collector's environment from Key Vault
  (managed identity). It is never written to the file. The producer must be registered at the
  edge (hash only) for the customer, cloud and `neurosphere.source_id` you send.
- **Cloud boundary**: point a Commercial collector at the Commercial edge and a Government
  collector at the Government edge. The edge rejects a producer registered for the other cloud.
- **Metrics**: the edge maps only delta sums and gauges of the known token metric names;
  histograms and cumulative sums are reported back as ignored, not silently dropped.
- **Unknown stays unknown**: missing token counts or end times arrive as nulls, never 0.
- **Retries and limits**: the edge answers 429 with `Retry-After` when a producer exceeds its
  rate limit; the exporter retries with backoff. Bodies over the edge size cap are rejected 422.

## Compose profile `otel` (PRP-09 item 10)

`otel-collector.compose.yaml` is the example config pointed at the composed `api`
(`http://api:8000/api/v1/ingest/...`). `docker-compose.yml` runs it as service `otel-collector`
(official `otel/opentelemetry-collector-contrib`, pinned to an exact tag, see ADR-0002) under the
opt-in profile `otel`; OTLP/gRPC is on `127.0.0.1:4317` and OTLP/HTTP on `127.0.0.1:4318`.

```bash
# The dev producer is registered by infra/dev/ingest-producers.dev.json; its throwaway secret is
# in docs/runbooks/ingest.md. Export "<producer_id>.<secret>" from your shell, never a file.
export NS_PRODUCER_CREDENTIAL=...
docker compose --profile app --profile otel up -d --wait
# send OTLP/HTTP JSON to http://127.0.0.1:4318/v1/traces, then stop only what you started:
docker compose --profile app --profile otel rm -sf api otel-collector
```

If `NS_PRODUCER_CREDENTIAL` is unset the collector sends an empty bearer and the edge answers
401 (the collector retries, then drops). Use `127.0.0.1`, not `localhost`. The contrib image has no
shell, so the service has no healthcheck; clients wait for port 4318. Validate a config change
with `docker run --rm -v <file>:/c.yaml:ro otel/opentelemetry-collector-contrib:<tag> validate --config=/c.yaml`.

The compose-gated test is `tests/integration/connectors/test_otel_collector_compose.py`
(marker `integration`, skipped when the stack is not up, not run in CI).

**G12 delta**: the Event Hubs emulator has no Entra producer identity, so the edge authenticates
the producer by its registered credential (a hash-compared bearer token) instead. Entra producer
identity and the managed-identity path to a real namespace stay with the live gate (G12), OPEN
until an approved run.

Specs (observed 2026-10-17): OTLP https://opentelemetry.io/docs/specs/otlp/ and CloudEvents 1.0
https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md. The Python connector in
`../neurosphere_connector_otel_generic/` is the alternative for code that already uses
`opentelemetry-sdk` or emits CloudEvents.
