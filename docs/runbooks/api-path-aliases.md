# API path aliases (deprecated)

Six routers moved under `/api/v1` and kept their old prefix for one release (PRP-29). Every
alias operation is marked `deprecated` in OpenAPI and answers with:

| Header | Value |
|---|---|
| `Deprecation` | `@<epoch seconds>` of `DEPRECATED_AT` (RFC 9745) |
| `Sunset` | `Fri, 30 Apr 2027 00:00:00 GMT` (RFC 8594) |
| `Link` | `<successor path>; rel="successor-version"` |

The headers are added by an ASGI middleware (`install_alias_headers`, installed by
`compose_app`), so 401, 403, 422 and 503 answers on an alias path carry them too. The
successor path is percent-encoded and computed after stripping `root_path`.

| Alias | Successor |
|---|---|
| `/catalog` | `/api/v1/catalog` |
| `/catalog/curation` | `/api/v1/catalog/curation` |
| `/audit` | `/api/v1/audit` |
| `/v1/ingest` | `/api/v1/ingest` |
| `/v1/deploy/scan` | `/api/v1/deploy/scan` |
| `/v1/deploy/plan` | `/api/v1/deploy/plan` |

## nginx edge limitation

The UI nginx proxies only `/api/`, `/readyz` and `/healthz` to the API. The alias paths
(`/catalog`, `/catalog/curation`, `/audit`, `/v1/ingest`, `/v1/deploy/scan`, `/v1/deploy/plan`)
and `/mcp` are therefore reachable only on the API port directly, never through the edge.
Clients behind the edge must already use the `/api/v1` forms.

## Removal checklist (not before the Sunset date, 2027-04-30)

`services/api/tests/path_aliases/test_alias_middleware.py::test_alias_removal_is_not_due_yet`
turns red on that date and points here.

1. Confirm no client still calls an alias path (access logs for the six prefixes).
2. Replace `register_with_alias` calls with plain `registry.register(prefix, router)`.
3. Delete the alias half of `deprecation.py`, the alias tests under
   `services/api/tests/path_aliases/`, and the `install_alias_headers` line in `compose_app`.
4. Regenerate `services/api/openapi.json` and `docs/reference/**`.
5. Update the route inventories that list alias paths.
