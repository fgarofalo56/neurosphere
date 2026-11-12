# G12 evidence: PRP-31 round 2 item 12, UI surfaces real-stack loop

Date: 2026-11-11. Local compose emulators only (no paid or cloud calls, no `NS_LIVE_APPROVED`).
Raw output: `run-2026-11-11.txt`.

## Command

```
NS_AUTH_TENANT_ID=<synthetic tenant guid> NS_PROBE_COSMOS_URL=http://127.0.0.1:8081/ MSYS_NO_PATHCONV=1 \
  uv run pytest -v -rs -m integration -p no:randomly tests/integration/real_stack/test_ui_surfaces_loop.py
```

Result: 11 passed, 1 skipped (OPEN). The suite is `pytest.mark.integration`, so the plain run
deselects it and CI never runs it. The app is the production composition (`create_app` +
`compose_app`, default builders); only the token validator is a test stand-in.

## Stack seeding used (the stack was empty when this run began)

The compose emulators were up but the `neurosphere` database held no catalog data. The seed needs
the ingestion workers, which the `app` compose profile normally runs; that profile was not started
(it builds images). The same worker module was run as a host process against the emulators instead:

1. `python -m sandbox.generate --seed 1 --profile tiny --cloud commercial --out temp/sandbox`
2. `scripts/sandbox/sbx_cli.py seed --data-dir temp/sandbox` (sandbox world, event hub)
3. `python -m neurosphere_workers.runtime` on the host (`NS_WORKER_ROLES=all`, env as in
   `docker-compose.yml`, emulator endpoints at 127.0.0.1)
4. `scripts/sandbox/sbx_seed_stack.py --profile small --operator-object-id <suite operator oid>`

Tenant: the repo's fixed synthetic test tenant from `tests/integration/real_stack/conftest.py`
(`DEFAULT_TEST_TENANT`), so no `.env` value was needed. A real-tenant seed on this database would
be a second, independent tenant policy set.

## Per-step result

| Step | Result | Notes |
|------|--------|-------|
| 1 catalog search | pass | 200 with hits (`NS_SEARCH_PROVIDER=fixture`); term is a word of a seeded display name |
| 2 create entity | pass | 201 + ETag; id matches `<cloud>:<customer>:manual:agent:<32 hex>`; `domain_id` = path domain; body with `domain_id` -> 422 |
| 3 PUT with If-Match | pass | 200 and a new ETag; replay of the old ETag -> 409 |
| 4 deprecate + audit | pass | 200; audit record `outcome.detail == "entity_deprecate:reason=superseded"`, `kind=after`, `verified=true`, target `canonical_id` = the entity |
| 5 recertify | pass | 200 on a freshly created active **owner** (recertify applies to owners only, not agents) |
| 6 curation decision | pass | seeded edge found via lineage neighbors; 201; actor stamped as a `person` id; body with `actor` -> 422; a `channel=button` audit record names the edge |
| 7 stale agents | pass | dry-run 200, confirm 200. Window 3650 days so no seeded agent is marked (the plan is scope-wide) |
| 8 auditor-only | pass | `security_auditor` only: `/me/domains` 403; `/audit/domains` 200 non-empty; records read; `verify` -> `ok: true` (see gap 1 for how this principal was granted) |
| 9 emergency disable | pass | PUT disable, GET reflects it, PUT enable (in `finally`), GET reflects it |
| 10 reads | evaluation pass, federation pass, **forecast OPEN** | see gap 2 |

## Product gaps found (not fixed; product code is out of this item's ownership)

1. **No seeded persona can read any audit chain.** The audit API serves a domain id of the form
   `<cloud>:<customer>:catalog:domain:<name>` (chain `<customer>.<name>`, `authz/audit_mount.py`
   `domain_from_chain_id`), but the seeded world's domains are `<cloud>:<customer>:sandbox:domain:dom-00N`.
   With the seed's own grants, the `auditor` persona gets 403 `permission_missing` from
   `GET /api/v1/audit/domains` and the operator gets 403 `audit_chain_out_of_scope` on every
   seeded domain. Catalog writes in a sandbox domain do land in chain `synthco.dom-00N`. The suite
   works around it by granting a separate suite-owned principal `security_auditor` through the same
   `sbx_grant_operator` step with the domain list mapped to the `catalog:domain` form. The UI
   `/audit` page will show Forbidden for every persona on a stack seeded this way.
2. **Finops forecast is 409 `capability_unavailable` / `price_version_unresolved` in every seeded
   domain.** The compose price sheet (`infra/dev/ledger-prices.dev.json`) prices only
   `synthetic-model`, so every sandbox cost estimate is `price_unresolved`. Typed refusal, not a
   500. Step 10 forecast is skipped with an explicit OPEN reason, not faked.

## State left on the stack

- Entities created by the suite (`ui-loop-*` display names) are deprecated in the fixture teardown;
  the catalog has no delete, so they remain as deprecated entities in `dom-001`.
- Step 6 records an `accept` decision on one seeded `invokes` edge in `dom-001`.
- Emergency disable is re-enabled (verified by the GET in step 9).
- Policy-store grants for two suite-owned synthetic principals (operator, audit-only).
- Host worker process(es) from the seeding above are still running against the emulators; compose
  was never stopped or restarted.

## OPEN

- Finops forecast on the seeded world (gap 2).
- Audit readability of seeded domains (gap 1).
- The headed browser pass, provider-specific live tests, and any hosted run are not covered here.
