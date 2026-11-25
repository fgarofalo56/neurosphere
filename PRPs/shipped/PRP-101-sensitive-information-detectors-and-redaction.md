---
name: PRP-101-sensitive-information-detectors-and-redaction
status: shipped
shipped: 2026-11-24
pr: 407
priority: P0
order: 101
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: opus
phase: 9
ns: NS-01, NS-08
depends_on: [PRP-70-contracts-revision-restored-scope, PRP-99-governance-contracts-a]
wave: W21
branch: prp-101-detectors-and-redaction
allow_parallel: true
issues: []
---

# PRP-101: Sensitive-information detectors and typed redaction (pure core library)

## Goal
Ship `neurosphere_core.classification`, a pure, dependency-free core library that finds structured sensitive identifiers and credentials in text and replaces them with typed placeholders, so that the opt-in interaction capture path (PRP-103) can detect and redact content at the ingest edge before anything is encrypted or stored. It contains a detector protocol, a versioned deterministic detector set (credentials and secrets, payment cards with Luhn, IBAN with mod 97, US SSN structure rules, email, phone, IP and MAC addresses, URLs with credentials, GUIDs), customer dictionaries and bounded customer patterns, a redaction engine that fails closed, a labelled synthetic corpus with measured precision and recall per detector, and a mapping from detector kinds to PRP-70's `sensitivity_category`. It is for the capture edge (PRP-103), the policy engine's `content_rule` (PRP-105) and the explorer (PRP-104), and it runs in W21 because PRP-103 (W22) cannot be written against anything less. Opus, because a detector that misses a credential would put a secret into an encrypted store that investigators can read.

Out of scope: running detectors on the ingest path or anywhere else (PRP-103); encryption and storage (PRP-102); capture policy (PRP-103); showing findings (PRP-104); a model-based detector (not in this program; GD-6); consolidating the four existing rule sets onto this library (follow-up issue filed at close-out); SDK-side redaction before send (PRP-111).

## Why
- The owner asked on 2026-11-16 for "the ultimate team AI governance and auditing tool" and directed that every identified gap be planned; interaction audit (gap G-a in `temp/audit/governance-core-design.md`) needs content classification first. GD-14 (reverse the 2026-11-06 metadata-only decision for opt-in capture) is approved in principle; that decision was recorded at `docs/validation/PRODUCT-VALIDATION-2026-11-06.md:71-72` ("Prompt and response capture is excluded by design (PRP-33). **Decision: keep metadata-only ...**").
- `docs/PRD.md:12` (NS-01) promises "Redact before persistence and external transmission; prompt/response bodies disabled by default." Today the ingest edge only drops bodies by key name (`packages/core/neurosphere_core/payload/guard.py:21-35` `BODY_FIELD_NAMES`, `:67-104` `drop_body_fields`); no value-level detector runs on ingest.
- Four rule sets exist and none is on ingest or measured: `packages/core/neurosphere_core/copilot/models/redaction.py:36-86` (JWT, bearer, credential phrasing, `sk_`/`ghp_`/`AKIA`, email, GUID, SSN, phone, card by pattern only, address, long opaque runs), `packages/core/neurosphere_core/observability/redaction.py:12-23` (log fields), `packages/core/neurosphere_core/audit/content_guard.py:21-131` (audit keys and strings), `services/api/neurosphere_api/copilot/redaction.py`. The card rule has no Luhn check, so it both over- and under-matches.
- PRP-70 provides the vocabulary findings must map to: `sensitivity_category` (`pii`, `phi`, `cui`, `pci`, `financial`, `biometric`, `credentials`, `export_controlled`, `legal_privileged`, `other`; `PRPs/backlog/PRP-70-contracts-revision-restored-scope.md:88`).

## Acceptance criteria
- [x] Given text containing a generated credential of each supported kind (JWT, bearer token, private-key block, connection string with an account key, password in a URL, each cloud or vendor key format in the verified list), When redacted with any configuration, Then every occurrence is replaced by the PRP-99 placeholder `[[ns-redacted:<detected_category>]]`, the output contains no substring of the match, and the result carries no hash, length, prefix or suffix of the match. Evidence: `tests/security/content_redaction/test_no_secret_leak.py::test_credentials_never_leak` (3 configs; hashes, encodings, length hints), `::test_placeholders_are_bare_category_tokens`, `packages/core/tests/content_detectors/test_secret_detectors.py` glue parity tests.
- [x] Given a Luhn-valid card number, Then it is found and redacted to `[[ns-redacted:payment_card]]` by default; a Luhn-invalid digit run of the same shape is not reported as a card. IBAN uses mod 97 and SSN uses the structure rules (area, group and serial exclusions) the same way. Evidence: `test_identifiers.py::test_luhn_valid_cards_found_every_length`, `::test_luhn_invalid_cards_not_found`, `::test_iban_valid_found_invalid_not`, the SSN exclusion tests; card default redact in `test_engine.py`.
- [x] Given a customer dictionary of exact terms and a customer pattern, When the pattern fails the static safety check (length cap, nested quantifier, backreference, lookaround) it is refused at load with a reason code; a valid pattern runs only on bounded chunks, and when the per-part time budget is exhausted the whole part is reported `redaction_failed` and no partial output is returned. Evidence: `test_customer.py::test_catastrophic_shapes_refused`, `::test_unsafe_patterns_refused_with_detail`; `test_engine.py::test_slow_customer_chunks_exhaust_budget` (`RedactionFailed("budget_exhausted")`, the library's `redaction_failed` result) and the chunk-boundary tests.
- [x] Given any exception inside a detector or the engine, Then the engine returns a `RedactionFailed` result with a reason code and no text; there is no code path that returns the input unredacted. Evidence: `tests/security/content_redaction/test_fail_closed.py` (raising detectors, 20 malformed and forged output shapes, every engine step monkeypatched, 200-seed property run); engine offset re-validation `engine.py` `_validated`.
- [x] Findings carry exactly what PRP-99's `DetectionFinding` holds (category, part, detector id, detector version `x.y.z`, count, action `replaced` or `kept`, confidence, placeholder offsets in the redacted text) plus the PRP-70 `sensitivity_category`, and never the matched text; a credential category is always `replaced`. Evidence: `test_models.py` (field parity with the generated contract, credential + kept rejected, DetectionFinding round trip), `test_engine.py` findings and offset tests.
- [x] Every credential format rejected by PRP-99's `secret_free_text` (`tests/contracts/validators.py::check_secret_free_text`) is detected: redacted output of the corpus validates against the `RedactedContent` JSON Schema (not only the Pydantic model, which ignores `not` patterns). Evidence: `test_engine.py::test_every_kind_redacts_to_secret_free_schema_valid_content` (JSON Schema `interactions/v1/redacted-content.schema.json`), `test_secret_detectors.py` validator-pattern probe test iterating `SECRET_TEXT_PATTERNS`.
- [x] No log record, exception message or `repr` produced by the library contains matched text (caplog test over the full corpus). Evidence: `test_no_secret_leak.py` (all loggers at DEBUG, zero records; repr/str/dump of results and findings), `::test_leak_oracle_has_teeth`, AST scan in `test_fail_closed.py`.
- [x] The labelled synthetic corpus reports precision and recall per detector; credential detectors and the Luhn card detector reach recall 1.0 on the corpus (GD-19, row 6); the measured table is published in `docs/runbooks/content-classification.md` with the detector-set version, and the runbook states "structured identifiers only: names, postal addresses and free-text health or legal content are not detected". Evidence: `test_corpus_quality.py::test_gate_recall_is_one_end_to_end` (all gated categories 1.000), runbook table for `ns-detectors-1.0.0` with digest, coverage statement at `docs/runbooks/content-classification.md:13`.
- PRP exit: `packages/core/tests/content_detectors`, `tests/security/content_redaction`, ruff, pyright, `validate_planning.py` pass; PR open with CI green. Evidence: local gates 2026-11-25 (ruff and pyright repo-wide clean, 1239 passed across the PRP and docs suites, validate_planning exit 0); verify-gates full: lint, typecheck and tests PASS (17608 passed), build FAIL locally only because the worktree's frontend `node_modules` is a Git-Bash symlink Node cannot follow (no frontend change in this PRP; CI frontend builds green); PR #407, CI result recorded below.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Reverse the metadata-only decision | keep; reverse for opt-in capture | Decided by the owner 2026-11-16 (GD-14): the 2026-11-06 metadata-only decision is reversed for opt-in capture only; capture stays OFF by default and "bodies disabled by default" stays true; the orchestrator records it in the decision log. Here: the log is `docs/DECISIONS-LOG.md` |
| 2 | Detector set at launch | deterministic set; add a model detector | Decided by the owner 2026-11-16 (GD-6): deterministic detector set (design section 2.2) plus customer dictionaries; no model detector |
| 3 | What is never stored | redact credentials only; redact all | Decided by the owner 2026-11-16 (GD-4): credentials and secrets always redacted; payment card numbers redacted by default; other detected types redacted or kept per capture policy, default redact. Here: the credential rule is not configurable; the card default is configurable by capture policy |
| 4 | Placeholder shape | opaque `[REDACTED]`; typed; typed plus hash | Typed, PRP-99 grammar `[[ns-redacted:<detected_category>]]`; no hash, length or partial digits (design 2.1) |
| 5 | Bounded customer regex without a new dependency | `regex` package with timeout; static check plus chunking | ASSUMPTION: Python `re` with a static safety check, a pattern length cap and fixed-size chunks; budget exhaustion fails the part closed. A dependency would need the W21 lockfile owner (PRP-102) and is not taken |
| 6 | Quality gate | report only; gate some detectors | Decided by the owner 2026-11-16 (GD-19): only the credential detectors and Luhn-valid payment cards are gated at recall 1.0 on the synthetic corpus; the other detectors report measured recall without a gate |
| 7 | Unicode evasion | detect on raw text; normalize first | ASSUMPTION: NFKC normalization and removal of zero-width characters before detection; the redacted output is the normalized text |
| 8 | Rewrite the four existing rule sets | consolidate now; follow-up | Follow-up issue (design PRP-101 scope) |
| 9 | Category for long opaque runs (item 2 `opaque_secret` is not a PRP-99 `DetectedCategory`) | `other` always redacted; `vendor_api_key`; drop | Decided by the owner 2026-11-24: detector id `opaque_secret`, category `other`, confidence low, always `replaced` (engine forces it regardless of policy); not under the recall 1.0 gate |
| 10 | Category for a SAS `sig=` parameter | `connection_string`; `url_with_credentials` | Orchestrator 2026-11-24: `connection_string` (a SAS signature is shared-access key material) |

Plan approved by the owner 2026-11-24 (session s-8c3599): rows 5-7 ASSUMPTIONS accepted as written; one independent review pass per code item (items 6 and 7 share one).

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/copilot/models/redaction.py:36-86` - existing patterns (reuse the proven ones, do not import the module).
- `packages/core/neurosphere_core/observability/redaction.py` - log redaction; the library must log nothing sensitive.
- `packages/core/neurosphere_core/audit/content_guard.py:68-131` - pointer-plus-category findings, value never echoed.
- `packages/core/neurosphere_core/payload/guard.py` - iterative, pure, counts-only style to copy.
- `packages/core/tests/test_import_boundaries.py` - core import rules the new package must pass.
- `PRPs/backlog/PRP-70-contracts-revision-restored-scope.md` "Interfaces provided" - `sensitivity_category`.
- `temp/audit/governance-core-design.md` sections 2.1, 2.2, 8 item 4.

### Interfaces consumed
- PRP-70: `sensitivity_category` vocabulary (catalog `common.schema.json` `$defs`).
- PRP-99 (`PRPs/backlog/PRP-99-governance-contracts-a.md` "Interfaces provided"): `DetectedCategory` (open-ended: `private_key`, `jwt`, `bearer_token`, `cloud_access_key`, `vendor_api_key`, `connection_string`, `url_with_credentials`, `password_assignment`, `payment_card`, `iban`, `us_ssn`, `email_address`, `phone_number`, `ip_address`, `mac_address`, `guid`, `customer_dictionary_term`, `customer_identifier_pattern`, `other`), `CredentialCategory` (the first eight), `ContentPartKind`, `DetectionFinding`, `RedactedContent` and its `secret_free_text` rule, the placeholder grammar. Runtime code uses the strings; only tests import `neurosphere_contracts`.
- No I/O, no settings.

### Interfaces provided
- `neurosphere_core.classification`: `Detector` protocol (`detector_id`, `version`, `kinds`, `find(text) -> tuple[Match, ...]` with offsets only), `Category` (the PRP-99 `DetectedCategory` strings; `CREDENTIAL_CATEGORIES` the eight credential ones), `Confidence`, `SENSITIVITY_CATEGORY_FOR` (`credentials` for the eight, `pci` for `payment_card`, `financial` for `iban`, `pii` for SSN, email, phone, IP and MAC, a configured category for customer terms and patterns, none for `guid`), `DetectorSet` (id, version, digest of configuration), `RedactionMode` (`redact`, `keep`), `RedactionConfig` (per-category mode mirroring PRP-99 `redaction_mode` and `kept_categories`; credential categories forced to `redact`), `CustomerDictionary`, `CustomerPattern` (validated), `Finding` (the `DetectionFinding` fields plus `sensitivity_category`), `RedactionResult` (`Redacted(text, findings, set_version)` or `RedactionFailed(reason)`), `redact(text, config, detector_set, budget) -> RedactionResult`, `default_detector_set()`, `COVERAGE_LABEL = "structured identifiers only"`.
- Reason codes: `detector_error`, `budget_exhausted`, `pattern_unsafe`, `input_too_large`.
- PRP-103 converts `Finding` into PRP-99's `DetectionFinding` and builds `RedactedContent`; this library does not import contracts at runtime.

### Patterns to match
- Pure, iterative, values never returned in errors: `packages/core/neurosphere_core/payload/guard.py:1-12,67-104`.
- Findings as pointer plus category: `packages/core/neurosphere_core/audit/content_guard.py:110-131`.
- Frozen pydantic models with `extra="forbid"`: `packages/core/neurosphere_core/lifecycle/policy.py:19-20`.

### Gotchas
- Test fixtures must never contain literal credential-shaped strings: gitleaks fingerprints are commit-scoped. Build every key, token and card at runtime from fragments or generators (`packages/core/tests/content_detectors/synth.py`), and keep generated corpora out of the repo.
- Overlapping matches: a connection string contains an account key and a URL; resolve by taking the longest credential span first, then non-credential spans, so a credential is never partly kept.
- Placeholders must not themselves trip a detector on a second pass (idempotence test).
- `re` cannot be interrupted mid-match; the static safety check and the chunk size are the real bound. Never accept a customer pattern without both.
- No vendor key format from memory beyond what the repo already carries (`copilot/models/redaction.py:64-65`); every other format comes from vendor documentation fetched in item 1 (verify-first) with URL and retrieval date in the runbook. A format that cannot be verified is not added.
- Same-named test directories shadow each other: use `packages/core/tests/content_detectors/` and `tests/security/content_redaction/` (the design's `classification` names would collide).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/classification/**
  - packages/core/tests/content_detectors/**
  - tests/security/content_redaction/**
  - docs/runbooks/content-classification.md
tier1: []
tier2_appends:
  - mkdocs.yml
must_not_touch:
  - packages/core/neurosphere_core/payload/**
  - packages/core/neurosphere_core/copilot/**
  - packages/core/neurosphere_core/observability/**
  - packages/core/neurosphere_core/audit/**
  - services/**
  - packages/contracts/**
  - pyproject.toml
  - uv.lock
```

## Implementation blueprint

Parallelization: item 1 first; items 2, 3 and 4 [P] (separate modules); item 5 after 2-4; items 6 and 7 after 5; item 8 last.

### Item 1 - Verify-first, models and protocol
- Deliverable: fetch the official documentation for each cloud and vendor credential format beyond the repo's existing ones (Azure storage and Event Hubs connection strings, GitHub token prefixes, any other format proposed) and record URL, retrieval date and the exact format in the runbook's "Sources" section; formats not verified are not coded. Then `classification/models.py` and `protocol.py` with the types in "Interfaces provided" and the kind-to-`sensitivity_category` mapping.
- Owned files: `packages/core/neurosphere_core/classification/{__init__,models,protocol}.py`, `docs/runbooks/content-classification.md` (sources section), `packages/core/tests/content_detectors/test_models.py`.
- Must NOT touch: existing redaction modules.
- Depends on: PRP-70 and PRP-99 merged.
- Acceptance criteria: credential categories cannot be configured to `keep` (validation error); every category string equals a PRP-99 `DetectedCategory` value (test against the generated enum); models are frozen and forbid extra fields.
- Tests: `packages/core/tests/content_detectors/test_models.py`.
- Pattern references: `lifecycle/policy.py:19-45`.

### Item 2 - Credential and secret detectors  [P]
- Deliverable: `classification/detectors/secret_detectors.py` (renamed 2026-11-24: the acc-guard secret-file rule refuses any path containing "credentials"): JWT, bearer, private-key blocks, connection strings with key material, passwords in URLs, credential phrasing (`password=`, `client_secret:`), verified vendor key formats, long opaque runs labelled `opaque_secret`.
- Owned files: `packages/core/neurosphere_core/classification/detectors/secret_detectors.py`, `packages/core/tests/content_detectors/test_secret_detectors.py`, `packages/core/tests/content_detectors/synth.py`.
- Must NOT touch: other detector modules.
- Depends on: item 1.
- Acceptance criteria: criterion 1 for each kind; `max_tokens=4096` and `prompt_tokens: 12` are not credentials (copy the negative lookahead idea at `copilot/models/redaction.py:56-62`).
- Tests: `packages/core/tests/content_detectors/test_secret_detectors.py`.
- Pattern references: `copilot/models/redaction.py:36-65`.

### Item 3 - Structured identifier detectors with checksums  [P]
- Deliverable: `classification/detectors/identifiers.py`: card (Luhn), IBAN (mod 97), US SSN (structure rules), email, phone (E.164 and separated national formats, flagged low precision), IPv4, IPv6, MAC, GUID.
- Owned files: `packages/core/neurosphere_core/classification/detectors/identifiers.py`, `packages/core/tests/content_detectors/test_identifiers.py`.
- Must NOT touch: secret_detectors module.
- Depends on: item 1.
- Acceptance criteria: criterion 2; dates, versions and plain counts are not phones (copy the guards at `copilot/models/redaction.py:68-75`).
- Tests: `packages/core/tests/content_detectors/test_identifiers.py`.
- Pattern references: `copilot/models/redaction.py:66-76`.

### Item 4 - Customer dictionaries and bounded customer patterns  [P]
- Deliverable: `classification/detectors/customer.py`: exact-term dictionary (case-folded, word-bounded, size cap) and `CustomerPattern` with the static safety check, length cap and a declared kind and `sensitivity_category`.
- Owned files: `packages/core/neurosphere_core/classification/detectors/customer.py`, `packages/core/tests/content_detectors/test_customer.py`.
- Must NOT touch: other detector modules.
- Depends on: item 1.
- Acceptance criteria: criterion 3 for loading; a catastrophic-backtracking pattern from a list of known shapes is refused with `pattern_unsafe`.
- Tests: `packages/core/tests/content_detectors/test_customer.py`.
- Pattern references: `payload/guard.py:178-202` (bounded scan).

### Item 5 - Redaction engine and versioned detector set
- Deliverable: `classification/engine.py` and `detector_set.py`: NFKC and zero-width normalization, chunking with overlap, overlap resolution (credentials first, longest span), per-mode replacement, findings with placeholder offsets, the time and size budget, fail-closed `RedactionFailed`, `default_detector_set()` with a version and configuration digest.
- Owned files: `packages/core/neurosphere_core/classification/{engine,detector_set}.py`, `packages/core/tests/content_detectors/test_engine.py`.
- Must NOT touch: detector modules (consume only).
- Depends on: items 2, 3, 4.
- Acceptance criteria: criteria 4, 5 and 6; idempotent (redacting a redacted text yields no new findings); a credential across a chunk boundary is found.
- Tests: `packages/core/tests/content_detectors/test_engine.py`.
- Pattern references: `audit/content_guard.py:87-131`.

### Item 6 - Labelled synthetic corpus and measurement
- Deliverable: a deterministic generator of labelled synthetic text (seeded, no real data) and a measurement test that computes precision and recall per detector, enforces the gate in row 6 and writes the table to the runbook through a small script under the tests folder (run manually; CI only checks the gate).
- Owned files: `packages/core/tests/content_detectors/{corpus,test_corpus_quality}.py`, `docs/runbooks/content-classification.md` (results section).
- Must NOT touch: engine code.
- Depends on: item 5.
- Acceptance criteria: criterion 8; the corpus is reproducible from its seed; no generated value is committed.
- Tests: `packages/core/tests/content_detectors/test_corpus_quality.py`.
- Pattern references: `packages/core/tests/lifecycle/lifecycle_helpers.py` (helper style).

### Item 7 - Security negative suite
- Deliverable: tests that run the whole corpus under caplog at DEBUG and assert no matched text in any record, exception or `repr`; that injected detector exceptions yield `RedactionFailed` with no text; that no output contains a hash of a match (compute SHA-256 and hex prefixes of each generated secret and grep).
- Owned files: `tests/security/content_redaction/**`.
- Must NOT touch: shared `tests/security/authz` harness.
- Depends on: item 5.
- Acceptance criteria: criteria 1, 4 and 7 proven end to end.
- Tests: `tests/security/content_redaction/test_no_secret_leak.py`, `test_fail_closed.py`.
- Pattern references: `tests/security/authz/test_admin_producers_secrecy.py`.

### Item 8 - Integration and close-out
- Deliverable: runbook complete (detectors, kinds, modes, coverage statement, measured table, sources, how a customer adds dictionaries and patterns safely); `mkdocs.yml` nav line; follow-up issue text for consolidating the four rule sets; changelog fragment `changelog.d/PRP-101-sensitive-information-detectors-and-redaction.md`; Tier-3 regeneration per reference section 2; completion note.
- Owned files: runbook, `mkdocs.yml` (one line), this PRP file, changelog fragment, Tier-3 files.
- Depends on: items 1-7.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/content_detectors tests/security/content_redaction packages/core/tests/test_import_boundaries.py tests/docs/test_nav_allowlist.py
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
None: a new library with no caller in this PRP, no settings, no stored data. Rollback is reverting the PR; nothing imports it until PRP-103.

## Live and open gates
None. No external call is made; the model-based detector is not built (GD-6).

## NOT building
- Detection of person names, postal addresses, free-text health, legal or financial content, or intent. Without a model this is not feasible deterministically (design section 8 item 4); the product says "structured identifiers only".
- A model-based or external classification service (GD-6); in Government nothing is sent outside the boundary.
- Any claim of DLP coverage, Purview parity or compliance; endpoint or browser DLP is out of reach for a server-side product (design section 8 items 2 and 5).
- Running on ingest, storing or showing anything (PRP-103, PRP-102, PRP-104).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1-3 are GD decisions made 2026-11-16, rows 5-7 are ASSUMPTIONS for plan approval)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | worktree-agent-aed05eadf2560d344 @ 69df73fb | review APPROVE; gates green (content_detectors + import boundaries + tests/docs 228 passed); orchestrator added Match category/confidence validation and pulled the mkdocs nav line forward from item 8 |
| 2 | merged | worktree-agent-a5559d51e4828bd4b @ 479f3d53 + rework worktree-agent-a0e04d02db516eedb @ 36c22c2e | review CHANGES REQUIRED (criterion 6 validator gaps: lowercase sk- slug, bearer after `_`, glued JWT, `xsig=`, long URL userinfo; `user@server` URL password); one rework round, confirmed by re-running the reviewer's probe (all detected, output validator-clean, idempotent); 345 passed after merge |
| 3 | merged | worktree-agent-a123dc9f196a65037 @ 0ae2ead7 | review APPROVE (follow-ups: IBAN country/length table, IPv6 hex-word compressed forms); 203 passed after merge |
| 4 | merged | worktree-agent-a24fbf0e798524465 @ efeef77e + rework worktree-agent-a2ee628f73be779bf @ 2e567d50 | review CHANGES REQUIRED (cost model ignored nesting/wrapper repeats: accepted patterns 8-30x over the documented bound); one rework round (`too_deep`, depth 2, MAX_COMPLEXITY 160, honest bound 250 ms per 64 KiB per pattern, dictionary 2 s), confirmed by the orchestrator re-running the reviewer's patterns (all refused); 470 passed after merge |
| 5 | merged | worktree-agent-a26ea51110909ef2c @ 7ea2f11f | review CHANGES REQUIRED (invisible-char strip list was a subset: variation selectors/tags split keys past detection); orchestrator fixed (full Default_Ignorable set) and confirmed: new 56-case test fails on the old engine, passes now; 599 passed + 1 strict xfail (chained assignment leak in item 2's detector, fix-forward lane in flight) |
| 6 | merged | worktree-agent-a3791096476f50fd3 @ 1425c2d3 | review APPROVE (shared pass with item 7); its gate caught two JSON-escaped leaks (bearer after escaped tab, escaped-quote client secret), fixed forward with the operator lane (5e5764dd); at merge the orchestrator gated the chained context too, pinned the table digest and regenerated the table: every gated category recall 1.000 end to end |
| 7 | merged | worktree-agent-ac7fd81ae7a69e615 @ 719aea66 | found a fail-open (forged Match offsets bypassing __post_init__); orchestrator fixed `engine._validated`, the 8 strict xfails now pass; review APPROVE (shared pass with item 6; engine rebuild now reuses checked offsets, f465c697); 741 passed |
| 8 | merged | prp-101-detectors-and-redaction (orchestrator) | runbook complete (detectors, configuration, customer patterns, known limits), mkdocs nav (pulled forward to item 1), changelog fragment, follow-up issues #408 and #409, completion note |

Fix-forward lanes (not numbered items): chained credential assignments (worktree-agent-af9ddd3e901080a39 @ 02e7fc1b, found by item 5); assignment operators `:=`/`=>`/`->`/`<-`/`==`, CLI flags and JSON-escaped text (worktree-agent-af739a51728948b1a @ 50b79646, found by an orchestrator probe and item 6's gate).

## Completion note (filled at ship)
- Date and PR: 2026-11-24, PR #407. CI green on b984d592: 33 check runs succeeded, 1 skipped (deploy to Pages), including CodeQL after fixing one error and two warnings in the new tests. Merge commits on the integration branch: items 1-7 merges plus fix-forward merges (`git log --oneline origin/main..prp-101-detectors-and-redaction`). One pushed commit (5a9a7000, the item 8 docs and completion note) carries a stale message, "test(classification): gate every corpus context...", because the message file was not rewritten. The content is correct; it was left as is (no force-push), and squash-merge drops it.
- Deviations:
  - Item 2's module is `detectors/secret_detectors.py`, not `credentials.py`: the acc-guard secret-file rule refuses any path containing "credentials".
  - `Redacted.set_version` follows the PRP-99 `detector_set_version` slug (`ns-detectors-1.0.0`), not x.y.z.
  - `Finding.offsets` mirrors `DetectionFinding.spans` (at most 64 entries); PRP-103 maps it.
  - Built-in detectors run on the whole text; only customer detectors are chunked. The reason is that private-key blocks exceed any sensible overlap. The overlap must be at least 2W+2.
  - The customer-pattern safety check is stricter than the PRP implied. It refuses every unbounded repeat, any bound above 100, nesting deeper than 2 and a cost above 160. The true bound is 250 ms per 64 KiB per pattern, not the first draft's 50 ms.
  - Added beyond the plan:
    - full Default_Ignorable stripping
    - a post-redaction self-check
    - re-validation of detector match offsets in the engine
    - the low-confidence bare `sk-` rule (criterion 6 requires it, so ordinary slugs such as `disk-encryption-set-configuration` are over-redacted)
  - The mkdocs nav line moved from item 8 to item 1, to keep the docs nav test green from the first push.
- Descoped items: none.
- OPEN gates: none. No live gate exists; the PRP makes no external call.
- Env vars for the operator: none. The library has no settings.
- Follow-up issues:
  - #408: consolidate the four existing rule sets (Clarification 8).
  - #409: precision and hardening follow-ups (IBAN, IPv6 and opaque precision; glued `sk_` keys; escaped-quote values; combining marks; finding-count cap; customer cost model; PRP-103 budget headroom).
- Product check: no. This is a library with no caller. An operator cannot configure dictionaries, patterns or redaction modes without code until PRP-103 (capture policy and ingest edge) and PRP-105 (policy `content_rule`) wire it in, as planned.
