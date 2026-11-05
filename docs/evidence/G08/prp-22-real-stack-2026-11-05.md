# G08 / PRP-22: MCP feature against the composed stack (2026-11-05)

Status: evidence aid for the G08 row (MCP authorization-spec behaviour), not an assessment.
NeuroSphere is not FedRAMP authorized and holds no ATO; nothing here claims either, or parity
between clouds. Commercial profile only, local compose emulators only, no paid or cloud calls.
Government MCP use stays OPEN (G01/G02).

Observed: 2026-11-05, PRP-22 audit close-out lane R, on the integration branch
`prp-22-audit-closeout` (lanes S, C and M merged).

## What ran

The production composition (`create_app` + `compose_app`, default builders) was served by uvicorn
on `127.0.0.1:<free port>` inside the pytest process, against the compose emulators
(`docker compose up -d --wait`: Cosmos vNext on `127.0.0.1:8081`, Azurite, Event Hubs). The
`api` container of the `app` profile was not used: it accepts real Entra tokens only, and this run
uses the local dev issuer.

Configuration came only from the process environment (no file), set by
`tests/security/mcp/mcp_live_stack.py`:

```
NS_ENV=local  NS_CLOUD=commercial  NS_COSMOS_ENDPOINT=http://127.0.0.1:8081
NS_STORE_DATABASE=ns_mcp_live_<random hex> (throwaway, deleted afterwards)
NS_AUTH_TENANT_ID=<fixed non-routable test tenant>  NS_AUTH_AUDIENCES=api://neurosphere-live-rest
NS_AUTH_CUSTOMER_ID=synthco  NS_COPILOT_MODE=disabled  NS_SEARCH_PROVIDER=fixture
NS_FOUNDRY_ENABLED=false  NS_APIM_ENABLED=false  NS_CORS_ALLOWED_ORIGINS=
NS_MCP_RESOURCE_SERVER_URL=https://mcp.neurosphere.test/mcp
NS_MCP_AUDIENCES=["api://neurosphere-live-mcp"]  NS_MCP_REQUIRED_SCOPE=mcp.invoke
NS_MCP_ALLOWED_HOSTS=["127.0.0.1:<port>"]
```

The Cosmos key was built at runtime (the emulator ignores it) and is not recorded.

The only stand-ins are the two token validators, passed through `CompositionOverrides` as
`tests/integration/real_stack/conftest.py` does. A local `DevIssuer` (`NS_ENV=local` only) is
trusted by the REST validator (REST audience) and by the MCP validator (`backends["mcp_validator"]`,
MCP audience). Everything after token validation is the composed production path: the
`ScopeDeriver` over the Cosmos policy store, the Cosmos revocation checker, the Cosmos catalog,
the Cosmos MCP registry and the admin plane's SSRF-vetted `ExternalMcpClient`, which uses the
system resolver.

Data: `scripts/sandbox/sbx_seed_catalog.py --profile small` loaded 119 entities, 127 edges and 6
grants across 3 domains into the throwaway database. The operator-grant code
(`sbx_grant_operator.py`) then granted three principals with random object ids: a viewer on one
domain, an analyst on that same domain, and an admin on all 3. Tokens were minted at runtime and
never printed. Afterwards the database was deleted (the emulator listed no databases) and the
stack was brought down with `docker compose down`. No volumes existed before or after.

## Commands

```
docker compose ps -a                      # empty: stack down before the run
docker compose up -d --wait               # emulators only
uv run python -m pytest -m integration tests/security/mcp -q -s
docker compose down
```

Result: `6 passed, 49 deselected in 40.63s`, broken down as follows:

| Test file | Tests | What it proves |
|---|---|---|
| `test_mcp_real_stack_live.py` | 1 | The checks below, against the live process |
| `test_mcp_compose_roundtrip.py` | 4 | Item 2's client against the composed `/mcp` over a TCP socket |
| `test_mcp_registry_cosmos_emulator.py` | 1 | `CosmosMcpServerStore` on the emulator |

## Live checks (redacted output of `test_mcp_real_stack_live.py`)

```
GET /.well-known/oauth-protected-resource/mcp -> 200; resource=https://mcp.neurosphere.test/mcp; authorization_servers=[login.microsoftonline.com/<tenant>/v2.0]; scopes_supported=['mcp.invoke']
OPTIONS /.well-known/oauth-protected-resource/mcp (preflight) -> 204; access-control-allow-origin=*
POST /mcp tools/list without token -> 401; WWW-Authenticate carries resource_metadata
POST /mcp tools/list as viewer (MCP token) -> 200; tools=['get_action_status', 'get_cost_summary', 'list_recommendations', 'search_catalog']
POST /mcp tools/list as analyst (MCP token) -> 200; tools=['draft_action', 'get_action_status', 'get_cost_summary', 'list_recommendations', 'present_action_confirmation', 'search_catalog', 'validate_action']
tools/call search_catalog: viewer -> 200, rows from 1 domain (its own); admin -> 200, rows from 3 domains
tools/call search_catalog as viewer with another seeded domain as filter -> 200, 0 rows (narrowed); as a domain_id argument -> 200, isError forbidden/scope_argument_refused
POST /mcp tools/list with token for another audience -> 401
POST /mcp tools/list with REST-audience token -> 401
POST /mcp tools/list with MCP token lacking mcp.invoke -> 403
GET /api/v1/me/domains with MCP-audience token -> 401; with REST token -> 200
GET /api/v1/mcp/admin/servers: viewer -> 403 (forbidden/permission_missing); admin -> 200, items=0
POST /api/v1/mcp/admin/servers as viewer -> 403
stub MCP server on 127.0.0.1:<port> answers directly: POST /mcp tools/list -> 200
POST /api/v1/mcp/admin/servers as admin url=https://127.0.0.1:<port>/mcp -> 403 (forbidden/ssrf_blocked_address)
POST /api/v1/mcp/admin/servers as admin url=https://localhost:<port>/mcp -> 403 (forbidden/ssrf_blocked_host)
POST /api/v1/mcp/admin/servers as admin url=https://[::1]:<port>/mcp -> 403 (forbidden/ssrf_blocked_address)
POST /api/v1/mcp/admin/servers as admin url=https://[::ffff:127.0.0.1]:<port>/mcp -> 403 (forbidden/ssrf_blocked_address)
POST /api/v1/mcp/admin/servers as admin url=http://127.0.0.1:<port>/mcp -> 422 (invalid_schema/invalid_server_url)
GET /api/v1/mcp/admin/servers as admin after the attempts -> items=0
POST /api/v1/mcp/admin/servers as admin url=https://localtest.me:<port>/mcp -> 201 (registered)
POST /api/v1/mcp/admin/servers/<id>/sync as admin -> 503 (dependency_transient/mcp_dns_unavailable)
GET /api/v1/mcp/admin/servers/<id>/tools -> 200, items=0 (nothing synced, so nothing can be approved)
```

What these lines show:

- **The MCP route exists** when `NS_MCP_RESOURCE_SERVER_URL` is set. The RFC 9728 metadata names
  the Commercial Entra v2 issuer for the tenant. The metadata preflight answers 204, where it
  answered 405 before lane S. An unauthenticated `/mcp` gets a 401 challenge with
  `resource_metadata`.
- **Tool listing and reads are scoped.** `tools/list` is scope-derived: the viewer gets no action
  tools, while the analyst gets `draft_action`, `validate_action` and
  `present_action_confirmation`. A read returns only the caller's domain, while the admin sees
  rows from all 3 seeded domains. So the filter is real, not an empty catalog.
- **Audiences and scopes are kept apart.** A token for another audience gets 401. A REST token at
  `/mcp` gets 401, and an MCP token at REST gets 401. A token without `mcp.invoke` gets 403.
- **Admin routes enforce `config.manage`.** The viewer gets 403, the admin gets 200.
- **The SSRF guard refused the loopback stub live.** A real stub MCP server was listening on
  `127.0.0.1` and answered a direct `tools/list` with 200. Registering it was refused for every
  loopback spelling, and nothing was registered. So register, sync and approve against a
  loopback server cannot happen.
- **Resolved-address check at sync (`localtest.me`): not proven live on this host.** The name's
  public A record is `127.0.0.1`. Registration accepts it, because registration does no DNS, and
  that is expected. On this machine the sync failed closed with **503 `mcp_dns_unavailable`**
  rather than 403 `ssrf_blocked_address`: the local resolver sinkholes the name (`nslookup`
  returned `0.0.0.0` and `::`, and `getaddrinfo` failed). Nothing was fetched and no tool was
  listed. The live run therefore does not prove the resolved-address refusal at sync. That refusal
  is proven with stub DNS in `test_mcp_compose_roundtrip.py`
  (`test_a_private_answer_for_the_registered_host_sends_nothing`: `ssrf_blocked_address`, zero
  requests) and in the client suites.

## Compose-backed roundtrip (`test_mcp_compose_roundtrip.py`, 4 passed)

Item 2's `ExternalMcpClient` registered the composed API's MCP resource
(`https://mcp.neurosphere.test/mcp`), synced it, approved `search_catalog` and called it over TCP.
The NeuroSphere platform credential was a viewer MCP token.

One thing is not production: the client's DNS answer. A stub resolver answers a public test
address, so `vet_target` vets and pins it. The transport factory then sends that vetted request to
`127.0.0.1:<port>` over HTTP, keeping the original `Host` header. A real loopback answer is
refused by the guard, as shown above.

- Before sync the call is refused with `tool_not_approved` and nothing is sent.
- The tools recorded by the sync equal the live, scope-derived `tools/list` for that token:
  `search_catalog` is present and `draft_action` is absent.
- After approval the call returns `untrusted_external` data with provenance.
- Every returned row is in the viewer's single domain, while the admin's unfiltered search spans
  more than one domain.
- On the wire, the only URL was the registered one, and the only credential was the platform's
  own token.
- Unapproved tools are refused without a request.
- A private DNS answer gives `ssrf_blocked_address` with nothing sent.
- A REST-audience platform token is rejected by the live server, and the client maps it to
  `forbidden/mcp_auth_rejected` (lane C).

## Cosmos registry store on the emulator (`test_mcp_registry_cosmos_emulator.py`, 1 passed)

The test used a fresh database, which was deleted afterwards.

- The container has partition key `/id`.
- Registration creates a document with `doc_type=mcp_server`, and the Cosmos `_etag` becomes the
  store ETag. A duplicate registration (same URL, different case and port spelling) maps the
  emulator 409 to `server_already_registered`.
- Sync from a real SDK `MCPServer` leaves both tools pending and not callable.
- Approval records the actor and the hash, and the call then goes through.
- A changed tool description revokes the tool on the next sync with `hash_changed`. The approved
  hash and entry are kept for the diff, and the call is refused.
- `list()` ran the parameterised `SELECT TOP @limit ... ORDER BY c.registered_at` on the emulator,
  in registration order.
- A stale ETag on replace maps the emulator 412 to `server_modified`.
- An independent client read back the disabled status and the revoked tool.

Emulator limits (G12): no auth enforcement, no RU accounting, and no composite or range indexes.
None of the store's operations needed a missing feature: the single-field `ORDER BY` worked. This
proves document shape and conditional semantics on the emulator, not RBAC, throughput or
consistency in Azure.

## Injection corpus honesty (offline, `test_injection_via_tool_output.py`)

The PRP-12 corpus (78 cases) is delivered through an approved external MCP tool's output and
carried out by a compromised agent. In this suite the data ports ignore scope, so only
NeuroSphere's tool layer can narrow a read.

- **Exercised for real: 18 cases, all pass.**
  - 11 retrieve cases are sent to all three MCP read tools: once with the target domain as a
    filter, once as a smuggled `domain_id` argument, once as a smuggled `customer_id`, and once as
    an unfiltered read.
  - 7 tool-call cases name an MCP read tool and send valid baseline arguments plus the hostile
    keys.
  - Call decisions: 61 narrowed to scope, 25 `scope_argument_refused`, 2 `argument_not_allowed`,
    and 1 MCP-client refusal (`missing_data_read`, the auditor).
- **Not applicable: 60 cases**, counted separately and never as passes:

  | Count | Reason |
  |---|---|
  | 13 | `no_model_in_loop` |
  | 13 | `no_fetch_tool` |
  | 8 | `no_reveal_tool` |
  | 7 | `no_chart_tool` |
  | 7 | `no_query_language_tool` |
  | 7 | `permission_not_exposed` |
  | 5 | `tool_not_exposed` |

  Their sanity probes were all refused: `tool_not_registered`, `invalid_arguments`, and
  registry URL refusals.
- **Totals:** 0 overscoped retrievals, 0 intents and 0 leaks.
- **Controls:**
  - Drafting bridge: 12 of 12 cases comply.
  - Tool-layer narrowing removed: an overscoped retrieval is reported.
  - Benign in-scope read: complies.
  - Baseline arguments alone execute for each read tool, so every refusal comes from the
    hostile key.

## Still OPEN

- **Browser UI pass of `frontend/src/features/mcp-admin/` against the real API.** The repo's
  real-stack Playwright setup (`frontend/playwright.real-stack.config.ts`, `tests/real-stack/`)
  needs a human to complete a real Entra sign-in in a headed browser. It also needs the compose
  `app` profile with real Entra ids, and that profile cannot accept dev-issuer tokens. An agent
  cannot do this, so it did not run. The admin UI is still proven against the mock API only.
- **Government MCP use and live Entra audience behaviour** (G01/G02): there is no live test.
- **MCP spec drift**: the spec revision 2026-07-28 will move, so G08 stays NARROWED.
- **#132**: the composed `WriteTargetRegistry` is empty, so MCP-initiated writes are advisory
  only. `draft_action` drafts, but no write target executes.
- **The resolved-address SSRF refusal at sync on a live resolver** (see above): proven with stub
  DNS only.
