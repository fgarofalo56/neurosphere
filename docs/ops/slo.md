# Service level objectives (planning targets)

Every figure here is a **planning target, to be measured**. None is a guarantee, an SLA or a
claim about current performance. Measurement starts when the owning PRP ships the instrumented
path; until then each row is unmeasured.

| SLO | Target (planning target, to be measured) | Measurement method | Metric name | Owner PRP |
|---|---|---|---|---|
| API availability | 99.9% of requests succeed over a rolling 30 days | `1 - errors / requests`, from error count over request count, excluding planned maintenance windows declared in advance | `ns.api.request.errors`, `ns.api.request.duration` | PRP-21 |
| Dashboard query latency | p95 <= 2 s on bounded 90-day aggregates | p95 of the dashboard query duration histogram, server side, per tenant scope | `ns.dashboard.query.duration` | PRP-14 |
| Catalog query latency | p95 <= 500 ms on indexed, scoped queries | p95 of the catalog query duration histogram, indexed and scoped queries only | `ns.catalog.query.duration` | PRP-10 |
| Live map freshness | p95 <= 10 s after normalized ingestion | p95 of lag between the normalized event timestamp and map availability | `ns.map.freshness.lag` | PRP-18 |

## Metric names

The only SLO metric names are:

- `ns.api.request.duration`
- `ns.api.request.errors`
- `ns.dashboard.query.duration`
- `ns.catalog.query.duration`
- `ns.map.freshness.lag`

They are emitted by the observability package (PRP-05 item 4). The Grafana dashboard
(`infra/observability/grafana-slo-dashboard.json`) and Azure Workbook
(`infra/observability/azure-workbook-slo.json`) visualize these names only. Backends may add
unit or histogram suffixes on export; adjust the queries to the exporter in use.

## Caveats

- **Provider billing freshness is not sub-10 s.** Cloud billing and cost exports arrive on the
  provider's schedule (typically hours). The 10 s map freshness target applies only to
  NeuroSphere's own normalized telemetry ingestion, never to provider billing data.
- **Copilot first-token <= 3 s** is a separate planning target, to be measured. It excludes
  provider outages and provider-side throttling of the model endpoint.
- Availability, feature maturity and authorization are separate gates. Nothing here claims
  FedRAMP authorization, ATO or compliance parity.

## Health endpoints

- `GET /healthz`: 200 while the process is up. It checks no dependency.
- `GET /readyz`: 200 only when every dependency probe reports `ok`; otherwise 503 (fail
  closed). The body lists each dependency by name with an enumerated reason code
  (`ok`, `timeout`, `connection_refused`, `unavailable`). It never contains connection
  strings, keys, URLs or hostnames.

Probe configuration (plain TCP/HTTP checks, no secrets; emulator defaults shown):

| Variable | Default | Meaning |
|---|---|---|
| `NS_PROBE_COSMOS_URL` | `http://localhost:8081/` | Cosmos endpoint, any HTTP status below 500 is ok |
| `NS_PROBE_EVENTHUBS_HOSTPORT` | `localhost:5672` | Event Hubs AMQP TCP connect |
| `NS_PROBE_BLOB_HOSTPORT` | `localhost:10000` | Blob (Azurite) TCP connect |
| `NS_PROBE_TIMEOUT_SECONDS` | `2.0` | Per-probe timeout; probes run concurrently |
