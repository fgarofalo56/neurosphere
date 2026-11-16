---
name: PRP-135-semantic-matching-and-embedding-port
status: backlog
priority: P2
order: 135
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-02, NS-03, NS-06
depends_on: [PRP-72-agent-and-tool-recommender-backend, PRP-80-copilot-docs-retrieval-and-groundedness, PRP-60-search-indexing-hardening]
wave: W33
branch: prp-135-semantic-matching
allow_parallel: true
issues: []
---

# PRP-135: Semantic matching and embedding port

## Goal
Add meaning-based matching behind the seams the earlier PRPs left for it, without making it a requirement. An `EmbeddingProvider` port (disabled by default) turns catalog text into vectors through an operator-approved model deployment inside the deployment's own cloud boundary; a vector retriever and hybrid ranking sit behind the existing `AuthorizedSearch` protocol (an in-process cosine index for the fixture backend, vector fields and a hybrid query in the Azure AI Search adapter); PRP-72's agent matcher gains an embedding signal; PRP-80's `search_docs` gains hybrid ranking; and an offline evaluation reports lexical against hybrid on the groundedness set. Lexical BM25 stays the default and the fallback everywhere, so there is no new paid dependency unless an operator turns it on, and every result says which signals produced it (`lexical`, `embedding`, or both, and why it fell back). It is for the platform engineer asking "find me an agent that handles invoice disputes" when no tag says "invoice", and for the copilot answering a docs question phrased unlike the page.

Out of scope: the matcher, its API and feedback (PRP-72); `search_docs`, the docs corpus and the groundedness harness themselves (PRP-80); the index definition, key encoding and indexing worker hardening (PRP-60, extended here only by an optional vector field); the PostgreSQL `pgvector` store and the embedding key-wrap or endpoint choices for AWS and GCP (PRP-91 and the multi-cloud PRPs consume the port; noted in the runbook only); embedding any captured interaction content (never, see Gotchas); a trained or LLM re-ranker; a live embedding call or live Azure AI Search vector run (operator-gated, PRP-136 and PRP-64).

## Why
- The gap is stated in three shipped or planned PRPs and owned by none: PRP-60 defers "semantic or vector search" (`PRPs/backlog/PRP-60-search-indexing-hardening.md` Out of scope and NOT building); PRP-72 clarification 2 decides embeddings are "later" and names `SimilaritySignalProvider` "the documented seam for a future embedding signal"; PRP-80 clarification 2 keeps vectors "an optional later ranking signal behind the same port". The design assigns the follow-up here (design G-k).
- Search today is lexical only: `AuthorizedSearch` (`packages/core/neurosphere_core/search/protocol.py:84-87`) takes a term and returns `SearchHit` of id and score; the fixture is BM25 with no embeddings (`search/fixture/index.py` module docstring); the Azure client pins `query_type="simple"` (`search/azure/client.py:98`). Nothing carries a vector or says which signals produced a rank.
- The one existing seam is real but unfed: `SimilaritySignalProvider.similarity(agent_a, agent_b) -> float | None` (`services/workers/neurosphere_workers/recommendations/duplicates/models.py:28-37`), consumed by `DuplicateDetector` (`detector.py:160,387-397`) with an `embedding` weight already in the signal list, and passed through `recommendations/pipeline.py:276`; no implementation exists.
- The original product promised it: `docs/PRD.md` NS-06 and original 5e quoted by PRP-80 ("RAG over the graph and a vector store of documentation/telemetry summaries"); `PRP.md:14` keeps vector stores "historical alternatives, not required GA dependencies", which this PRP honours by making them optional.
- The capability matrix already knows the building blocks and marks them unverified for Government: `packages/core/neurosphere_core/capabilities/data/search.yaml:142-149` (`ai_search.vector_search.government.global.any`, availability `unverified`) and `foundry.yaml:116-127,242-249` (`foundry.model_text_embedding_3.government.*`, `ga_status: unverified`). There are no Commercial rows; the PRP must add only what it verifies.
- Owner direction 2026-11-16: "the ultimate team AI governance and auditing tool"; all gaps planned.

## Acceptance criteria
- [ ] Verified facts recorded: `docs/runbooks/semantic-search.md` section "Verified facts" lists, each with URL and retrieval date, what the vendor documentation says about vector fields and profiles, hybrid query shape, the service tier needed, how a filter combines with a vector query (the order of filtering and ranking), dimension limits, the embedding deployment's endpoint and authentication shape, token and batch limits, and Commercial and Government availability; anything not found says "not found" and the dependent behaviour is disabled. Matrix rows are appended to `capabilities/data/{search,foundry}.yaml` only from these facts.
- [ ] Default off: with no `NS_EMBEDDING_*` setting and `NS_SEARCH_MODE` unset, behaviour is byte-for-byte as before: no embedding call, no vector field written, search results and the matcher unchanged, existing tests pass untouched.
- [ ] Port: `EmbeddingProvider.embed(texts, purpose)` returns vectors with `model_id`, `dimensions` and a `version`; implementations are `Disabled` (default), `Fixture` (deterministic, no network, hash-based; test and local use only, labelled as plumbing evidence) and one endpoint-backed provider for the operator-approved deployment (managed identity, no key, host allowed only inside the deployment's cloud, a Government deployment refuses a non-Government host and never falls back to Commercial).
- [ ] Cost control: per-refresh and per-day item caps (`NS_EMBEDDING_MAX_ITEMS_PER_REFRESH`, default 2000; `NS_EMBEDDING_MAX_ITEMS_PER_DAY`, default 20000; ASSUMPTION (GD-30, recommended default): embedding spend is capped by default at 2000 embeddings per refresh and 20000 per day), batching, content-hash caching so unchanged documents are not re-embedded, a visible counter, and a hard stop with reason `embedding_budget_exhausted` that degrades to lexical, never errors the search.
- [ ] Scope first: Given two scopes and documents in domains only one can read, When a hybrid search runs for the other scope, Then no out-of-scope document appears and neither the cosine index nor Azure query ranks or scores over out-of-scope vectors (the in-process index filters before scoring; the Azure query carries the existing OData filter and the verified filter-before-vector mode, else hybrid is disabled for that backend); a test with a poisoned out-of-scope near-duplicate proves it does not change in-scope ranks.
- [ ] Hybrid fusion: lexical and vector rank lists are fused by reciprocal rank fusion with a documented constant, deterministic tie-break by canonical id ascending, bounded by the request budget; a timeout in the vector leg returns the lexical result marked `partial` with `ranking="lexical"` and `fallback_reason="embedding_timeout"`.
- [ ] Transparency: `SearchResult` gains optional `ranking` (`lexical`|`hybrid`), `signals_used` (list) and `fallback_reason`; `SearchHit` gains optional `lexical_score` and `vector_score` (null when that leg did not run). All additions are optional with defaults, so existing callers and `extra="forbid"` models keep passing; API output reflects them where search results are returned and `openapi.json` is regenerated.
- [ ] Matcher signal: Given `NS_SEARCH_MODE=hybrid` with a working provider, When PRP-72's matcher runs, Then its explanation lists an `embedding` signal with its weight and value for each candidate, `combine` renormalizes over observed signals, and `signals_unavailable` lists `embedding` when the provider is off or failed; with the provider off, the explanation and ranks are those of PRP-72.
- [ ] Duplicates adapter: a structural implementation of `SimilaritySignalProvider` over the vector index exists in core and is unit-tested; it returns `None` when either agent has no vector. Wiring it into the worker role is a separate step (see Cut line).
- [ ] `search_docs` hybrid: Given the docs corpus and `NS_SEARCH_MODE=hybrid`, When `search_docs` runs, Then passages are ranked by fusion, each citation row carries `ranking` and `signals_used`, a corpus larger than `NS_EMBEDDING_MAX_ITEMS_PER_REFRESH` is embedded up to the cap and the rest ranks lexically with that stated in the result; with the provider off nothing changes.
- [ ] Evaluation: `tests/evals/semantic_retrieval/` runs the PRP-80 groundedness questions that need retrieval through both modes offline and writes recall at k and rank of the expected source for lexical and hybrid to `docs/evidence/semantic-retrieval/<date>/results.json`; with the Fixture provider it is labelled "plumbing check, not a quality claim"; a live run with a real deployment is OPEN (operator-gated).
- [ ] Content guard: the embedding provider accepts only catalog documents, docs passages and recommender task text (typed inputs); a test proves interaction records, captured content, audit payloads and telemetry payload bodies cannot be passed (type refusal), and that no embedding text is logged.
- [ ] Capability gating: with the matrix row `unverified` or missing for the deployment cloud and region, the endpoint-backed provider reports disabled with reason `embedding_capability_unavailable` on `/readyz` (optional component) and search stays lexical.
- PRP exit: touched suites, ruff, pyright, `validate_planning.py`, OpenAPI drift test pass; PR open with CI green; live runs recorded OPEN and handed to PRP-136 (embedding) and PRP-64 (Azure AI Search vector).

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Default | On; off | Off. Lexical is the default and fallback on every platform; no new paid dependency by default (design G-k) |
| 2 | Where embeddings come from | Hosted public API; in-boundary deployment | An operator-approved model deployment in the same cloud boundary. Whether and where one exists is a verify-first fact (design U-22); otherwise the port ships disabled |
| 3 | Vector backends | Azure AI Search only; port | Port with three backends: in-process cosine (fixture and small deployments), Azure AI Search vector fields, and a documented `pgvector` seam for PRP-91 (not built here) |
| 4 | Fusion | Weighted sum; reciprocal rank fusion | Reciprocal rank fusion with a fixed documented constant; no tuned weights claimed |
| 5 | How callers opt in | Always hybrid; per request | `SearchRequest.mode` (optional, default lexical) plus the deployment setting `NS_SEARCH_MODE`; hybrid happens only when both allow it and the provider is healthy |
| 6 | What gets embedded | Everything; allowlisted | Catalog entity text already indexed for search, docs passages and recommender task text; never interaction content, audit, telemetry bodies or secrets (typed inputs) |
| 7 | Matcher integration | New signal wired in `data.py`; derive from the injected search | Derive from the hybrid `AuthorizedSearch` already injected (per-hit `lexical_score` and `vector_score`), so no change to the Tier-1 data builder; ASSUMPTION |
| 8 | Duplicates worker wiring | Here; later | Adapter here, wiring later: `workers/runtime/factories.py` is a Tier-1 file this PRP is not granted |
| 9 | Index change on Azure | In place; new index | ASSUMPTION: vector field and profile are added only when hybrid is enabled and, if the verified rules do not allow adding a vector field in place, a new index name is used (`NS_SEARCH_VECTOR_INDEX`) and refilled by the existing indexer; operator action recorded in the runbook |
| 10 | Dimensions and model change | Fixed; configured | Configured and stored with each vector (`model_id`, `dimensions`, `version`); a mismatch between query and index disables the vector leg with `embedding_model_mismatch`, never mixes spaces |
| 11 | Evaluation honesty | Report quality; report plumbing | Offline numbers with the Fixture provider are plumbing only; a quality statement requires the live run with a real deployment |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/search/protocol.py` - `AuthorizedSearch`, `SearchRequest`, `SearchHit`, `SearchResult` (all `extra="forbid"`).
- `packages/core/neurosphere_core/search/fixture/index.py` - scope-first BM25, tie-break, docstring guarantees to keep.
- `packages/core/neurosphere_core/search/azure/{client.py,filters.py,fallback.py}` and (new in PRP-60) `search/azure/schema.py`, `search/indexer.py` - the backend, the OData scope filter, `FallbackAuthorizedSearch`, `catalog_index_definition()`, `CatalogIndexer`.
- `services/api/neurosphere_api/runtime/builders/search.py` - `SearchSettings` (`NS_SEARCH_*`), `IndexedGraphQuery`, `SearchRuntime`; `PRPs/backlog/PRP-60-search-indexing-hardening.md` for what it adds.
- `PRPs/backlog/PRP-72-agent-and-tool-recommender-backend.md` and `packages/core/neurosphere_core/recommendations/matching/` (after PRP-72 merges) - signal functions, `combine`, `MatchSettings`, `signals_unavailable`.
- `services/workers/neurosphere_workers/recommendations/duplicates/{models.py,detector.py}` - `SimilaritySignalProvider` and its use.
- `PRPs/backlog/PRP-80-copilot-docs-retrieval-and-groundedness.md` and `packages/core/neurosphere_core/copilot/{retrieval,tools/search_docs.py}`, `tests/evals/copilot_groundedness/` (after PRP-80 merges).
- `packages/core/neurosphere_core/capabilities/data/{search,foundry}.yaml` and `packages/core/neurosphere_core/copilot/models/gating.py:136-170` (`resolve_adapters`, capability gating with a reason) - the pattern for disabled-with-reason providers.

### Interfaces consumed
- PRP-60: `catalog_index_definition()`, `ensure_index`, `CatalogIndexer`, `IndexSink`, `NS_SEARCH_ENSURE_INDEX`, `wrap_catalog_for_search`.
- PRP-72: `AgentMatcher`, signal functions, `combine`, `MatchSettings`, `NS_MATCH_WEIGHTS`, `signals_unavailable` (names from its "Interfaces provided"; confirm against the merged code).
- PRP-80: `DocsCorpus`, `DocsPassage`, `search_docs` and `SearchDocsArgs`, caps, groundedness questions and harness.
- Shipped: `IdentityScope`, `Budget`, `SimilaritySignalProvider`, `CapabilityMatrix` and `resolve_adapters`-style gating, `DefaultAzureCredential` use in the search builder.
- By purpose: PRP-91 (PostgreSQL search with `pgvector`, multi-cloud) consumes `VectorRetriever`; not built here.

### Interfaces provided
- Core `neurosphere_core.search.embedding`: `EmbeddingProvider` protocol, `EmbeddingBatch`, `DisabledEmbeddingProvider`, `FixtureEmbeddingProvider`, endpoint-backed provider, `EmbeddingBudget`, `EmbeddingCache`, typed input classes `CatalogText`, `DocsPassageText`, `TaskText`.
- Core `neurosphere_core.search.vector`: `VectorRetriever` protocol, `InProcessCosineIndex`, `AgentVectorSimilarity` (structural `SimilaritySignalProvider`), `rrf_fuse`.
- Core `neurosphere_core.search.hybrid`: `HybridAuthorizedSearch(lexical, vector, provider, ...)` implementing `AuthorizedSearch`.
- Additive fields: `SearchRequest.mode`, `SearchResult.{ranking,signals_used,fallback_reason}`, `SearchHit.{lexical_score,vector_score}`.
- Azure: vector field and profile in `catalog_index_definition()` when enabled, hybrid query in `AzureAuthorizedSearch`.
- Settings: `NS_SEARCH_MODE` (`lexical` default, `hybrid`), `NS_EMBEDDING_PROVIDER` (`none` default, `fixture`, `endpoint`), `NS_EMBEDDING_ENDPOINT`, `NS_EMBEDDING_DEPLOYMENT`, `NS_EMBEDDING_REGION`, `NS_EMBEDDING_MAX_ITEMS_PER_REFRESH`, `NS_EMBEDDING_MAX_ITEMS_PER_DAY`, `NS_SEARCH_VECTOR_INDEX`; optional component `embedding` with a reason code.
- Evals: `tests/evals/semantic_retrieval/`; evidence `docs/evidence/semantic-retrieval/<date>/`; runbook `docs/runbooks/semantic-search.md`.

### Patterns to match
- Scope-then-rank with tie-break by canonical id: `search/fixture/index.py` docstring and `search/azure/client.py` sort.
- Disabled-with-reason availability: `copilot/models/gating.py` (`_disabled`, `AdapterAvailability`).
- Optional component with a reason code: `services/api/neurosphere_api/runtime/builders/edge.py:17-27`.
- Fallback wrapper that never reroutes cloud: `search/azure/fallback.py:65-100`.
- Deterministic fixtures with no randomness: `search/fixture/index.py`.
- Offline engine-level eval: `tests/e2e/copilot/test_first_token.py` (as PRP-80 cites).

### Gotchas
- UNVERIFIED (design U-21, verbatim): "Azure AI Search supports vector fields and hybrid queries on the deployed tier in both clouds; `pgvector` is available on the managed PostgreSQL services chosen by PRP-89." If false: "Lexical only on that platform." The capability row `ai_search.vector_search.government.global.any` is `unverified` today (`search.yaml:142-149`).
- UNVERIFIED (design U-22, verbatim): "An embedding model deployment is available in the same boundary (paid, operator-approved)." If false: "Port ships disabled." Government rows for `text-embedding-3` exist but `ga_status: unverified` (`foundry.yaml:116-127`); Commercial rows do not exist.
- Authorization is the whole risk: a vector query that ranks first and filters afterwards leaks through rank and score; the verified filter-before-vector behaviour is a hard precondition for the Azure leg, otherwise it is disabled.
- Embedding text leaves the process for the model endpoint: only the three typed inputs are accepted; catalog descriptions can be sensitive to a customer, so the endpoint must be inside the boundary and operator-approved, and Government never reroutes.
- Vectors of different models or dimensions are not comparable; store `model_id`, `dimensions` and `version` with every vector and refuse mixed spaces.
- `SearchResult` and `SearchHit` are `extra="forbid"` pydantic models used by `RepositoryGraphQuery.search` and test helpers (`packages/core/tests/catalog/graph_helpers.py`); only add optional fields with defaults, and expect the OpenAPI drift test and any pinned response models to need regeneration.
- Pure-Python cosine: use `math.sumprod` (Python 3.12, C-speed) over normalised vectors and cap in-scope candidates; no new dependency (no numpy in `pyproject.toml`). Record the measured p95 at 10k documents in the runbook; if it exceeds the existing search budget, the in-process index is documented as small-deployment only.
- Not granted here: `services/api/neurosphere_api/runtime/builders/data.py` (PRP-72 wave owner), `services/workers/neurosphere_workers/runtime/factories.py` and `packages/core/neurosphere_core/stores/containers.py`. If the matcher cannot take the signal from the injected search, raise `[serial-after: PRP-72 Tier-1 owner]`; do not edit them.
- The hosted index changes shape with vectors; reindex time and embedding cost scale with catalog size, and the first refresh can exhaust the cap: state the cap in the runbook and log the counter, never the text.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/search/embedding/**
  - packages/core/neurosphere_core/search/vector/**
  - packages/core/neurosphere_core/search/hybrid.py
  - packages/core/neurosphere_core/search/protocol.py
  - packages/core/neurosphere_core/search/indexer.py
  - packages/core/neurosphere_core/search/__init__.py
  - packages/core/neurosphere_core/search/azure/**
  - packages/core/neurosphere_core/recommendations/matching/embedding_signal.py
  - packages/core/neurosphere_core/recommendations/matching/combine.py
  - packages/core/neurosphere_core/recommendations/matching/signals.py
  - packages/core/neurosphere_core/copilot/retrieval/hybrid.py
  - packages/core/neurosphere_core/copilot/tools/search_docs.py
  - packages/core/tests/search_embedding/**
  - packages/core/tests/search_vector/**
  - packages/core/tests/agent_match/test_embedding_signal.py
  - packages/core/tests/copilot_retrieval/test_search_docs_hybrid.py
  - services/api/tests/runtime_data/test_search_hybrid_builder.py
  - tests/evals/semantic_retrieval/**
  - docs/runbooks/semantic-search.md
  - docs/evidence/semantic-retrieval/**
  - changelog.d/PRP-135-semantic-matching-and-embedding-port.md
tier1:
  - services/api/neurosphere_api/runtime/builders/search.py
tier2_appends:
  - services/api/neurosphere_api/runtime/settings.py
  - services/api/neurosphere_api/runtime/status.py
  - packages/core/neurosphere_core/capabilities/data/search.yaml
  - packages/core/neurosphere_core/capabilities/data/foundry.yaml
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - services/api/neurosphere_api/runtime/builders/data.py
  - services/workers/neurosphere_workers/runtime/factories.py
  - services/workers/neurosphere_workers/recommendations/**
  - packages/core/neurosphere_core/stores/containers.py
  - packages/core/neurosphere_core/catalog/**
  - packages/core/neurosphere_core/copilot/tools/registry.py
  - pyproject.toml
  - uv.lock
  - infra/**
  - services/api/Dockerfile
```

## Implementation blueprint

### Item 1 - Verify first: record the vendor facts and gate the matrix
- Deliverable: the "Verified facts" section of `docs/runbooks/semantic-search.md` per the first criterion, with a decision per backend (build, disabled, not found); matrix rows appended for verified facts only (source URL, observed date); a note on `pgvector` for PRP-91 limited to what is verified.
- Owned files: `docs/runbooks/semantic-search.md`, Tier-2 appends to `capabilities/data/{search,foundry}.yaml`.
- Must NOT touch: code.
- Depends on: none (PRP-60, 72 and 80 merged).
- Acceptance criteria: verified-facts criterion; unknown stays "not found"; the capability validator passes.
- Tests: `uv run pytest -q packages/core/tests/capabilities`.
- Pattern references: existing matrix rows and `docs/RESEARCH-AND-GATES.md` source style.

### Item 2 - Embedding port, providers, budget and cache
- Deliverable: `EmbeddingProvider`, the three typed inputs, `Disabled`, `Fixture` and the endpoint-backed provider (httpx, managed identity, cloud-bound host, capability-gated), `EmbeddingBudget` with the two caps and the counter, content-hash `EmbeddingCache`, `embedding_budget_exhausted` and `embedding_capability_unavailable` reasons; no text in logs.
- Owned files: `packages/core/neurosphere_core/search/embedding/**`, `packages/core/tests/search_embedding/**`.
- Depends on: item 1.
- Acceptance criteria: port, cost-control, content-guard and capability-gating criteria.
- Tests: `packages/core/tests/search_embedding/test_providers.py`, `test_budget.py`, `test_cache.py`, `test_typed_inputs.py`, `test_gov_host.py`, `test_no_text_in_logs.py`.
- Pattern references: `copilot/models/gating.py`; the copilot Foundry adapter's httpx use.

### Item 3 - Vector core, fusion and transparency  [P]
- Deliverable: `VectorRetriever` protocol, `InProcessCosineIndex` (scope filter before scoring, `math.sumprod` over normalised vectors, candidate cap, tie-break), `rrf_fuse`, `HybridAuthorizedSearch` with fallback and `partial`, the additive fields on `SearchRequest`, `SearchHit` and `SearchResult`, `AgentVectorSimilarity`.
- Owned files: `packages/core/neurosphere_core/search/{vector/**,hybrid.py,protocol.py,__init__.py}`, `packages/core/tests/search_vector/**`.
- Depends on: item 2.
- Acceptance criteria: scope-first, fusion, transparency, duplicates-adapter criteria; default-off criterion for the protocol additions.
- Tests: `packages/core/tests/search_vector/test_scope_first.py`, `test_poisoned_neighbour.py`, `test_rrf.py`, `test_hybrid_fallback.py`, `test_result_fields.py`, `test_agent_similarity.py`; existing `packages/core/tests/search` unchanged and green.
- Pattern references: `search/fixture/index.py`.

### Item 4 - Azure AI Search vector field and hybrid query  [P]
- Deliverable: optional vector field and profile in `catalog_index_definition()`, the indexer path that embeds documents within the budget and writes vectors with `model_id`, `dimensions` and `version`, the hybrid query in `AzureAuthorizedSearch` carrying the existing scope filter in the verified filter-before-vector mode (otherwise the leg stays disabled with a reason), mismatch refusal, tests against the existing fake backend extended with vectors.
- Owned files: `packages/core/neurosphere_core/search/azure/**`, `packages/core/neurosphere_core/search/indexer.py`, `packages/core/tests/search_vector/test_azure_hybrid.py`.
- Depends on: items 1 and 2 (item 3 for the result fields).
- Acceptance criteria: scope-first on the Azure leg, mismatch and capability criteria; no vector field when hybrid is off.
- Tests: `packages/core/tests/search_vector/test_azure_hybrid.py`, existing `packages/core/tests/search/test_azure_search_scope.py` and `test_indexer.py` unchanged and green.
- Pattern references: `search/azure/client.py`, `filters.py`.

### Item 5 - Composition, settings and readiness
- Deliverable: `NS_SEARCH_MODE` and `NS_EMBEDDING_*` in the search builder, composition of `HybridAuthorizedSearch` over the existing lexical search only when hybrid is allowed and the provider is healthy, Government guard (no reroute), optional component `embedding` with reason code in `/readyz`, stored-setting precedence as for `search`.
- Owned files: `services/api/neurosphere_api/runtime/builders/search.py` (Tier-1), Tier-2 appends to `runtime/settings.py` and `runtime/status.py`, `services/api/tests/runtime_data/test_search_hybrid_builder.py`.
- Depends on: items 2 to 4.
- Acceptance criteria: default-off, capability-gating and Government criteria.
- Tests: `services/api/tests/runtime_data/test_search_hybrid_builder.py`, `test_search_builder.py`, `services/api/tests/runtime_api/test_readiness.py` (component set pinned there: update it).
- Pattern references: existing `SearchSettings` and `build_catalog_graph`.

### Item 6 - Matcher embedding signal
- Deliverable: `embedding_signal` reading per-hit `vector_score` from the injected search, the `embedding` weight in `MatchSettings` defaults (0 when off), `combine` renormalising over observed signals with `embedding` listed in `signals_unavailable` when absent, explanation fields for the signal.
- Owned files: `packages/core/neurosphere_core/recommendations/matching/{embedding_signal.py,combine.py,signals.py}`, `packages/core/tests/agent_match/test_embedding_signal.py`.
- Must NOT touch: matcher API files, `data.py`.
- Depends on: item 3.
- Acceptance criteria: matcher-signal criterion; default-off unchanged ranks.
- Tests: `packages/core/tests/agent_match` (whole directory green) plus the new test.
- Pattern references: `matching/signals.py` `lexical_signal`.

### Item 7 - `search_docs` hybrid and the offline evaluation
- Deliverable: passage vector index built lazily within the cap, fusion in `search_docs`, `ranking` and `signals_used` on citation rows, `tests/evals/semantic_retrieval/` (lexical and hybrid, Fixture provider, recall at k and expected-source rank) and the results file layout; the runbook table of the offline result with its plumbing-only label.
- Owned files: `packages/core/neurosphere_core/copilot/retrieval/hybrid.py`, `packages/core/neurosphere_core/copilot/tools/search_docs.py`, `packages/core/tests/copilot_retrieval/test_search_docs_hybrid.py`, `tests/evals/semantic_retrieval/**`, `docs/evidence/semantic-retrieval/**`.
- Depends on: items 3 and 5.
- Acceptance criteria: `search_docs` and evaluation criteria.
- Tests: `packages/core/tests/copilot_retrieval`, `tests/evals/semantic_retrieval` (offline, unmarked).
- Pattern references: PRP-80 `tests/evals/copilot_groundedness` layout.

### Item 8 - Integration and close-out
- Deliverable: runbook completion (settings table, cost caps, index migration steps, measured p95 for the in-process index, `pgvector` seam note, what the operator must approve), `mkdocs.yml` nav line, changelog fragment, Tier-3 regeneration (`openapi.json` and any generated client types if search results are exposed), completion note listing each backend as verified-built, disabled or OPEN.
- Owned files: the runbook, the changelog fragment, this PRP file.
- Depends on: items 1 to 7.
- Acceptance criteria: validation gates pass; CI green.

## Cut line
Items 1 to 6 and 8 deliver the port, the vector core, the Azure leg, composition and the matcher signal. If the session overruns, item 7 (`search_docs` hybrid and the evaluation) becomes a follow-up PRP without leaving anything half-wired: the tool simply stays lexical. Wiring `AgentVectorSimilarity` into the worker duplicates role is outside this PRP in every case (Tier-1 file `workers/runtime/factories.py`).

## Validation gates
```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/search packages/core/tests/search_embedding packages/core/tests/search_vector packages/core/tests/agent_match packages/core/tests/copilot_retrieval packages/core/tests/capabilities services/api/tests/runtime_data services/api/tests/runtime_api services/api/tests/test_openapi_drift.py tests/evals/semantic_retrieval
python scripts/changelog_assemble.py --check
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration with the defaults. Enabling hybrid on Azure adds a vector field (or a new index, per the verified rule and clarification 9) that the existing indexer refills; the old lexical index keeps working until the setting is switched. Roll back by unsetting `NS_SEARCH_MODE` and `NS_EMBEDDING_PROVIDER` (search is lexical at once; the vector field is ignored) or by reverting the PR; delete the vector index by an operator step recorded in the runbook. Additive fields on search models are backwards compatible.

## Live and open gates
Operator-gated: `NS_LIVE_APPROVED=1`, an embedding deployment in the deployment's own boundary that the operator approves (paid; the live script states the item cap and expected cost before it runs), and an Azure AI Search service on a tier the verified facts allow. Not run here: the live embedding check and a quality evaluation with real embeddings go to PRP-136; the Azure vector query and 10k-document latency go to PRP-64. Until then these are OPEN and the offline evaluation is a plumbing check.

## NOT building
A trained or LLM re-ranker; embeddings of interaction content, audit records, telemetry bodies, secrets or any content that PRP-101 to PRP-104 handle; a hosted public embedding API call by default; a new paid service by default; `pgvector` or any PostgreSQL vector store (PRP-91); a separate vector database (Qdrant, Pinecone); cross-customer or cross-cloud vector sharing; semantic cache of copilot answers; tuned fusion weights or any claim that hybrid is better before a live evaluation says so; wiring the duplicates provider into the worker role.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 7, 9 and the default cap values are ASSUMPTIONS for plan approval)

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
- Descoped items (each backend: verified-built, disabled with reason, or OPEN):
- OPEN gates:
- Env vars for the operator:
- Follow-up issues (duplicates worker wiring; pgvector for PRP-91):
- Product check (can an operator see which signals ranked a result, and is lexical still the default):
