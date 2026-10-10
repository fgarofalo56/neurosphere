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

## Appendix: dependency and tooling register (PRP-00 item 4)

The decision tables above are unchanged. This appendix records every dependency in
`uv.lock` and `pnpm-lock.yaml` with its resolved version, licence and scope, plus the
runtime tooling that is not a lockfile dependency. The same data, with a support note per
package, is in `docs/licenses.md`. Licences are read from locally installed metadata only;
`python scripts/licenses_report.py --check` (CI planning job) fails on an `UNKNOWN` licence,
on a non-permissive licence (copyleft, non-commercial, EULA) that is not allowlisted with a
reason, on `@cosmograph/*`, and when either generated file is stale. MPL-2.0 is accepted
only when the package is dev-only (hypothesis, for example).

### Appendix A: lockfile dependencies (generated; do not edit between the markers)

<!-- BEGIN licences-register (generated by scripts/licenses_report.py) -->

#### Python (uv.lock): 72 packages

| Component | Pin | Licence | Source | Note |
|---|---|---|---|---|
| annotated-doc | 0.0.5 | MIT | https://pypi.org/project/annotated-doc/ | runtime; 0.x: minor releases may break; no support window recorded |
| annotated-types | 0.8.0 | MIT | https://pypi.org/project/annotated-types/ | runtime; 0.x: minor releases may break; no support window recorded |
| anyio | 4.15.1 | MIT | https://pypi.org/project/anyio/ | runtime; no EOL published locally; Dependabot tracks releases |
| argcomplete | 3.7.2 | Apache-2.0 | https://pypi.org/project/argcomplete/ | dev-only; no EOL published locally; Dependabot tracks releases |
| attrs | 26.1.0 | MIT | https://pypi.org/project/attrs/ | runtime; no EOL published locally; Dependabot tracks releases |
| black | 26.10.1 | MIT | https://pypi.org/project/black/ | dev-only; no EOL published locally; Dependabot tracks releases |
| boolean-py | 5.0 | BSD-2-Clause | https://pypi.org/project/boolean-py/ | dev-only; no EOL published locally; Dependabot tracks releases |
| cachecontrol | 0.14.4 | Apache-2.0 | https://pypi.org/project/cachecontrol/ | dev-only; 0.x: minor releases may break; no support window recorded |
| certifi | 2026.7.22 | MPL-2.0 | https://pypi.org/project/certifi/ | dev-only; no EOL published locally; Dependabot tracks releases |
| charset-normalizer | 3.5.2 | MIT | https://pypi.org/project/charset-normalizer/ | dev-only; no EOL published locally; Dependabot tracks releases |
| click | 8.5.0 | BSD-3-Clause | https://pypi.org/project/click/ | runtime; no EOL published locally; Dependabot tracks releases |
| colorama | 0.4.6 | BSD | https://pypi.org/project/colorama/ | dev-only; 0.x: minor releases may break; no support window recorded |
| cyclonedx-python-lib | 11.12.0 | Apache-2.0 | https://pypi.org/project/cyclonedx-python-lib/ | dev-only; no EOL published locally; Dependabot tracks releases |
| datamodel-code-generator | 0.83.0 | MIT | https://pypi.org/project/datamodel-code-generator/ | dev-only; 0.x: minor releases may break; no support window recorded |
| defusedxml | 0.7.1 | PSF-2.0 | https://pypi.org/project/defusedxml/ | dev-only; 0.x: minor releases may break; no support window recorded |
| fastapi | 0.143.0 | MIT | https://pypi.org/project/fastapi/ | runtime; 0.x: minor releases may break; no support window recorded |
| filelock | 4.0.12 | MIT | https://pypi.org/project/filelock/ | dev-only; no EOL published locally; Dependabot tracks releases |
| genson | 1.4.0 | MIT | https://pypi.org/project/genson/ | dev-only; no EOL published locally; Dependabot tracks releases |
| h11 | 0.16.0 | MIT | https://pypi.org/project/h11/ | runtime; 0.x: minor releases may break; no support window recorded |
| idna | 3.20 | BSD-3-Clause | https://pypi.org/project/idna/ | runtime; no EOL published locally; Dependabot tracks releases |
| inflect | 7.5.0 | MIT | https://pypi.org/project/inflect/ | dev-only; no EOL published locally; Dependabot tracks releases |
| iniconfig | 2.3.1 | MIT | https://pypi.org/project/iniconfig/ | dev-only; no EOL published locally; Dependabot tracks releases |
| isort | 8.0.1 | MIT | https://pypi.org/project/isort/ | dev-only; no EOL published locally; Dependabot tracks releases |
| jinja2 | 3.1.6 | BSD | https://pypi.org/project/jinja2/ | dev-only; no EOL published locally; Dependabot tracks releases |
| jsonschema | 4.26.0 | MIT | https://pypi.org/project/jsonschema/ | runtime; no EOL published locally; Dependabot tracks releases |
| jsonschema-specifications | 2025.9.1 | MIT | https://pypi.org/project/jsonschema-specifications/ | runtime; no EOL published locally; Dependabot tracks releases |
| license-expression | 30.4.4 | Apache-2.0 | https://pypi.org/project/license-expression/ | dev-only; no EOL published locally; Dependabot tracks releases |
| markdown-it-py | 4.2.0 | MIT | https://pypi.org/project/markdown-it-py/ | dev-only; no EOL published locally; Dependabot tracks releases |
| markupsafe | 3.0.4 | BSD-3-Clause | https://pypi.org/project/markupsafe/ | dev-only; no EOL published locally; Dependabot tracks releases |
| mdurl | 0.1.2 | MIT | https://pypi.org/project/mdurl/ | dev-only; 0.x: minor releases may break; no support window recorded |
| more-itertools | 11.1.0 | MIT | https://pypi.org/project/more-itertools/ | dev-only; no EOL published locally; Dependabot tracks releases |
| msgpack | 1.2.3 | Apache-2.0 | https://pypi.org/project/msgpack/ | dev-only; no EOL published locally; Dependabot tracks releases |
| mypy-extensions | 1.1.0 | MIT | https://pypi.org/project/mypy-extensions/ | dev-only; no EOL published locally; Dependabot tracks releases |
| neurosphere-api | 0.0.0 | first-party | workspace | first-party |
| neurosphere-contracts | 0.0.0 | first-party | workspace | first-party |
| neurosphere-core | 0.0.0 | first-party | workspace | first-party |
| neurosphere-workers | 0.0.0 | first-party | workspace | first-party |
| neurosphere-workspace | 0.0.0 | first-party | workspace | first-party |
| nodeenv | 1.11.0 | BSD | https://pypi.org/project/nodeenv/ | dev-only; no EOL published locally; Dependabot tracks releases |
| opentelemetry-api | 1.45.1 | Apache-2.0 | https://pypi.org/project/opentelemetry-api/ | runtime; no EOL published locally; Dependabot tracks releases |
| packageurl-python | 0.17.6 | MIT | https://pypi.org/project/packageurl-python/ | dev-only; 0.x: minor releases may break; no support window recorded |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://pypi.org/project/packaging/ | dev-only; no EOL published locally; Dependabot tracks releases |
| pathspec | 1.1.1 | MPL-2.0 | https://pypi.org/project/pathspec/ | dev-only; no EOL published locally; Dependabot tracks releases |
| pip | 26.2.1 | MIT | https://pypi.org/project/pip/ | dev-only; no EOL published locally; Dependabot tracks releases |
| pip-api | 0.0.35 | Apache-2.0 | https://pypi.org/project/pip-api/ | dev-only; 0.x: minor releases may break; no support window recorded |
| pip-audit | 2.10.1 | Apache-2.0 | https://pypi.org/project/pip-audit/ | dev-only; no EOL published locally; Dependabot tracks releases |
| pip-requirements-parser | 32.0.1 | MIT | https://pypi.org/project/pip-requirements-parser/ | dev-only; no EOL published locally; Dependabot tracks releases |
| platformdirs | 4.12.4 | MIT | https://pypi.org/project/platformdirs/ | dev-only; no EOL published locally; Dependabot tracks releases |
| pluggy | 1.6.0 | MIT | https://pypi.org/project/pluggy/ | dev-only; no EOL published locally; Dependabot tracks releases |
| py-serializable | 2.1.0 | Apache-2.0 | https://pypi.org/project/py-serializable/ | dev-only; no EOL published locally; Dependabot tracks releases |
| pydantic | 2.14.0 | MIT | https://pypi.org/project/pydantic/ | runtime; no EOL published locally; Dependabot tracks releases |
| pydantic-core | 2.50.0 | MIT | https://pypi.org/project/pydantic-core/ | runtime; no EOL published locally; Dependabot tracks releases |
| pygments | 2.21.0 | BSD-2-Clause | https://pypi.org/project/pygments/ | dev-only; no EOL published locally; Dependabot tracks releases |
| pyparsing | 3.3.3 | MIT | https://pypi.org/project/pyparsing/ | dev-only; no EOL published locally; Dependabot tracks releases |
| pyright | 1.1.414 | MIT | https://pypi.org/project/pyright/ | dev-only; no EOL published locally; Dependabot tracks releases |
| pytest | 9.1.1 | MIT | https://pypi.org/project/pytest/ | dev-only; no EOL published locally; Dependabot tracks releases |
| pytokens | 0.4.1 | MIT | https://pypi.org/project/pytokens/ | dev-only; 0.x: minor releases may break; no support window recorded |
| pyyaml | 6.0.3 | MIT | https://pypi.org/project/pyyaml/ | dev-only; no EOL published locally; Dependabot tracks releases |
| referencing | 0.37.0 | MIT | https://pypi.org/project/referencing/ | runtime; 0.x: minor releases may break; no support window recorded |
| requests | 2.34.2 | Apache-2.0 | https://pypi.org/project/requests/ | dev-only; no EOL published locally; Dependabot tracks releases |
| rich | 15.0.0 | MIT | https://pypi.org/project/rich/ | dev-only; no EOL published locally; Dependabot tracks releases |
| rpds-py | 2026.9.1 | MIT | https://pypi.org/project/rpds-py/ | runtime; no EOL published locally; Dependabot tracks releases |
| ruff | 0.16.10 | MIT | https://pypi.org/project/ruff/ | dev-only; 0.x: minor releases may break; no support window recorded |
| sortedcontainers | 2.4.0 | Apache-2.0 | https://pypi.org/project/sortedcontainers/ | dev-only; no EOL published locally; Dependabot tracks releases |
| starlette | 1.7.0 | BSD-3-Clause | https://pypi.org/project/starlette/ | runtime; no EOL published locally; Dependabot tracks releases |
| tomli | 2.5.0 | MIT | https://pypi.org/project/tomli/ | dev-only; no EOL published locally; Dependabot tracks releases |
| tomli-w | 1.2.0 | MIT | https://pypi.org/project/tomli-w/ | dev-only; no EOL published locally; Dependabot tracks releases |
| typeguard | 4.6.0 | MIT | https://pypi.org/project/typeguard/ | dev-only; no EOL published locally; Dependabot tracks releases |
| typing-extensions | 4.16.0 | PSF-2.0 | https://pypi.org/project/typing-extensions/ | runtime; no EOL published locally; Dependabot tracks releases |
| typing-inspection | 0.4.4 | MIT | https://pypi.org/project/typing-inspection/ | runtime; 0.x: minor releases may break; no support window recorded |
| urllib3 | 2.8.0 | MIT | https://pypi.org/project/urllib3/ | dev-only; no EOL published locally; Dependabot tracks releases |
| uvicorn | 0.54.0 | BSD-3-Clause | https://pypi.org/project/uvicorn/ | runtime; 0.x: minor releases may break; no support window recorded |

#### npm (pnpm-lock.yaml): 265 packages

| Component | Pin | Licence | Source | Note |
|---|---|---|---|---|
| @apidevtools/json-schema-ref-parser | 11.9.3 | MIT | https://www.npmjs.com/package/@apidevtools/json-schema-ref-parser | dev-only; no EOL published locally; Dependabot tracks releases |
| @babel/runtime | 7.29.10 | MIT | https://www.npmjs.com/package/@babel/runtime | runtime; no EOL published locally; Dependabot tracks releases |
| @cacheable/memory | 2.2.0 | MIT | https://www.npmjs.com/package/@cacheable/memory | dev-only; no EOL published locally; Dependabot tracks releases |
| @cacheable/utils | 2.5.0 | MIT | https://www.npmjs.com/package/@cacheable/utils | dev-only; no EOL published locally; Dependabot tracks releases |
| @emotion/hash | 0.9.2 | MIT | https://www.npmjs.com/package/@emotion/hash | runtime; 0.x: minor releases may break; no support window recorded |
| @eslint-community/eslint-utils | 4.10.1 | MIT | https://www.npmjs.com/package/@eslint-community/eslint-utils | dev-only; no EOL published locally; Dependabot tracks releases |
| @eslint-community/regexpp | 4.12.2 | MIT | https://www.npmjs.com/package/@eslint-community/regexpp | dev-only; no EOL published locally; Dependabot tracks releases |
| @eslint/config-array | 0.23.5 | Apache-2.0 | https://www.npmjs.com/package/@eslint/config-array | dev-only; 0.x: minor releases may break; no support window recorded |
| @eslint/config-helpers | 0.7.0 | Apache-2.0 | https://www.npmjs.com/package/@eslint/config-helpers | dev-only; 0.x: minor releases may break; no support window recorded |
| @eslint/core | 1.2.1 | Apache-2.0 | https://www.npmjs.com/package/@eslint/core | dev-only; no EOL published locally; Dependabot tracks releases |
| @eslint/js | 10.0.1 | MIT | https://www.npmjs.com/package/@eslint/js | dev-only; no EOL published locally; Dependabot tracks releases |
| @eslint/object-schema | 3.0.5 | Apache-2.0 | https://www.npmjs.com/package/@eslint/object-schema | dev-only; no EOL published locally; Dependabot tracks releases |
| @eslint/plugin-kit | 0.7.3 | Apache-2.0 | https://www.npmjs.com/package/@eslint/plugin-kit | dev-only; 0.x: minor releases may break; no support window recorded |
| @floating-ui/core | 1.8.0 | MIT | https://www.npmjs.com/package/@floating-ui/core | runtime; no EOL published locally; Dependabot tracks releases |
| @floating-ui/devtools | 0.2.3 | MIT | https://www.npmjs.com/package/@floating-ui/devtools | runtime; 0.x: minor releases may break; no support window recorded |
| @floating-ui/dom | 1.8.0 | MIT | https://www.npmjs.com/package/@floating-ui/dom | runtime; no EOL published locally; Dependabot tracks releases |
| @floating-ui/utils | 0.2.12 | MIT | https://www.npmjs.com/package/@floating-ui/utils | runtime; 0.x: minor releases may break; no support window recorded |
| @fluentui/keyboard-keys | 9.0.9 | MIT | https://www.npmjs.com/package/@fluentui/keyboard-keys | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/priority-overflow | 9.4.3 | MIT | https://www.npmjs.com/package/@fluentui/priority-overflow | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-accordion | 9.12.4 | MIT | https://www.npmjs.com/package/@fluentui/react-accordion | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-alert | 9.0.2-beta.1 | MIT | https://www.npmjs.com/package/@fluentui/react-alert | runtime; pre-release version; no support window recorded |
| @fluentui/react-aria | 9.17.15 | MIT | https://www.npmjs.com/package/@fluentui/react-aria | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-avatar | 9.11.8 | MIT | https://www.npmjs.com/package/@fluentui/react-avatar | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-badge | 9.5.6 | MIT | https://www.npmjs.com/package/@fluentui/react-badge | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-breadcrumb | 9.4.6 | MIT | https://www.npmjs.com/package/@fluentui/react-breadcrumb | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-button | 9.11.1 | MIT | https://www.npmjs.com/package/@fluentui/react-button | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-card | 9.7.3 | MIT | https://www.npmjs.com/package/@fluentui/react-card | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-carousel | 9.9.14 | MIT | https://www.npmjs.com/package/@fluentui/react-carousel | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-checkbox | 9.6.5 | MIT | https://www.npmjs.com/package/@fluentui/react-checkbox | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-color-picker | 9.3.1 | MIT | https://www.npmjs.com/package/@fluentui/react-color-picker | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-combobox | 9.17.7 | MIT | https://www.npmjs.com/package/@fluentui/react-combobox | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-components | 9.74.9 | MIT | https://www.npmjs.com/package/@fluentui/react-components | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-context-selector | 9.2.20 | MIT | https://www.npmjs.com/package/@fluentui/react-context-selector | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-dialog | 9.18.5 | MIT | https://www.npmjs.com/package/@fluentui/react-dialog | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-divider | 9.7.5 | MIT | https://www.npmjs.com/package/@fluentui/react-divider | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-drawer | 9.13.4 | MIT | https://www.npmjs.com/package/@fluentui/react-drawer | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-field | 9.5.5 | MIT | https://www.npmjs.com/package/@fluentui/react-field | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-icons | 2.0.343 | MIT | https://www.npmjs.com/package/@fluentui/react-icons | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-image | 9.4.5 | MIT | https://www.npmjs.com/package/@fluentui/react-image | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-infobutton | 9.0.1-beta.1 | MIT | https://www.npmjs.com/package/@fluentui/react-infobutton | runtime; pre-release version; no support window recorded |
| @fluentui/react-infolabel | 9.4.27 | MIT | https://www.npmjs.com/package/@fluentui/react-infolabel | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-input | 9.8.7 | MIT | https://www.npmjs.com/package/@fluentui/react-input | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-jsx-runtime | 9.4.6 | MIT | https://www.npmjs.com/package/@fluentui/react-jsx-runtime | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-label | 9.4.5 | MIT | https://www.npmjs.com/package/@fluentui/react-label | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-link | 9.8.5 | MIT | https://www.npmjs.com/package/@fluentui/react-link | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-list | 9.6.19 | MIT | https://www.npmjs.com/package/@fluentui/react-list | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-menu | 9.25.6 | MIT | https://www.npmjs.com/package/@fluentui/react-menu | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-message-bar | 9.7.7 | MIT | https://www.npmjs.com/package/@fluentui/react-message-bar | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-motion | 9.16.4 | MIT | https://www.npmjs.com/package/@fluentui/react-motion | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-motion-components-preview | 0.15.9 | MIT | https://www.npmjs.com/package/@fluentui/react-motion-components-preview | runtime; 0.x: minor releases may break; no support window recorded |
| @fluentui/react-nav | 9.4.7 | MIT | https://www.npmjs.com/package/@fluentui/react-nav | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-overflow | 9.9.4 | MIT | https://www.npmjs.com/package/@fluentui/react-overflow | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-persona | 9.7.10 | MIT | https://www.npmjs.com/package/@fluentui/react-persona | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-popover | 9.14.9 | MIT | https://www.npmjs.com/package/@fluentui/react-popover | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-portal | 9.8.16 | MIT | https://www.npmjs.com/package/@fluentui/react-portal | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-positioning | 9.23.3 | MIT | https://www.npmjs.com/package/@fluentui/react-positioning | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-progress | 9.5.6 | MIT | https://www.npmjs.com/package/@fluentui/react-progress | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-provider | 9.22.21 | MIT | https://www.npmjs.com/package/@fluentui/react-provider | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-radio | 9.6.6 | MIT | https://www.npmjs.com/package/@fluentui/react-radio | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-rating | 9.4.6 | MIT | https://www.npmjs.com/package/@fluentui/react-rating | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-search | 9.4.7 | MIT | https://www.npmjs.com/package/@fluentui/react-search | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-select | 9.5.6 | MIT | https://www.npmjs.com/package/@fluentui/react-select | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-shared-contexts | 9.26.4 | MIT | https://www.npmjs.com/package/@fluentui/react-shared-contexts | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-skeleton | 9.7.6 | MIT | https://www.npmjs.com/package/@fluentui/react-skeleton | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-slider | 9.6.6 | MIT | https://www.npmjs.com/package/@fluentui/react-slider | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-spinbutton | 9.6.7 | MIT | https://www.npmjs.com/package/@fluentui/react-spinbutton | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-spinner | 9.8.6 | MIT | https://www.npmjs.com/package/@fluentui/react-spinner | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-swatch-picker | 9.6.2 | MIT | https://www.npmjs.com/package/@fluentui/react-swatch-picker | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-switch | 9.7.6 | MIT | https://www.npmjs.com/package/@fluentui/react-switch | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-table | 9.19.22 | MIT | https://www.npmjs.com/package/@fluentui/react-table | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-tabs | 9.12.5 | MIT | https://www.npmjs.com/package/@fluentui/react-tabs | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-tabster | 9.26.18 | MIT | https://www.npmjs.com/package/@fluentui/react-tabster | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-tag-picker | 9.10.5 | MIT | https://www.npmjs.com/package/@fluentui/react-tag-picker | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-tags | 9.9.7 | MIT | https://www.npmjs.com/package/@fluentui/react-tags | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-teaching-popover | 9.7.7 | MIT | https://www.npmjs.com/package/@fluentui/react-teaching-popover | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-text | 9.6.20 | MIT | https://www.npmjs.com/package/@fluentui/react-text | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-textarea | 9.7.7 | MIT | https://www.npmjs.com/package/@fluentui/react-textarea | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-theme | 9.2.2 | MIT | https://www.npmjs.com/package/@fluentui/react-theme | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-toast | 9.8.4 | MIT | https://www.npmjs.com/package/@fluentui/react-toast | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-toolbar | 9.8.5 | MIT | https://www.npmjs.com/package/@fluentui/react-toolbar | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-tooltip | 9.10.7 | MIT | https://www.npmjs.com/package/@fluentui/react-tooltip | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-tree | 9.16.8 | MIT | https://www.npmjs.com/package/@fluentui/react-tree | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-utilities | 9.26.7 | MIT | https://www.npmjs.com/package/@fluentui/react-utilities | runtime; no EOL published locally; Dependabot tracks releases |
| @fluentui/react-virtualizer | 9.0.0-alpha.116 | MIT | https://www.npmjs.com/package/@fluentui/react-virtualizer | runtime; pre-release version; no support window recorded |
| @fluentui/tokens | 1.0.0-alpha.24 | MIT | https://www.npmjs.com/package/@fluentui/tokens | runtime; pre-release version; no support window recorded |
| @griffel/core | 1.21.4 | MIT | https://www.npmjs.com/package/@griffel/core | runtime; no EOL published locally; Dependabot tracks releases |
| @griffel/react | 1.7.8 | MIT | https://www.npmjs.com/package/@griffel/react | runtime; no EOL published locally; Dependabot tracks releases |
| @griffel/style-types | 1.4.3 | MIT | https://www.npmjs.com/package/@griffel/style-types | runtime; no EOL published locally; Dependabot tracks releases |
| @humanfs/core | 0.19.2 | Apache-2.0 | https://www.npmjs.com/package/@humanfs/core | dev-only; 0.x: minor releases may break; no support window recorded |
| @humanfs/node | 0.16.8 | Apache-2.0 | https://www.npmjs.com/package/@humanfs/node | dev-only; 0.x: minor releases may break; no support window recorded |
| @humanfs/types | 0.15.0 | Apache-2.0 | https://www.npmjs.com/package/@humanfs/types | dev-only; 0.x: minor releases may break; no support window recorded |
| @humanwhocodes/module-importer | 1.0.1 | Apache-2.0 | https://www.npmjs.com/package/@humanwhocodes/module-importer | dev-only; no EOL published locally; Dependabot tracks releases |
| @humanwhocodes/retry | 0.4.3 | Apache-2.0 | https://www.npmjs.com/package/@humanwhocodes/retry | dev-only; 0.x: minor releases may break; no support window recorded |
| @jridgewell/sourcemap-codec | 1.6.0 | MIT | https://www.npmjs.com/package/@jridgewell/sourcemap-codec | dev-only; no EOL published locally; Dependabot tracks releases |
| @jsdevtools/ono | 7.1.3 | MIT | https://www.npmjs.com/package/@jsdevtools/ono | dev-only; no EOL published locally; Dependabot tracks releases |
| @keyv/bigmap | 1.3.1 | MIT | https://www.npmjs.com/package/@keyv/bigmap | dev-only; no EOL published locally; Dependabot tracks releases |
| @keyv/serialize | 1.1.1 | MIT | https://www.npmjs.com/package/@keyv/serialize | dev-only; no EOL published locally; Dependabot tracks releases |
| @oxc-project/types | 0.153.0 | MIT | https://www.npmjs.com/package/@oxc-project/types | dev-only; 0.x: minor releases may break; no support window recorded |
| @rolldown/binding-android-arm-eabi | 1.2.13 | MIT | https://www.npmjs.com/package/@rolldown/binding-android-arm-eabi | dev-only; no EOL published locally; Dependabot tracks releases |
| @rolldown/binding-android-arm64 | 1.2.13 | MIT | https://www.npmjs.com/package/@rolldown/binding-android-arm64 | dev-only; no EOL published locally; Dependabot tracks releases |
| @rolldown/binding-darwin-arm64 | 1.2.13 | MIT | https://www.npmjs.com/package/@rolldown/binding-darwin-arm64 | dev-only; no EOL published locally; Dependabot tracks releases |
| @rolldown/binding-darwin-x64 | 1.2.13 | MIT | https://www.npmjs.com/package/@rolldown/binding-darwin-x64 | dev-only; no EOL published locally; Dependabot tracks releases |
| @rolldown/binding-freebsd-x64 | 1.2.13 | MIT | https://www.npmjs.com/package/@rolldown/binding-freebsd-x64 | dev-only; no EOL published locally; Dependabot tracks releases |
| @rolldown/binding-linux-arm-gnueabihf | 1.2.13 | MIT | https://www.npmjs.com/package/@rolldown/binding-linux-arm-gnueabihf | dev-only; no EOL published locally; Dependabot tracks releases |
| @rolldown/binding-linux-arm64-gnu | 1.2.13 | MIT | https://www.npmjs.com/package/@rolldown/binding-linux-arm64-gnu | dev-only; no EOL published locally; Dependabot tracks releases |
| @rolldown/binding-linux-arm64-musl | 1.2.13 | MIT | https://www.npmjs.com/package/@rolldown/binding-linux-arm64-musl | dev-only; no EOL published locally; Dependabot tracks releases |
| @rolldown/binding-linux-ppc64-gnu | 1.2.13 | MIT | https://www.npmjs.com/package/@rolldown/binding-linux-ppc64-gnu | dev-only; no EOL published locally; Dependabot tracks releases |
| @rolldown/binding-linux-s390x-gnu | 1.2.13 | MIT | https://www.npmjs.com/package/@rolldown/binding-linux-s390x-gnu | dev-only; no EOL published locally; Dependabot tracks releases |
| @rolldown/binding-linux-x64-gnu | 1.2.13 | MIT | https://www.npmjs.com/package/@rolldown/binding-linux-x64-gnu | dev-only; no EOL published locally; Dependabot tracks releases |
| @rolldown/binding-linux-x64-musl | 1.2.13 | MIT | https://www.npmjs.com/package/@rolldown/binding-linux-x64-musl | dev-only; no EOL published locally; Dependabot tracks releases |
| @rolldown/binding-openharmony-arm64 | 1.2.13 | MIT | https://www.npmjs.com/package/@rolldown/binding-openharmony-arm64 | dev-only; no EOL published locally; Dependabot tracks releases |
| @rolldown/binding-win32-arm64-msvc | 1.2.13 | MIT | https://www.npmjs.com/package/@rolldown/binding-win32-arm64-msvc | dev-only; no EOL published locally; Dependabot tracks releases |
| @rolldown/binding-win32-x64-msvc | 1.2.13 | MIT | https://www.npmjs.com/package/@rolldown/binding-win32-x64-msvc | dev-only; no EOL published locally; Dependabot tracks releases |
| @rolldown/pluginutils | 1.0.1 | MIT | https://www.npmjs.com/package/@rolldown/pluginutils | dev-only; no EOL published locally; Dependabot tracks releases |
| @standard-schema/spec | 1.1.0 | MIT | https://www.npmjs.com/package/@standard-schema/spec | dev-only; no EOL published locally; Dependabot tracks releases |
| @swc/helpers | 0.5.23 | Apache-2.0 | https://www.npmjs.com/package/@swc/helpers | runtime; 0.x: minor releases may break; no support window recorded |
| @types/chai | 5.2.3 | MIT | https://www.npmjs.com/package/@types/chai | dev-only; no EOL published locally; Dependabot tracks releases |
| @types/deep-eql | 4.0.2 | MIT | https://www.npmjs.com/package/@types/deep-eql | dev-only; no EOL published locally; Dependabot tracks releases |
| @types/esrecurse | 4.3.1 | MIT | https://www.npmjs.com/package/@types/esrecurse | dev-only; no EOL published locally; Dependabot tracks releases |
| @types/estree | 1.0.9 | MIT | https://www.npmjs.com/package/@types/estree | dev-only; no EOL published locally; Dependabot tracks releases |
| @types/json-schema | 7.0.15 | MIT | https://www.npmjs.com/package/@types/json-schema | dev-only; no EOL published locally; Dependabot tracks releases |
| @types/lodash | 4.17.25 | MIT | https://www.npmjs.com/package/@types/lodash | dev-only; no EOL published locally; Dependabot tracks releases |
| @types/react | 19.3.0 | MIT | https://www.npmjs.com/package/@types/react | runtime; no EOL published locally; Dependabot tracks releases |
| @types/react-dom | 19.3.0 | MIT | https://www.npmjs.com/package/@types/react-dom | dev-only; no EOL published locally; Dependabot tracks releases |
| @typescript-eslint/eslint-plugin | 8.71.1 | MIT | https://www.npmjs.com/package/@typescript-eslint/eslint-plugin | dev-only; no EOL published locally; Dependabot tracks releases |
| @typescript-eslint/parser | 8.71.1 | MIT | https://www.npmjs.com/package/@typescript-eslint/parser | dev-only; no EOL published locally; Dependabot tracks releases |
| @typescript-eslint/project-service | 8.71.1 | MIT | https://www.npmjs.com/package/@typescript-eslint/project-service | dev-only; no EOL published locally; Dependabot tracks releases |
| @typescript-eslint/scope-manager | 8.71.1 | MIT | https://www.npmjs.com/package/@typescript-eslint/scope-manager | dev-only; no EOL published locally; Dependabot tracks releases |
| @typescript-eslint/tsconfig-utils | 8.71.1 | MIT | https://www.npmjs.com/package/@typescript-eslint/tsconfig-utils | dev-only; no EOL published locally; Dependabot tracks releases |
| @typescript-eslint/type-utils | 8.71.1 | MIT | https://www.npmjs.com/package/@typescript-eslint/type-utils | dev-only; no EOL published locally; Dependabot tracks releases |
| @typescript-eslint/types | 8.71.1 | MIT | https://www.npmjs.com/package/@typescript-eslint/types | dev-only; no EOL published locally; Dependabot tracks releases |
| @typescript-eslint/typescript-estree | 8.71.1 | MIT | https://www.npmjs.com/package/@typescript-eslint/typescript-estree | dev-only; no EOL published locally; Dependabot tracks releases |
| @typescript-eslint/utils | 8.71.1 | MIT | https://www.npmjs.com/package/@typescript-eslint/utils | dev-only; no EOL published locally; Dependabot tracks releases |
| @typescript-eslint/visitor-keys | 8.71.1 | MIT | https://www.npmjs.com/package/@typescript-eslint/visitor-keys | dev-only; no EOL published locally; Dependabot tracks releases |
| @vitest/expect | 4.1.11 | MIT | https://www.npmjs.com/package/@vitest/expect | dev-only; no EOL published locally; Dependabot tracks releases |
| @vitest/mocker | 4.1.11 | MIT | https://www.npmjs.com/package/@vitest/mocker | dev-only; no EOL published locally; Dependabot tracks releases |
| @vitest/pretty-format | 4.1.11 | MIT | https://www.npmjs.com/package/@vitest/pretty-format | dev-only; no EOL published locally; Dependabot tracks releases |
| @vitest/runner | 4.1.11 | MIT | https://www.npmjs.com/package/@vitest/runner | dev-only; no EOL published locally; Dependabot tracks releases |
| @vitest/snapshot | 4.1.11 | MIT | https://www.npmjs.com/package/@vitest/snapshot | dev-only; no EOL published locally; Dependabot tracks releases |
| @vitest/spy | 4.1.11 | MIT | https://www.npmjs.com/package/@vitest/spy | dev-only; no EOL published locally; Dependabot tracks releases |
| @vitest/utils | 4.1.11 | MIT | https://www.npmjs.com/package/@vitest/utils | dev-only; no EOL published locally; Dependabot tracks releases |
| acorn | 8.19.0 | MIT | https://www.npmjs.com/package/acorn | dev-only; no EOL published locally; Dependabot tracks releases |
| acorn-jsx | 5.3.2 | MIT | https://www.npmjs.com/package/acorn-jsx | dev-only; no EOL published locally; Dependabot tracks releases |
| ajv | 6.15.0 | MIT | https://www.npmjs.com/package/ajv | dev-only; no EOL published locally; Dependabot tracks releases |
| argparse | 2.0.1 | Python-2.0 | https://www.npmjs.com/package/argparse | dev-only; no EOL published locally; Dependabot tracks releases |
| assertion-error | 2.0.1 | MIT | https://www.npmjs.com/package/assertion-error | dev-only; no EOL published locally; Dependabot tracks releases |
| balanced-match | 4.0.4 | MIT | https://www.npmjs.com/package/balanced-match | dev-only; no EOL published locally; Dependabot tracks releases |
| brace-expansion | 5.0.12 | MIT | https://www.npmjs.com/package/brace-expansion | dev-only; no EOL published locally; Dependabot tracks releases |
| cacheable | 2.5.0 | MIT | https://www.npmjs.com/package/cacheable | dev-only; no EOL published locally; Dependabot tracks releases |
| chai | 6.3.0 | MIT | https://www.npmjs.com/package/chai | dev-only; no EOL published locally; Dependabot tracks releases |
| convert-source-map | 2.0.0 | MIT | https://www.npmjs.com/package/convert-source-map | dev-only; no EOL published locally; Dependabot tracks releases |
| cross-spawn | 7.0.6 | MIT | https://www.npmjs.com/package/cross-spawn | dev-only; no EOL published locally; Dependabot tracks releases |
| csstype | 3.2.3 | MIT | https://www.npmjs.com/package/csstype | runtime; no EOL published locally; Dependabot tracks releases |
| debug | 4.4.3 | MIT | https://www.npmjs.com/package/debug | dev-only; no EOL published locally; Dependabot tracks releases |
| deep-is | 0.1.4 | MIT | https://www.npmjs.com/package/deep-is | dev-only; 0.x: minor releases may break; no support window recorded |
| detect-libc | 2.1.2 | Apache-2.0 | https://www.npmjs.com/package/detect-libc | dev-only; no EOL published locally; Dependabot tracks releases |
| embla-carousel | 8.6.0 | MIT | https://www.npmjs.com/package/embla-carousel | runtime; no EOL published locally; Dependabot tracks releases |
| embla-carousel-autoplay | 8.6.0 | MIT | https://www.npmjs.com/package/embla-carousel-autoplay | runtime; no EOL published locally; Dependabot tracks releases |
| embla-carousel-fade | 8.6.0 | MIT | https://www.npmjs.com/package/embla-carousel-fade | runtime; no EOL published locally; Dependabot tracks releases |
| es-module-lexer | 2.3.2 | MIT | https://www.npmjs.com/package/es-module-lexer | dev-only; no EOL published locally; Dependabot tracks releases |
| escape-string-regexp | 4.0.0 | MIT | https://www.npmjs.com/package/escape-string-regexp | dev-only; no EOL published locally; Dependabot tracks releases |
| eslint | 10.12.0 | MIT | https://www.npmjs.com/package/eslint | dev-only; no EOL published locally; Dependabot tracks releases |
| eslint-scope | 9.1.2 | BSD-2-Clause | https://www.npmjs.com/package/eslint-scope | dev-only; no EOL published locally; Dependabot tracks releases |
| eslint-visitor-keys | 3.4.3 | Apache-2.0 | https://www.npmjs.com/package/eslint-visitor-keys | dev-only; no EOL published locally; Dependabot tracks releases |
| eslint-visitor-keys | 5.0.1 | Apache-2.0 | https://www.npmjs.com/package/eslint-visitor-keys | dev-only; no EOL published locally; Dependabot tracks releases |
| espree | 11.2.0 | BSD-2-Clause | https://www.npmjs.com/package/espree | dev-only; no EOL published locally; Dependabot tracks releases |
| esquery | 1.7.0 | BSD-3-Clause | https://www.npmjs.com/package/esquery | dev-only; no EOL published locally; Dependabot tracks releases |
| esrecurse | 4.3.0 | BSD-2-Clause | https://www.npmjs.com/package/esrecurse | dev-only; no EOL published locally; Dependabot tracks releases |
| estraverse | 5.3.0 | BSD-2-Clause | https://www.npmjs.com/package/estraverse | dev-only; no EOL published locally; Dependabot tracks releases |
| estree-walker | 3.0.3 | MIT | https://www.npmjs.com/package/estree-walker | dev-only; no EOL published locally; Dependabot tracks releases |
| esutils | 2.0.3 | BSD-2-Clause | https://www.npmjs.com/package/esutils | dev-only; no EOL published locally; Dependabot tracks releases |
| expect-type | 1.4.0 | Apache-2.0 | https://www.npmjs.com/package/expect-type | dev-only; no EOL published locally; Dependabot tracks releases |
| fast-deep-equal | 3.1.3 | MIT | https://www.npmjs.com/package/fast-deep-equal | dev-only; no EOL published locally; Dependabot tracks releases |
| fast-json-stable-stringify | 2.1.0 | MIT | https://www.npmjs.com/package/fast-json-stable-stringify | dev-only; no EOL published locally; Dependabot tracks releases |
| fast-levenshtein | 2.0.6 | MIT | https://www.npmjs.com/package/fast-levenshtein | dev-only; no EOL published locally; Dependabot tracks releases |
| fdir | 6.5.0 | MIT | https://www.npmjs.com/package/fdir | dev-only; no EOL published locally; Dependabot tracks releases |
| file-entry-cache | 11.1.5 | MIT | https://www.npmjs.com/package/file-entry-cache | dev-only; no EOL published locally; Dependabot tracks releases |
| find-up | 5.0.0 | MIT | https://www.npmjs.com/package/find-up | dev-only; no EOL published locally; Dependabot tracks releases |
| flat-cache | 6.1.23 | MIT | https://www.npmjs.com/package/flat-cache | dev-only; no EOL published locally; Dependabot tracks releases |
| flatted | 3.4.4 | ISC | https://www.npmjs.com/package/flatted | dev-only; no EOL published locally; Dependabot tracks releases |
| fsevents | 2.3.3 | MIT | https://www.npmjs.com/package/fsevents | dev-only; no EOL published locally; Dependabot tracks releases |
| glob-parent | 6.0.2 | ISC | https://www.npmjs.com/package/glob-parent | dev-only; no EOL published locally; Dependabot tracks releases |
| hashery | 1.5.1 | MIT | https://www.npmjs.com/package/hashery | dev-only; no EOL published locally; Dependabot tracks releases |
| hookified | 1.15.1 | MIT | https://www.npmjs.com/package/hookified | dev-only; no EOL published locally; Dependabot tracks releases |
| hookified | 2.2.0 | MIT | https://www.npmjs.com/package/hookified | dev-only; no EOL published locally; Dependabot tracks releases |
| ignore | 5.3.2 | MIT | https://www.npmjs.com/package/ignore | dev-only; no EOL published locally; Dependabot tracks releases |
| ignore | 7.0.12 | MIT | https://www.npmjs.com/package/ignore | dev-only; no EOL published locally; Dependabot tracks releases |
| imurmurhash | 0.1.4 | MIT | https://www.npmjs.com/package/imurmurhash | dev-only; 0.x: minor releases may break; no support window recorded |
| is-extglob | 2.1.1 | MIT | https://www.npmjs.com/package/is-extglob | dev-only; no EOL published locally; Dependabot tracks releases |
| is-glob | 4.0.3 | MIT | https://www.npmjs.com/package/is-glob | dev-only; no EOL published locally; Dependabot tracks releases |
| isexe | 2.0.0 | ISC | https://www.npmjs.com/package/isexe | dev-only; no EOL published locally; Dependabot tracks releases |
| js-yaml | 4.3.2 | MIT | https://www.npmjs.com/package/js-yaml | dev-only; no EOL published locally; Dependabot tracks releases |
| js-yaml | 5.4.3 | MIT | https://www.npmjs.com/package/js-yaml | dev-only; no EOL published locally; Dependabot tracks releases |
| json-schema-to-typescript | 16.0.0 | MIT | https://www.npmjs.com/package/json-schema-to-typescript | dev-only; no EOL published locally; Dependabot tracks releases |
| json-schema-traverse | 0.4.1 | MIT | https://www.npmjs.com/package/json-schema-traverse | dev-only; 0.x: minor releases may break; no support window recorded |
| json-stable-stringify-without-jsonify | 1.0.1 | MIT | https://www.npmjs.com/package/json-stable-stringify-without-jsonify | dev-only; no EOL published locally; Dependabot tracks releases |
| keyborg | 2.14.1 | MIT | https://www.npmjs.com/package/keyborg | runtime; no EOL published locally; Dependabot tracks releases |
| keyborg | 3.498.0 | MIT | https://www.npmjs.com/package/keyborg | runtime; no EOL published locally; Dependabot tracks releases |
| keyv | 5.6.0 | MIT | https://www.npmjs.com/package/keyv | dev-only; no EOL published locally; Dependabot tracks releases |
| levn | 0.4.1 | MIT | https://www.npmjs.com/package/levn | dev-only; 0.x: minor releases may break; no support window recorded |
| lightningcss | 1.33.0 | MPL-2.0 | https://www.npmjs.com/package/lightningcss | dev-only; no EOL published locally; Dependabot tracks releases |
| lightningcss-android-arm64 | 1.33.0 | MPL-2.0 | https://www.npmjs.com/package/lightningcss-android-arm64 | dev-only; no EOL published locally; Dependabot tracks releases |
| lightningcss-darwin-arm64 | 1.33.0 | MPL-2.0 | https://www.npmjs.com/package/lightningcss-darwin-arm64 | dev-only; no EOL published locally; Dependabot tracks releases |
| lightningcss-darwin-x64 | 1.33.0 | MPL-2.0 | https://www.npmjs.com/package/lightningcss-darwin-x64 | dev-only; no EOL published locally; Dependabot tracks releases |
| lightningcss-freebsd-x64 | 1.33.0 | MPL-2.0 | https://www.npmjs.com/package/lightningcss-freebsd-x64 | dev-only; no EOL published locally; Dependabot tracks releases |
| lightningcss-linux-arm-gnueabihf | 1.33.0 | MPL-2.0 | https://www.npmjs.com/package/lightningcss-linux-arm-gnueabihf | dev-only; no EOL published locally; Dependabot tracks releases |
| lightningcss-linux-arm64-gnu | 1.33.0 | MPL-2.0 | https://www.npmjs.com/package/lightningcss-linux-arm64-gnu | dev-only; no EOL published locally; Dependabot tracks releases |
| lightningcss-linux-arm64-musl | 1.33.0 | MPL-2.0 | https://www.npmjs.com/package/lightningcss-linux-arm64-musl | dev-only; no EOL published locally; Dependabot tracks releases |
| lightningcss-linux-x64-gnu | 1.33.0 | MPL-2.0 | https://www.npmjs.com/package/lightningcss-linux-x64-gnu | dev-only; no EOL published locally; Dependabot tracks releases |
| lightningcss-linux-x64-musl | 1.33.0 | MPL-2.0 | https://www.npmjs.com/package/lightningcss-linux-x64-musl | dev-only; no EOL published locally; Dependabot tracks releases |
| lightningcss-win32-arm64-msvc | 1.33.0 | MPL-2.0 | https://www.npmjs.com/package/lightningcss-win32-arm64-msvc | dev-only; no EOL published locally; Dependabot tracks releases |
| lightningcss-win32-x64-msvc | 1.33.0 | MPL-2.0 | https://www.npmjs.com/package/lightningcss-win32-x64-msvc | dev-only; no EOL published locally; Dependabot tracks releases |
| locate-path | 6.0.0 | MIT | https://www.npmjs.com/package/locate-path | dev-only; no EOL published locally; Dependabot tracks releases |
| lodash | 4.18.1 | MIT | https://www.npmjs.com/package/lodash | dev-only; no EOL published locally; Dependabot tracks releases |
| magic-string | 0.30.21 | MIT | https://www.npmjs.com/package/magic-string | dev-only; 0.x: minor releases may break; no support window recorded |
| minimatch | 10.2.6 | BlueOak-1.0.0 | https://www.npmjs.com/package/minimatch | dev-only; no EOL published locally; Dependabot tracks releases |
| minimist | 1.2.8 | MIT | https://www.npmjs.com/package/minimist | dev-only; no EOL published locally; Dependabot tracks releases |
| ms | 2.1.3 | MIT | https://www.npmjs.com/package/ms | dev-only; no EOL published locally; Dependabot tracks releases |
| nanoid | 3.3.20 | MIT | https://www.npmjs.com/package/nanoid | dev-only; no EOL published locally; Dependabot tracks releases |
| natural-compare | 1.4.0 | MIT | https://www.npmjs.com/package/natural-compare | dev-only; no EOL published locally; Dependabot tracks releases |
| obug | 2.2.1 | MIT | https://www.npmjs.com/package/obug | dev-only; no EOL published locally; Dependabot tracks releases |
| optionator | 0.9.4 | MIT | https://www.npmjs.com/package/optionator | dev-only; 0.x: minor releases may break; no support window recorded |
| p-limit | 3.1.0 | MIT | https://www.npmjs.com/package/p-limit | dev-only; no EOL published locally; Dependabot tracks releases |
| p-locate | 5.0.0 | MIT | https://www.npmjs.com/package/p-locate | dev-only; no EOL published locally; Dependabot tracks releases |
| path-exists | 4.0.0 | MIT | https://www.npmjs.com/package/path-exists | dev-only; no EOL published locally; Dependabot tracks releases |
| path-key | 3.1.1 | MIT | https://www.npmjs.com/package/path-key | dev-only; no EOL published locally; Dependabot tracks releases |
| pathe | 2.0.3 | MIT | https://www.npmjs.com/package/pathe | dev-only; no EOL published locally; Dependabot tracks releases |
| picocolors | 1.1.1 | ISC | https://www.npmjs.com/package/picocolors | dev-only; no EOL published locally; Dependabot tracks releases |
| picomatch | 4.0.7 | MIT | https://www.npmjs.com/package/picomatch | dev-only; no EOL published locally; Dependabot tracks releases |
| postcss | 8.5.29 | MIT | https://www.npmjs.com/package/postcss | dev-only; no EOL published locally; Dependabot tracks releases |
| prelude-ls | 1.2.1 | MIT | https://www.npmjs.com/package/prelude-ls | dev-only; no EOL published locally; Dependabot tracks releases |
| prettier | 3.9.9 | MIT | https://www.npmjs.com/package/prettier | dev-only; no EOL published locally; Dependabot tracks releases |
| punycode | 2.3.1 | MIT | https://www.npmjs.com/package/punycode | dev-only; no EOL published locally; Dependabot tracks releases |
| qified | 0.10.1 | MIT | https://www.npmjs.com/package/qified | dev-only; 0.x: minor releases may break; no support window recorded |
| react | 19.3.0 | MIT | https://www.npmjs.com/package/react | runtime; no EOL published locally; Dependabot tracks releases |
| react-dom | 19.3.0 | MIT | https://www.npmjs.com/package/react-dom | runtime; no EOL published locally; Dependabot tracks releases |
| rolldown | 1.2.13 | MIT | https://www.npmjs.com/package/rolldown | dev-only; no EOL published locally; Dependabot tracks releases |
| rtl-css-js | 1.16.1 | MIT | https://www.npmjs.com/package/rtl-css-js | runtime; no EOL published locally; Dependabot tracks releases |
| scheduler | 0.28.0 | MIT | https://www.npmjs.com/package/scheduler | runtime; 0.x: minor releases may break; no support window recorded |
| semver | 7.8.5 | ISC | https://www.npmjs.com/package/semver | dev-only; no EOL published locally; Dependabot tracks releases |
| shebang-command | 2.0.0 | MIT | https://www.npmjs.com/package/shebang-command | dev-only; no EOL published locally; Dependabot tracks releases |
| shebang-regex | 3.0.0 | MIT | https://www.npmjs.com/package/shebang-regex | dev-only; no EOL published locally; Dependabot tracks releases |
| siginfo | 2.0.0 | ISC | https://www.npmjs.com/package/siginfo | dev-only; no EOL published locally; Dependabot tracks releases |
| source-map-js | 1.2.2 | BSD-3-Clause | https://www.npmjs.com/package/source-map-js | dev-only; no EOL published locally; Dependabot tracks releases |
| stackback | 0.0.2 | MIT | https://www.npmjs.com/package/stackback | dev-only; 0.x: minor releases may break; no support window recorded |
| std-env | 4.3.0 | MIT | https://www.npmjs.com/package/std-env | dev-only; no EOL published locally; Dependabot tracks releases |
| stylis | 4.4.0 | MIT | https://www.npmjs.com/package/stylis | runtime; no EOL published locally; Dependabot tracks releases |
| tabster | 8.8.1 | MIT | https://www.npmjs.com/package/tabster | runtime; no EOL published locally; Dependabot tracks releases |
| tinybench | 2.9.0 | MIT | https://www.npmjs.com/package/tinybench | dev-only; no EOL published locally; Dependabot tracks releases |
| tinyexec | 1.3.1 | MIT | https://www.npmjs.com/package/tinyexec | dev-only; no EOL published locally; Dependabot tracks releases |
| tinyglobby | 0.2.17 | MIT | https://www.npmjs.com/package/tinyglobby | dev-only; 0.x: minor releases may break; no support window recorded |
| tinyrainbow | 3.2.0 | MIT | https://www.npmjs.com/package/tinyrainbow | dev-only; no EOL published locally; Dependabot tracks releases |
| ts-api-utils | 2.5.0 | MIT | https://www.npmjs.com/package/ts-api-utils | dev-only; no EOL published locally; Dependabot tracks releases |
| tslib | 2.8.1 | 0BSD | https://www.npmjs.com/package/tslib | runtime; no EOL published locally; Dependabot tracks releases |
| type-check | 0.4.0 | MIT | https://www.npmjs.com/package/type-check | dev-only; 0.x: minor releases may break; no support window recorded |
| typescript | 6.0.3 | Apache-2.0 | https://www.npmjs.com/package/typescript | dev-only; pinned 6.0.x; TS 7 incompatible with typescript-eslint (ADR-0002) |
| typescript-eslint | 8.71.1 | MIT | https://www.npmjs.com/package/typescript-eslint | dev-only; no EOL published locally; Dependabot tracks releases |
| uri-js | 4.4.1 | BSD-2-Clause | https://www.npmjs.com/package/uri-js | dev-only; no EOL published locally; Dependabot tracks releases |
| use-sync-external-store | 1.7.0 | MIT | https://www.npmjs.com/package/use-sync-external-store | runtime; no EOL published locally; Dependabot tracks releases |
| vite | 8.3.3 | MIT | https://www.npmjs.com/package/vite | dev-only; no EOL published locally; Dependabot tracks releases |
| vitest | 4.1.11 | MIT | https://www.npmjs.com/package/vitest | dev-only; no EOL published locally; Dependabot tracks releases |
| which | 2.0.2 | ISC | https://www.npmjs.com/package/which | dev-only; no EOL published locally; Dependabot tracks releases |
| why-is-node-running | 2.3.0 | MIT | https://www.npmjs.com/package/why-is-node-running | dev-only; no EOL published locally; Dependabot tracks releases |
| word-wrap | 1.2.5 | MIT | https://www.npmjs.com/package/word-wrap | dev-only; no EOL published locally; Dependabot tracks releases |
| yocto-queue | 0.1.0 | MIT | https://www.npmjs.com/package/yocto-queue | dev-only; 0.x: minor releases may break; no support window recorded |

<!-- END licences-register -->

### Appendix B: runtime tooling that is not a lockfile dependency

| Component | Pin | Licence | Source | Note |
|---|---|---|---|---|
| Cosmos DB vNext emulator image | `mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator:vnext-latest` | Microsoft EULA | https://learn.microsoft.com/azure/cosmos-db/emulator-linux | EULA image, local development only; pulled by `docker compose`, never redistributed or deployed |
| Event Hubs emulator image | `mcr.microsoft.com/azure-messaging/eventhubs-emulator:latest` | Microsoft EULA (`ACCEPT_EULA=Y`) | https://learn.microsoft.com/azure/event-hubs/overview-emulator | EULA image, local development only; `ACCEPT_EULA=Y` is the operator's acceptance |
| Azurite image | `mcr.microsoft.com/azure-storage/azurite:latest` | MIT | https://learn.microsoft.com/azure/storage/common/storage-use-azurite | required by the Event Hubs emulator |
| @mermaid-js/mermaid-cli | 12.0.0 (`scripts/render_mermaid.py`, run through `pnpm dlx`) | MIT | https://www.npmjs.com/package/@mermaid-js/mermaid-cli | not in `pnpm-lock.yaml` (fetched at run time); renders the `docs/ARCHITECTURE.md` diagrams |
| Chromium (headless) | whatever puppeteer downloads for mermaid-cli 12.0.0 | BSD-3-Clause (Chromium project; bundled third-party components carry their own licences) | https://www.chromium.org/chromium-projects/ | downloaded by puppeteer on the rendering machine; not committed or redistributed. Not verified from local metadata: confirm before any redistribution |

No Fabric, Synapse or Databricks component is a dependency of this repository.
