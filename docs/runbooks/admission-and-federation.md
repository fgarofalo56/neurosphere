# Admission control and federation

Operator guide for per-domain admission control and federated cells (PRP-21). Every number
here is a measured result against a provisional planning target, never a guarantee.

## Admission control

The API throttles each domain separately so a noisy domain cannot starve the others. It is a
step inside `require(...)` (`authz/dependencies.py`), not an ASGI middleware: the middleware
runs before authentication and cannot see the server-derived scope.

- **Charge point:** after the permission check passes. A denied request (401, 403) is never
  charged, so a caller cannot drain another domain's bucket.
- **Bucket key:** the server-derived scope plus the route domain that `permits` already
  validated. A caller-supplied header, query or body value never selects a bucket. A principal
  with several domains and no route domain shares one per-scope bucket (no multiplier).
- **Coverage:** every route that uses `require(...)`, once per request. Health and public paths
  are not charged. The ingest edge keeps its own per-producer limiter.
- **Answer when over quota:** `429` problem body with `code: rate_limited` and a `Retry-After`
  header (seconds).

### Settings

| Variable | Default | Meaning |
|---|---|---|
| `NS_ADMISSION_ENABLED` | `false` | Turn admission on. Off means no throttling and no behaviour change. |
| `NS_ADMISSION_POLICY_FILE` | unset | JSON or YAML quota policy. With admission on and no readable file the conservative default (10 req/s, burst 20 per domain) applies and a warning is logged. It is never unlimited. |

An invalid `NS_ADMISSION_*` value turns admission on with the default quota rather than off.

Policy file shape (see `infra/dev/admission-quotas.dev.json`):

```json
{
  "default": { "rate_per_second": 10, "burst": 20 },
  "domains": {
    "commercial:contoso:catalog:domain:finance": { "rate_per_second": 50, "burst": 100 }
  }
}
```

### Compose

The `api` service mounts `infra/dev/admission-quotas.dev.json` at
`/etc/neurosphere/admission-quotas.json` and sets `NS_ADMISSION_ENABLED` (default `true` in
compose; set `NS_ADMISSION_ENABLED=false` in the shell to turn it off).

### Helm

Set exactly one of `admission.policyFile` (a path inside the api pod, for example a vault
object) or `admission.policyConfigMap` (an operator-created ConfigMap with key `quotas.json`,
mounted read-only at `/etc/neurosphere/admission`). Neither set: no env, no mount, admission
off. Both set fails `helm template`.

### Rollback

Set `NS_ADMISSION_ENABLED=false` (or clear the Helm values). The dependency is a no-op when
`app.state.admission` is absent.
