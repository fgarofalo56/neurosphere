# Platform configuration: domains, budgets, price sheets, review policy

The platform configuration API (PRP-44) gives an administrator an audited home for four objects
that used to live in code, environment files or a seeder:

- the **domain registry** (which domains exist),
- **budgets** with alert thresholds per domain (stored only),
- versioned **price sheets** that price the ingestion cost ledger,
- the **human-review policy** (SLA, escalation, expiry; maker-checker stays strict).

All routes are under `/api/v1/admin/platform` and need **customer-level** `config.manage` (held on
the customer-control domain). A domain admin gets 403 `customer_scope_required`; every refusal
writes a denial record. Every accepted write is audited on the `<customer>.admin-config` chain. No
price value and no policy body is ever put in a log line or an audit record.

## 1. Domains

| Method | Path | Notes |
|---|---|---|
| POST | `/domains` | create, 201 with `ETag`; duplicate is 409 |
| GET | `/domains` | list (`include_retired`) |
| GET | `/domains/{domain_id}` | read |
| POST | `/domains/{domain_id}/retire` | `If-Match` required |

The id must be canonical for this deployment's cloud and your customer
(`<cloud>:<customer>:<source>:domain:<name>`). The reserved `customer-control` domain is registered
automatically the first time you create a domain (`control_registered: true` in the response), carries
`is_control_domain: true`, and can never be retired. Names that collide with a customer-wide audit
chain (`admin-config`, `gateway`, `execution-control`) are refused. A retired domain keeps its record
and stops counting as registered.

**Enforcement.** Once at least one domain is registered, the identity admin routes refuse to **add**
a role assignment, membership or grant that names an unregistered domain (422
`domain_not_registered`). Removals are never blocked, so access to a retired domain can always be
cleaned up. With an empty registry nothing changes.

## 2. Budgets

`POST/GET/PUT/DELETE /budgets[/{budget_id}]`. A budget names a registered domain, a `period`
(`monthly`, `quarterly`, `annual`), a decimal-string `amount` (never a float), a `currency` and
strictly increasing `thresholds_percent` between 1 and 200. `DELETE` retires the record.

Budgets are **stored only**: nothing evaluates them against spend and nothing sends an alert yet.

## 3. Price sheets

`POST /price-sheets` uploads a `PriceSheetUpload`; the server builds the `PriceSnapshot`, stamps its
content hash and appends it to `price_snapshots`:

| Outcome | Status |
|---|---|
| new `snapshot_id` | 201 |
| same `snapshot_id`, same content | 200 (`created: false`) |
| same `snapshot_id`, different content | 409 `snapshot_conflict` |
| sheet does not list this cloud | 422 `cross_cloud` |
| `synthetic: true` outside `NS_ENV=local` | 422 `synthetic_refused` |
| `azure_retail_prices` for Government | 422 (the model rule) |

A changed price list is a **new** `snapshot_id` with a later effective date; there is no update or
delete. `GET /price-sheets`, `/{snapshot_id}` and `/{snapshot_id}/coverage` return summaries without
rows. The **coverage report** lists models priced (input and output both present), models
incomplete (only one side: the ledger would silently skip them, so fix the sheet), and rows without
a token meter. Incomplete models are a warning, not a rejection.

The ingestion worker merges stored snapshots (this cloud only) with the optional
`NS_LEDGER_PRICE_TABLE_FILE` table when it **starts**. Equal ids with identical content collapse;
equal ids with different content refuse startup with `price_version_conflict`. If the snapshot store
cannot be read, the role starts on the file table with one log line (`price_snapshot_store_unavailable`).
Government sheets are customer-supplied and unverified.

## 4. Review policy

`GET /review-policy` returns the stored policy, or the built-in defaults with `ETag: "defaults"`.
`PUT /review-policy` replaces it and **requires `If-Match`** (use `"defaults"` for the first write).
The response carries the before and after documents and a value-level diff; the server sets
`policy_version` to `admin-v<N>`.

Rules: durations are positive, `sla` is at least 60 seconds, `expiry` at most 90 days,
`max_escalations` 0 to 10, and the approver permission is `action.approve` or `catalog.curate`.
`maker_checker` can **never** be loosened: `self_approval_forbidden` stays true and its approver stays
`action.approve`, for the default and for every per-action override.

A stored policy applies when the API and the `actions`, `hitl_timers` and `evaluation` worker roles
**next start** (no hot reload). With nothing stored, behaviour is identical to the built-in defaults.
A store read failure keeps the defaults and logs one reason-coded line.

## 5. Operator checks

1. `POST /domains` for each domain, then the identity admin routes start validating domains.
2. Upload your provider sheet; read `/coverage`; fix any incomplete model and upload a new
   `snapshot_id`.
3. Restart the ingestion worker; an estimated observation then cites the stored price version, and
   the forecast route stops answering `price_version_unresolved`.
4. Restart the API and the three review roles after changing the review policy.

Not configured here: budget alert delivery, scraping provider prices, a catalog-wide "which models
have no price" view, the dev-stack price seed (PRP-38) and the console pages (PRP-53, PRP-57).

## 6. Environment variables

No new `NS_*` variable. Existing: `NS_LEDGER_PRICE_TABLE_FILE` (optional file table), `NS_ENV`
(`local` allows `synthetic` sheets), `NS_COSMOS_*` / `NS_STORE_*` (the stores).
