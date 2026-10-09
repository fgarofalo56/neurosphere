# ADR-0002: Stack selection and version pins

- Status: accepted (pins re-verified at each PRP-00 run and by Dependabot)
- Date: 2026-10-08
- Deciders: Frank Garofalo
- Closes: gate G11 (`docs/RESEARCH-AND-GATES.md`)

## Context

PRP.md §2 required supported, pinned versions to be selected in Phase 0. The
operator accepted a default stack on 2026-10-08; a research pass the same day
checked current versions, support windows and licences against first-party
registries and Microsoft Learn. Every row below was observed on 2026-10-08
unless stated. Versions are major.minor; exact pins live in `uv.lock` and
`pnpm-lock.yaml`.

## Decision

### Runtimes and package managers

| Component | Pin | Support window | Licence | Source | Note |
|---|---|---|---|---|---|
| Python | 3.12 | EOL 2028-10 | PSF | https://devguide.python.org/versions/ | 3.13 allowed by `requires-python`; 3.12 is the CI target |
| uv | 0.12 | pre-1.0 | MIT/Apache-2.0 | https://pypi.org/project/uv/ | pin minor |
| Node.js | **24 LTS** | 2028-04-30 | MIT | https://github.com/nodejs/Release | Node 22 is in Maintenance (EOL 2027-04-30); the operator's default of 22 was adjusted to 24 |
| pnpm | 11.x | n/a | MIT | https://www.npmjs.com/package/pnpm | installed 11.17; 12.x exists, upgrade via Dependabot |

### Backend

| Component | Pin | Licence | Source | Note |
|---|---|---|---|---|
| FastAPI | 0.143 | MIT | https://pypi.org/project/fastapi/ | 0.x, pin minor |
| Starlette | 1.7 | BSD-3 | https://pypi.org/project/starlette/ | respect FastAPI's range |
| Pydantic | 2.14 | MIT | https://pypi.org/project/pydantic/ | |
| pydantic-settings | 2.15 | MIT | https://pypi.org/project/pydantic-settings/ | |
| uvicorn | 0.54 | BSD-3 | https://pypi.org/project/uvicorn/ | |
| azure-cosmos | 4.17 | MIT | https://pypi.org/project/azure-cosmos/ | hierarchical partition keys need ≥4.6 |
| azure-eventhub | 5.15 | MIT | https://pypi.org/project/azure-eventhub/ | |
| azure-eventhub-checkpointstoreblob-aio | 1.2 | MIT | https://pypi.org/project/azure-eventhub-checkpointstoreblob-aio/ | last release 2025-02; only blob checkpoint store |
| azure-identity | 1.26 | MIT | https://pypi.org/project/azure-identity/ | |
| azure-search-documents | 12.0 | MIT | https://pypi.org/project/azure-search-documents/ | breaking vs 11.x |
| azure-monitor-opentelemetry | 1.8 | MIT | https://pypi.org/project/azure-monitor-opentelemetry/ | |
| opentelemetry-sdk | 1.45 | Apache-2.0 | https://pypi.org/project/opentelemetry-sdk/ | keep contrib (`0.66b`) aligned |
| azure-ai-projects | 2.8 | MIT | https://pypi.org/project/azure-ai-projects/ | Government needs ≥2.0; preview features need `allow_preview=True` |
| openai | 3.26 | Apache-2.0 | https://pypi.org/project/openai/ | |
| mcp | 2.3 | MIT | https://pypi.org/project/mcp/ | spec 2026-07-28; OAuth 2.1 resource-server auth in SDK; set `validate_token_resource` explicitly; DCR deprecated |
| cloudevents | 2.2 | Apache-2.0 | https://pypi.org/project/cloudevents/ | |
| jsonschema | 4.26 | MIT | https://pypi.org/project/jsonschema/ | draft 2020-12 |
| pytest / pytest-asyncio / hypothesis | 9.1 / 1.4 / 6.168 | MIT / Apache-2.0 / MPL-2.0 | pypi | hypothesis is dev-only (file-level copyleft) |
| ruff / pyright / pip-audit | 0.16 / 1.1.4xx / 2.10 | MIT / MIT / Apache-2.0 | pypi | |
| httpx / respx | 0.28 / 0.23 | BSD-3 | pypi | |

### Frontend

| Component | Pin | Licence | Source | Note |
|---|---|---|---|---|
| React | 19.3 | MIT | https://www.npmjs.com/package/react | |
| Vite | 8.3 | MIT | https://www.npmjs.com/package/vite | needs Node ≥22.12 |
| TypeScript | **6.0.x** | Apache-2.0 | https://www.npmjs.com/package/typescript | TS 7 is incompatible with typescript-eslint 8.71 (`<6.1`) |
| @fluentui/react-components | 9.74 | MIT | https://www.npmjs.com/package/@fluentui/react-components | peer React `<20` |
| @azure/msal-browser / msal-react | 5.25 / 5.7 | MIT | npm | msal-react peers React `^19.2.1` |
| sigma / graphology | 4.0 / 0.26 | MIT | npm | WebGL map. **@cosmograph is CC-BY-NC and must not be used** |
| vega-lite / vega-embed / vega-interpreter | 6.5 / 7.3 / current | BSD-3 | npm | Vega compiles expressions with `Function` by default (https://vega.github.io/vega/usage/#csp); untrusted chart plans must use `vega-interpreter`, an allowlist schema, and no `url` data or loader |
| @tanstack/react-query / react-router / zustand | 5.104 / 8.4 / 5.0 | MIT | npm | |
| vitest / @testing-library/react / @playwright/test | 5.0 / 16.3 / 1.64 | MIT / MIT / Apache-2.0 | npm | |
| eslint / typescript-eslint / prettier | 10.12 / 8.71 / 3.9 | MIT | npm | flat config only |
| @modelcontextprotocol/server, /client | 2.3 | Apache-2.0 | https://github.com/modelcontextprotocol/typescript-sdk | v2 replaces `@modelcontextprotocol/sdk` 1.x |

### Infrastructure and tooling

| Component | Pin | Licence | Source | Note |
|---|---|---|---|---|
| Bicep CLI | 0.48 | MIT | https://github.com/Azure/bicep/releases | |
| Azure CLI / azd | 2.91 / 1.35 | MIT | learn.microsoft.com, github.com/Azure/azure-dev | |
| Helm | **4.3** | Apache-2.0 | https://helm.sh/blog/helm-v3-end-of-life/ | Helm 3 security fixes end 2027-02-10; charts target Helm 4 |
| Cosmos DB vNext emulator | `vnext-latest` | Microsoft EULA | https://learn.microsoft.com/azure/cosmos-db/emulator-linux | GA June 2026; no auth, no sprocs/triggers/UDF, no range/composite/spatial index, no RU accounting; change feed supported |
| Event Hubs emulator | `latest` | Microsoft EULA (`ACCEPT_EULA=Y`) | https://learn.microsoft.com/azure/event-hubs/overview-emulator | GA status unverified; SAS only, 1 namespace / 10 hubs, no persistence, needs Azurite |
| Azurite | `latest` | MIT | https://learn.microsoft.com/azure/storage/common/storage-use-azurite | Table preview; no ADLS Gen2 |
| MkDocs Material | 9.7.x | MIT | https://squidfunk.github.io/mkdocs-material/ | **EOL scheduled 2026-11-05**; Insiders split removed in 9.7. PRP-25 evaluates Zensical (MIT, same authors) before building the site |
| gitleaks | 8.30.1 binary, sha256 `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb` | MIT | https://github.com/gitleaks/gitleaks/releases | gitleaks-action needs a licence on org repos; binary used instead |
| GitHub Actions | checkout v7, setup-python v7, setup-node v7, pnpm/action-setup v6, codeql-action v4, astral-sh/setup-uv v7 | MIT | github.com | Dependabot keeps majors current |

## Consequences

- PRP-00 writes these pins into the member `pyproject.toml` / `package.json`
  files and expands this table to every lockfile dependency with licence and EOL.
- Dependabot `cooldown` (7 days minor, 14 days major) prevents same-day adoption
  of new releases.
- Any PRP that adds a runtime dependency with a non-permissive licence
  (copyleft, non-commercial, EULA) must add a row here and get operator approval.

## References

- Research pass 2026-10-08, summarised in `docs/RESEARCH-AND-GATES.md`.
- MCP versioning: https://modelcontextprotocol.io/specification/versioning
