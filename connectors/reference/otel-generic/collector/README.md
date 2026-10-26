# OpenTelemetry Collector example for the NeuroSphere ingest edge

`otel-collector.example.yaml` is configuration only. It is not started, tested against a live
collector or deployed by this repository; validate it with your collector distribution
(`otelcol validate --config otel-collector.example.yaml`) before use. The `transform` processor
needs the contrib distribution.

What it does:

- Receives OTLP (gRPC 4317, HTTP 4318).
- Deletes prompt/response body attributes (`prompt`, `response`, `gen_ai.prompt`,
  `gen_ai.completion`, `gen_ai.input.messages`, `gen_ai.output.messages`,
  `gen_ai.system_instructions`, and any `*.prompt` / `*.response`) before export. The ingest
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

Specs (observed 2026-10-17): OTLP https://opentelemetry.io/docs/specs/otlp/ and CloudEvents 1.0
https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md. The Python connector in
`../neurosphere_connector_otel_generic/` is the alternative for code that already uses
`opentelemetry-sdk` or emits CloudEvents.
