---
name: PRP-80-copilot-docs-retrieval-and-groundedness
status: backlog
priority: P1
order: 73
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 7
ns: NS-06
depends_on: [PRP-78-copilot-graph-timeline-and-recommender-tools, PRP-60-search-indexing-hardening]
wave: W23
branch: prp-80-copilot-docs-retrieval
allow_parallel: true
issues: []
---

# PRP-80: Copilot docs retrieval, telemetry summaries and the groundedness set

## Goal
Add the retrieval half of the original copilot: a `search_docs` tool that retrieves, scope-first and lexically, from three sources (the published product documentation, catalog descriptions through the existing authorized search, and per-domain telemetry summaries built from hour and day aggregates) and returns cited passages; a 100-question operator groundedness set with a programmatic judge that runs offline on recorded streams in CI and, operator-gated, against a real model; and Helm values that let a cluster deployment configure the copilot. It is for the operations lead who asks "how do I register a producer?" or "which agents had errors yesterday?" and for the owner who wants the original Phase 3 exit measured instead of assumed. It runs in W23 after PRP-78 (copilot registry, tool wiring module, recorded demo adapter) and PRP-60 (catalog search on Azure AI Search fixed).

Out of scope: graph, timeline and recommender tools, tool-call audit and progress events (PRP-78); a vector or semantic ranking mode (optional later step, clarification 2); the first live model turn and the live groundedness run itself (operator-gated, PRP-64); putting the built docs site into the hosted API image (Dockerfiles are Tier 1; follow-up, see item 8); the public docs assistant (`services/docs-assistant`, unchanged and still separate).

## Why
- Restores original 5e (`git show 9fbf5f4c:docs/PRD.md`): "Conversational interface using retrieval-augmented generation (RAG) over the graph and a vector store of documentation/telemetry summaries", with the criterion "Every factual claim in a copilot answer is grounded in a graph query result or telemetry record, shown as an inline citation/reference" and "Falls back to 'I don't have enough information' rather than hallucinating when retrieval is empty."
- Restores the original Phase 3 exit (`git show 9fbf5f4c:PRP.md`, line 121): "Copilot answers a benchmark set of 100 operator questions with >90% groundedness pass rate; no hallucinated answers in eval set." No copilot groundedness harness exists; the evaluation registry has a `groundedness` dimension (`packages/core/neurosphere_core/evaluation/registry/models.py:48`) but nothing exercises the copilot with it.
- The v1.2 line that removed the store: `PRP.md:14` "Qdrant/Pinecone are historical alternatives, not required GA dependencies." Read with gap analysis section 5 item 3, the capability is restored lexically on what exists: `AuthorizedSearch` (`packages/core/neurosphere_core/search/protocol.py:84`) and `GraphQuery.search` on `app.state.catalog_graph`.
- The copilot imports nothing from `neurosphere_core/search/`; the only docs retrieval is `services/docs-assistant`, which by design "shares nothing with the product" (`services/docs-assistant/README.md`), so the in-product copilot cannot answer how-to questions.
- Helm has no copilot values at all (`infra/helm/values.yaml` has `search:` at line 110 and no `copilot:` block), so a cluster deployment cannot even set `NS_COPILOT_MODE`.
- `docs/PRD.md:50` keeps the "Copilot first token <=3s" target; groundedness evidence on a real model is what makes that number meaningful, and it is OPEN today (PRP-19 completion note: "The live copilot model run is OPEN").

## Acceptance criteria
- [ ] Given `NS_COPILOT_DOCS_DIR` pointing at a built docs site (`mkdocs build --site-dir temp/site`), When the model calls `search_docs {term: "register a producer", sources: ["product_docs"]}`, Then the top passages come from the published runbook pages, each cited with kind `document`, a docs URL and the corpus build time; only `*.html` inside the directory are read (symlinks skipped), and the corpus is capped (5000 chunks, 20 MB).
- [ ] Given no `NS_COPILOT_DOCS_DIR`, the `product_docs` source is reported unavailable (`sections_omitted` reason `docs_corpus_unconfigured`) and the tool still serves the other sources; `/readyz` is unaffected.
- [ ] `catalog` source: hits come from `GraphQuery.search` under the caller's scope (descriptions, tags, capabilities of entities in readable domains only); an entity in another domain never influences results.
- [ ] `telemetry_summaries` source: for each readable domain (at most 5, context-narrowed first) the tool builds plain-text summaries per agent from day and hour aggregates (requests, error rate, p95 latency, cost; unknown is "unknown", never 0), cached per customer and domain for 300 s, and cites the aggregate point ids; a caller without `data.read` in a domain gets no summary of it.
- [ ] `search_docs` arguments are `{term (1-256 chars, tokenized only), sources, limit <= 20}`; scope-shaped keys and unknown keys are refused by the PRP-19 registry rules; it is registered in `build_copilot_registry` only, never in the five-tool default registry used by MCP and reports.
- [ ] The groundedness set has exactly 100 questions in `tests/evals/copilot_groundedness/questions.yaml` across graph access, timeline, agent matching, cost and metrics, docs how-to, out-of-scope and injection categories, each with an expected outcome (`answer` with the record ids that must be cited, or `abstain`/`denied` with a reason) and a recorded stream; the offline run passes 100/100 on recorded streams, and a negative control (fabricated numbers, uncited sentences, foreign handles) fails every case.
- [ ] The programmatic judge marks an answer grounded only if every sentence containing a number or an entity name carries a citation, every citation resolves to a record returned in that turn, and every required record id is cited; it reports the pass rate, never a "compliant" or "verified" wording.
- [ ] The live runner (`pytest -m live`) refuses to start without `NS_LIVE_APPROVED=1` and a configured endpoint, and writes results to `docs/evidence/copilot-groundedness/<date>/` with the pass rate against the >90% target; when it did not run, the completion note says OPEN.
- [ ] The dock renders `document` citations as links to the docs URL and `telemetry_summary` citations with their window.
- [ ] Helm renders `NS_COPILOT_MODE`, `_ENDPOINT`, `_DEPLOYMENT`, `_API_VERSION`, `_REGION`, `_MODEL_FEATURE`, `_SKU`, `_OAUTH_SCOPE` and `NS_COPILOT_DOCS_DIR` from a `copilot:` values block (default mode `disabled`, never a credential value); `tests/unit/infra/test_helm_render.py` covers it.
- PRP exit: touched suites, injection corpus, ruff, pyright, frontend lint/typecheck/test, helm render test and `validate_planning.py` pass; PR open with CI green; live run written OPEN unless evidenced.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Docs corpus boundary | repository Markdown; built site | Built site HTML only, like `services/docs-assistant/docs_assistant/index.py` (published pages only; `exclude_docs` already applied) |
| 2 | Vector store | Azure AI Search vectors; Qdrant; lexical first | Lexical BM25 first (gap analysis section 5 item 3); ASSUMPTION: vectors are an optional later ranking signal behind the same port |
| 3 | Telemetry summaries | indexed by a worker; built on demand | ASSUMPTION: built on demand from aggregates per readable domain with a 300 s cache; no new container or worker role |
| 4 | Groundedness judge | LLM judge (PRP-16); programmatic | Programmatic (citations resolve, claims cited, required ids present); ASSUMPTION: an LLM judge pass can be added later through PRP-16 calibration |
| 5 | What "recorded streams" means | one fixture; per-question transcripts | One scripted transcript per question (tool calls, then an answer citing issued handles) replayed through the real engine and tools on the seeded world |
| 6 | Pass bar offline vs live | assert 90 % both; assert offline only | Offline asserts 100/100 (it tests the pipeline); live reports the measured rate against the >90 % target and is not asserted in CI |
| 7 | Docs in the hosted image | edit Dockerfiles here; follow-up | Follow-up (Dockerfiles are Tier 1 with no W23 owner); hosted reports `docs_corpus_unconfigured` until then |
| 8 | Helm edits | here; serial | `[serial-after: PRP-84]`, which owns `infra/helm/**` in W23 |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-78-copilot-graph-timeline-and-recommender-tools.md` (or its shipped copy) - "Interfaces provided": `build_copilot_registry`, `neurosphere_api.copilot.tooling.build_tool_ports`, `progress` event (and `RecordedDemoAdapter`, decided by the owner 2026-11-16).
- `packages/core/neurosphere_core/copilot/tools/builtin.py` - `_build_result`, `_readable_domains`, citation rows.
- `services/api/neurosphere_api/copilot/engine.py` - `_tool_content` handles (`:249-275`), `_judge` (`:681-707`).
- `services/docs-assistant/docs_assistant/index.py` - `tokenize`, `_PageParser`, `_chunks_from_html`, `DocsIndex` (pattern only; do not import).
- `packages/core/neurosphere_core/search/protocol.py` and `catalog/protocol.py:412-470` - `GraphSearchRequest`, `GraphQuery.search`.
- `packages/core/neurosphere_core/aggregates/` - `AggregateWindow`, `Grain`, `QueryResult` (as used by `_get_cost_summary`).
- `services/api/tests/copilot_api/copilot_api_harness.py` - world, ports and `ScriptedAdapter`.
- `infra/helm/values.yaml:110-114` and `infra/helm/templates/deployment.yaml` - the `search:` block to copy; `tests/unit/infra/test_helm_render.py`.
- `tests/e2e/copilot/test_first_token.py` - an unmarked engine-level measurement test to imitate for the offline harness.

### Interfaces consumed
- PRP-78: `build_copilot_registry(deps, *, sink, observer)`, `CopilotToolDependencies`, `neurosphere_api.copilot.tooling.build_tool_ports(ctx)`, `CopilotToolAuditor`, `COPILOT_TOOL_NAMES`; `RecordedDemoAdapter` (PRP-78 clarification 6, decided 2026-11-16; this PRP's groundedness harness uses its own scripted transcripts and does not depend on it).
- PRP-60: the catalog search index correct on Azure AI Search (`text` field, encoded keys, worker writes indexed); the `catalog` source uses whatever provider is composed.
- PRP-71: the seeded realistic world the groundedness set is written against (the sandbox world otherwise). PRP-70: catalog `tags`, `capabilities` (indexed text).
- Shipped: `GraphQuery.search` on `app.state.catalog_graph`, `AggregateReader`, the PRP-19 registry, judge and citation rules, the `live` pytest marker (`pyproject.toml:93`). PRP-55, PRP-58 and PRP-60 are treated as shipped.

### Interfaces provided
- Core: `neurosphere_core.copilot.retrieval.docs` (`DocsCorpus.load(site_dir, base_url)`, `DocsPassage`, caps `MAX_DOC_CHUNKS=5000`, `MAX_CORPUS_BYTES=20_000_000`); `neurosphere_core.copilot.retrieval.summaries` (`TelemetrySummaryBuilder`, `SUMMARY_CACHE_SECONDS=300`); tool `neurosphere_core.copilot.tools.search_docs` (`search_docs`, `SearchDocsArgs`, source names `product_docs`, `catalog`, `telemetry_summaries`; citation kinds `document`, `telemetry_summary`).
- API: `neurosphere_api.copilot.retrieval_settings.CopilotRetrievalSettings` (`NS_COPILOT_DOCS_DIR`, `NS_COPILOT_DOCS_BASE_URL`); docs port bound in `tooling.build_tool_ports`.
- Evals: `tests/evals/copilot_groundedness/` (`questions.yaml`, `transcripts/`, `judge.py`, offline and live tests); evidence layout `docs/evidence/copilot-groundedness/<date>/{results.json,README.md}`.
- Helm: `copilot:` values block (`mode`, `endpoint`, `deployment`, `apiVersion`, `region`, `modelFeature`, `sku`, `oauthScope`, `docsDir`).

### Patterns to match
- HTML chunking by heading with symlink skip: `services/docs-assistant/docs_assistant/index.py:72-170`.
- Tool row and citation construction: `builtin.py:177-210`.
- Engine-level offline harness with a scripted adapter: `services/api/tests/copilot_api/copilot_api_harness.py:304-335`.
- Helm env from values with an empty default: `infra/helm/values.yaml:110-114` and its template lines.
- Live test refusing without approval: `services/docs-assistant/tests/test_live_model_smoke.py`.

### Gotchas
- Answers cite `cite_as` handles, not record ids; transcripts must cite handles in issue order (`r1`, `r2`...) of the tool results they request, or the judge abstains `unsupported_citation`.
- Docs text is product-public, but telemetry summaries are domain data: build summaries only after `_readable_domains`, and filter every summary row by domain again (the double filter in `builtin.py`).
- `search_docs.term` is model text: it is tokenized and scored only; never pass it to a provider query syntax (Azure `query_type="simple"` already, `search/azure/client.py:98`); add injection cases with operators and quotes.
- `NS_COPILOT_*` names containing `KEY`, `SECRET` or `PASSWORD` refuse startup (`runtime/builders/copilot.py:99`); the new names avoid them.
- 100 transcripts are data, not code: keep them small JSON/YAML, generated once by a helper script in the eval folder and reviewed; do not generate them at test time.
- The evaluation folder is under the `tests` root (no new CI shard); give it a unique name and no `__init__.py` clash with `tests/e2e/copilot`.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/copilot/retrieval/**
  - packages/core/neurosphere_core/copilot/tools/search_docs.py
  - packages/core/neurosphere_core/copilot/tools/registry.py
  - packages/core/neurosphere_core/copilot/tools/__init__.py
  - packages/core/tests/copilot_retrieval/**
  - services/api/neurosphere_api/copilot/**
  - services/api/tests/copilot_retrieval_api/**
  - tests/evals/copilot_groundedness/**
  - docs/evidence/copilot-groundedness/**
  - frontend/src/features/copilot/**
  - frontend/tests/mock-api/copilot.ts
  - docs/runbooks/copilot.md
tier1: []
tier2_appends:
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/search/**
  - packages/core/neurosphere_core/catalog/**
  - services/api/neurosphere_api/runtime/builders/**
  - services/api/neurosphere_api/mcp/**
  - services/docs-assistant/**
  - infra/bicep/**
  - infra/demo/**
  - infra/appservice/**
  - services/api/Dockerfile
```

## Implementation blueprint

Parallelization: items 1 and 2 are [P] (separate core modules and test files). Item 3 after 1 and 2; item 4 after 3; items 5 and 7 after 4 and [P] with each other; item 6 after 5; item 8 last.

### Item 1 - Docs corpus and lexical index  [P]
- Deliverable: `copilot/retrieval/docs.py`: load a built site directory, chunk by heading, keep the published URL, BM25 scoring, caps, a corpus build timestamp; no network.
- Owned files: `packages/core/neurosphere_core/copilot/retrieval/{__init__,docs}.py`, `packages/core/tests/copilot_retrieval/test_docs_corpus.py`.
- Depends on: none.
- Acceptance criteria: criteria 1 and 2 at the core level; files outside the directory and symlinks are never read (test with a symlink and `..` path).
- Tests: `test_docs_corpus.py` with a small HTML fixture site under the test folder.
- Pattern references: `services/docs-assistant/docs_assistant/index.py:51-235`.

### Item 2 - Telemetry summaries  [P]
- Deliverable: `copilot/retrieval/summaries.py`: per-domain summaries from `MetricsReader` (day and hour grain), unknown kept as unknown, cached 300 s per (customer, domain), point ids kept for citations.
- Owned files: `packages/core/neurosphere_core/copilot/retrieval/summaries.py`, `packages/core/tests/copilot_retrieval/test_summaries.py`.
- Depends on: none.
- Acceptance criteria: criterion 4; a domain absent from the readable set is never queried (spy reader).
- Tests: `test_summaries.py`.
- Pattern references: `builtin.py:256-305` (`_get_cost_summary`).

### Item 3 - `search_docs` tool and registration
- Deliverable: `copilot/tools/search_docs.py` merging the three sources (scope first, then rank, then cap), `sections_omitted`; registration in `build_copilot_registry` when a docs port or catalog graph is bound; injection cases.
- Owned files: `copilot/tools/search_docs.py`, `copilot/tools/registry.py` (registration only), `copilot/tools/__init__.py`, `packages/core/tests/copilot_retrieval/test_search_docs.py`.
- Must NOT touch: the other tool modules (PRP-78).
- Depends on: items 1, 2; PRP-78 merged.
- Acceptance criteria: criteria 3 and 5; default registry still five tools.
- Tests: `test_search_docs.py`, `packages/core/tests/copilot`, `packages/core/tests/copilot_graph_tools`.
- Pattern references: `builtin.py:213-253`.

### Item 4 - API wiring and settings
- Deliverable: `CopilotRetrievalSettings`; docs corpus loaded once at composition through `tooling.build_tool_ports` (failure to load is a logged reason code, never a startup failure); summaries bound to the shared aggregate reader; catalog source bound to `app.state.catalog_graph`.
- Owned files: `services/api/neurosphere_api/copilot/{tooling,retrieval_settings}.py`, `services/api/tests/copilot_retrieval_api/test_wiring.py`.
- Must NOT touch: `runtime/builders/copilot.py` (PRP-78's `build_tool_ports` is the seam).
- Depends on: item 3.
- Acceptance criteria: with and without `NS_COPILOT_DOCS_DIR`; `services/api/tests/copilot_api` and `copilot_tools_api` pass; injection corpus 78/78.
- Tests: `test_wiring.py`, `services/api/tests/copilot_api`, `services/api/tests/copilot_tools_api`.
- Pattern references: PRP-78 `tooling.build_tool_ports`.

### Item 5 - Groundedness set and offline harness  [P]
- Deliverable: 100 questions with categories, expected outcomes and per-question transcripts on the seeded world; `judge.py`; an unmarked test that runs all 100 through the composed engine with the recorded transcripts and the real tools, asserts 100/100, and a negative control that must fail every case; a summary printed by category.
- Owned files: `tests/evals/copilot_groundedness/**`.
- Depends on: item 4.
- Acceptance criteria: criteria 6 and 7.
- Tests: `tests/evals/copilot_groundedness/test_offline_groundedness.py`, `test_judge_negative_control.py`.
- Pattern references: `services/api/tests/copilot_api/copilot_api_harness.py`, `tests/e2e/copilot/test_first_token.py`.

### Item 6 - Live groundedness runner
- Deliverable: `test_live_groundedness.py` (`pytest.mark.live`) using the configured `approved_endpoint` adapter, refusing without `NS_LIVE_APPROVED=1`; writes `results.json` and a README with model, region, date, pass rate, per-category rates and failures; runbook section for the operator.
- Owned files: `tests/evals/copilot_groundedness/test_live_groundedness.py`, `docs/evidence/copilot-groundedness/README.md`, `docs/runbooks/copilot.md`.
- Depends on: item 5.
- Acceptance criteria: criterion 8; the default test selection deselects it.
- Tests: a unit test that the runner refuses without approval.
- Pattern references: `services/docs-assistant/tests/test_live_model_smoke.py`.

### Item 7 - Dock citations  [P]
- Deliverable: document citations as external links (safe `rel`), summary citations with window; mock fixture and unit test.
- Owned files: `frontend/src/features/copilot/**`, `frontend/tests/mock-api/copilot.ts`.
- Depends on: item 4.
- Acceptance criteria: criterion 9; a11y test unchanged.
- Tests: `frontend/src/features/copilot/copilot.test.tsx`.
- Pattern references: `frontend/src/features/copilot/components.tsx:105-115`.

### Item 8 - Helm values and close-out  [serial-after: PRP-84]
- Deliverable: after PRP-84 merges and the branch is rebased, the `copilot:` values block and template env lines, plus a render test; if the orchestrator does not grant the Tier-1 edit, file a follow-up instead and record it. Then Tier-3 regeneration (`openapi.json` if status or models changed, `docs/reference/**`, status table, `PRPs/INDEX.md`, `PRPs/EXECUTION-PLAN.md`), `mkdocs.yml` nav line for the evidence README if published, changelog fragment, completion note with env vars, the OPEN live run, and the follow-up for the docs site in the hosted image.
- Owned files: `infra/helm/values.yaml`, `infra/helm/templates/deployment.yaml`, `tests/unit/infra/test_helm_render.py` (all as granted after PRP-84), this PRP file, Tier-3 files.
- Depends on: items 1-7; PRP-84 merged.
- Acceptance criteria: criterion 10; validation gates pass.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/copilot packages/core/tests/copilot_graph_tools packages/core/tests/copilot_retrieval services/api/tests/copilot_api services/api/tests/copilot_tools_api services/api/tests/copilot_retrieval_api services/api/tests/mcp_api services/api/tests/reports tests/evals/copilot_groundedness tests/integration/copilot tests/security tests/unit/infra/test_helm_render.py services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Operator only, not CI: `NS_LIVE_APPROVED=1 uv run pytest -q -m live tests/evals/copilot_groundedness/test_live_groundedness.py`.

## Migration and rollback
No data migration and no container: the docs corpus lives in memory, summaries in a short cache. Turn off: unset `NS_COPILOT_DOCS_DIR` (docs source omitted) or set `NS_COPILOT_MODE=disabled`. Helm values default to `disabled`. Revert the PR to return to PRP-78's tool set.

## Live and open gates
The live groundedness run on a real model (100 questions, >90 % target) and the first-token measurement against a provider need `NS_LIVE_APPROVED=1` and an approved Foundry endpoint; they are OPEN and handed to PRP-64 (a row to add there). Docs retrieval in the hosted environment stays OPEN until the built site is in the image (follow-up).

## NOT building
Vector embeddings or a vector store; an indexing worker for summaries; changes to `services/docs-assistant`; a docs site build inside the API image; LLM-judge scoring of groundedness; copilot usage metrics; MCP exposure of `search_docs`.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 2, 3 and 4 are ASSUMPTIONS for plan approval)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |
| 7 | todo | | |
| 8 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator: `NS_COPILOT_DOCS_DIR`, `NS_COPILOT_DOCS_BASE_URL`.
- Follow-up issues:
- Product check (can an operator use it without editing files):
