# ADR-0004: Contract versioning, code generation and drift check

- Status: accepted (PRP-01 item 6; confirmed by the PRP-01 review pass)
- Date: 2026-10-10
- Deciders: Frank Garofalo
- Relates to: PRP-01 Clarifications 2, 3, 4 and 6; ADR-0002 (stack pins); gate G08

## Context

PRP-01 makes JSON Schema 2020-12 under `packages/contracts/schemas/` the single source of
truth for every wire and persisted document. Pydantic v2 and TypeScript bindings are
generated from it and committed, so 26 downstream PRPs build against one shape. That only
holds if (a) the schemas evolve under a rule consumers can rely on, (b) generation is
reproducible byte-for-byte, and (c) CI notices when someone edits a schema without
regenerating, or hand-edits a generated file. Generators also disagree with each other and
with JSON Schema on `oneOf`, `const` and conditionals (PRP-01 gotcha), so the bindings must
not be trusted by inspection.

## Decision

### Layout: one directory per major version

- Every schema is `packages/contracts/schemas/<area>/v<major>/<name>.schema.json`. Areas
  today: telemetry, cost, catalog, actions, audit, scope, query, chart, recommendations,
  evaluation, deployment, connectors, errors. All are `v1`.
- `$id` is `https://neurosphere.invalid/schemas/<area>/v<major>/<name>.schema.json`, a
  reserved-domain placeholder that is never resolved. Every `$ref` is a relative file
  reference (`common.schema.json#/$defs/x`, `../../actions/v1/actor.schema.json`); remote
  `$ref` is forbidden and the generator refuses one.
- File names are kept as authored (catalog uses snake_case such as `agent_version`, other
  areas kebab-case such as `telemetry-event`). Generated module paths mirror the schema path:
  `neurosphere_contracts.<area>.v1.<name_with_underscores>` and
  `packages/contracts/ts/src/<area>/v1/<name>.ts`.
- Data files beside the schemas (`transitions.json`, `confirmation-hash.json`,
  `error-codes.json`, `id-corpus.json`) and `examples/` folders are not schemas and are not
  generated from.

### Additive-only within a major

Inside `v1` a change is allowed only if every document valid before stays valid after, and
every consumer built against the old bindings keeps compiling:

- allowed: a new **optional** property (nullable or with a default), a new `$defs` entry, a new
  schema file, a new enum value only on fields documented as open-ended, a looser bound only
  when no consumer relies on the tighter one, description changes;
- not allowed (needs `v2`): removing or renaming a property, changing a type, making an
  optional property required, tightening a pattern or bound, removing an enum value, changing
  `additionalProperties` or a `$ref` target's shape.

Every object keeps `additionalProperties: false` and the generated Pydantic models set
`extra="forbid"` (Clarification 6). That makes "add an optional field" a coordinated change:
writers must not emit the new field until readers run the regenerated bindings.

### Breaking changes and deprecation

- A breaking change creates `<area>/v2/` alongside `v1`; `v1` stays generated and supported.
- Deprecating a field or schema in `v1`: add `"deprecated": true` and a description naming
  the replacement and the PRP that removes it. Readers keep accepting it; writers stop
  emitting it.
- A `v1` schema is removed only after (1) its `v2` replacement shipped, (2) no persisted
  document of the old major remains or a migration has run, and (3) an ADR records the
  removal. No stability beyond these rules is promised ("no future refactoring" is not a
  claim this project makes).

### `schema_version`

- Required on every persisted and wire document (Clarification 4).
- Format `1.x.y`, the canonical pattern being
  `^1\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$` (no leading zeros). The major equals the
  directory; `x` increments on each additive change; `y` on description-only or clarifying
  changes.
- Readers accept any `1.x.y`; a reader that sees `2.x.y` in a `v1` channel rejects it with
  `invalid_schema`.

### Generators and pins

| Tool | Pin | Licence | Scope | Source |
|---|---|---|---|---|
| datamodel-code-generator | 0.83.0 | MIT | dev (Python codegen) | https://pypi.org/project/datamodel-code-generator/ |
| json-schema-to-typescript | 16.0.0 | MIT | dev (TS codegen) | https://www.npmjs.com/package/json-schema-to-typescript |
| typescript | ~6.0.0 (6.0.3 locked) | Apache-2.0 | dev (typecheck) | ADR-0002 |
| vitest | ^4.0.0 (4.1.11 locked, same range as `frontend/`) | MIT | dev (test runner for item 7) | ADR-0002 |
| ruff | workspace pin (0.16.x) | MIT | dev (formats generated Python) | ADR-0002 |

Pins are exact for the two generators: datamodel-code-generator in the `dev` dependency group
of `packages/contracts/python/pyproject.toml`, json-schema-to-typescript in the
`devDependencies` of `packages/contracts/ts/package.json`, both locked in `uv.lock` and
`pnpm-lock.yaml`, and repeated as constants in `packages/contracts/scripts/generate.py`.
`test_generate.py` fails if any of these five places disagree or if this table is not
updated; `generate.py` refuses to run when the installed version differs from the pin.

Transitive licences observed from installed metadata on 2026-10-10: datamodel-code-generator
pulls argcomplete (Apache-2.0), black (MIT), genson (MIT), inflect (MIT), isort (MIT), jinja2
and markupsafe (BSD-3-Clause), more-itertools (MIT), mypy-extensions (MIT), **pathspec
(MPL-2.0, dev-only, accepted under the ADR-0002 dev-only rule)**, pytokens (MIT), pyyaml (MIT)
and typeguard (MIT). json-schema-to-typescript pulls @apidevtools/json-schema-ref-parser,
prettier, lodash, js-yaml, minimist and tinyglobby, all MIT. None ship in a runtime artefact.
The licence register (`docs/licenses.md`, ADR-0002 appendix) must be regenerated with
`python scripts/licenses_report.py` when these land (PRP-00 owns that file).

### Deterministic generation

`python packages/contracts/scripts/generate.py`:

1. discovers `*/v*/*.schema.json` in sorted order;
2. stages projected copies (below) into a temporary directory, renaming `x.schema.json` to
   `x.json` and rewriting relative `$ref` targets to match, so module names are clean;
3. runs datamodel-code-generator (`--no-allow-remote-refs`, `--disable-timestamp`,
   `--extra-fields forbid`, a fixed header, strict `str`/`int`/`float`/`bool`, `date-time` and
   `date` kept as pattern-checked strings) and formats the result with the workspace ruff;
4. runs json-schema-to-typescript through `scripts/json2ts.cjs` with the HTTP resolver
   disabled, `additionalProperties: false`, fixed prettier options and a fixed banner;
5. writes LF-only files and a generated `ts/src/index.ts` that exports each root type by
   title and each schema as a namespace (`CatalogAgentVersionV1`).

Every generated file starts with `GENERATED - do not edit.` No timestamps, absolute paths
or generator command lines appear in output. Running the script twice produces no diff.

### Generator disagreement (oneOf, const, conditionals) and the mitigation

Neither generator implements `if`/`then`/`else`/`not`, and both mistranslate them:
json-schema-to-typescript turns a conditional-only `allOf` member into
`{[k: string]: unknown}` and intersects it with the object, re-opening a closed object;
datamodel-code-generator distributes an `allOf` of `anyOf` branches into a `RootModel`
union of numbered multiple-inheritance classes while still dropping the rule. Mitigation:

- Both generators receive a **shape projection**: conditionals removed, `allOf` members with
  no `type`/`$ref` dropped, `$defs` that became annotation-only dropped. Shapes, required
  lists, enums, `const`, patterns, bounds and nullability are kept. For TypeScript, an
  annotation-only subschema ("any JSON") becomes `unknown` and a `$defs`-only library root
  becomes `never` via the generator's `tsType` escape hatch.
- **JSON Schema stays authoritative.** Generated models are a typed convenience, not the
  validator of record. Ingress paths validate against the JSON Schema (jsonschema 4.26) as
  well as the model; PRP-01 item 7 runs the same golden fixtures through JSON Schema,
  Pydantic and TypeScript.
- Measured on the in-repo examples on 2026-10-10: the Pydantic models accept 83 of 83
  valid examples and reject 112 of 163 invalid ones. All 51 they accept are cross-field
  conditional rules (for example estimated cost without `price_version`, inferred edge
  without evidence, audit chain head with `previous_hash`). The unprojected generator output
  rejected the same 112. Code that needs those rules must validate against the schema.
- Generated Python carries `# pyright: reportAssignmentType=false, reportInvalidTypeForm=false`:
  datamodel-code-generator emits `constr(...)` dict keys for `patternProperties` and literal
  defaults on `RootModel`-typed fields, which pyright rejects although Pydantic accepts them.
  The suppression covers generated files only.

### Python `$` matches before a trailing newline

In Python `re`, `$` also matches just before a final `\n`, so `re.match(r"^[a-z]+$", "abc\n")`
succeeds; ECMA-262, which JSON Schema patterns follow, does not. The Python `jsonschema`
library uses `re.search` and therefore **accepts** `"abc\n"` against such a pattern;
Pydantic (Rust regex in pydantic-core) rejects it. Any hand-written Python check of a
canonical ID, pseudonym or other anchored pattern must use `re.fullmatch` (or `\Z`), and
contract tests must include trailing-newline cases so the two engines are compared.

### Where the drift check runs

A new workflow, `.github/workflows/contracts.yml`, runs on push to `main`, on pull requests
and on demand. It installs the locked toolchains, runs
`python packages/contracts/scripts/generate.py --check` (regenerates into a temporary
directory and exits 1 on any added, removed or changed file), then `pytest
packages/contracts/scripts` with `NS_CODEGEN_REQUIRED=1` (a missing generator fails instead of
skipping) and the TypeScript typecheck. No step suppresses a failing exit code. A separate
file was chosen over editing `ci.yml` because PRP-01 item 6 does not own `ci.yml`, and the
existing `python` job installs neither Node nor the generator dev group. In `ci.yml`, the
idempotence test in `test_generate.py` skips with a reason; the other tests run.

## Consequences

- Adding a field means: edit the schema, bump `schema_version` minor in its documentation,
  run `generate.py`, commit schema and bindings together. CI rejects a schema-only commit.
- A generator upgrade is a reviewed change: bump the pin in all five places, regenerate,
  inspect the diff, and repeat the examples smoke comparison.
- Schema defects found while building the generator are reported to the schema owners, not
  patched here. At 2026-10-10 nine schemas in six areas still use the looser
  `^1\.[0-9]+\.[0-9]+$` for `schema_version` (catalog `common`, which every catalog schema
  references; actions intent, approval and transitions; audit; errors; both deployment
  schemas; connectors) instead of the canonical pattern above. Tightening it is a pattern
  change, so it must land before any `v1` document is persisted.

## References

- JSON Schema 2020-12: https://json-schema.org/draft/2020-12 (observed 2026-10-10).
- datamodel-code-generator 0.83.0: https://pypi.org/project/datamodel-code-generator/
  (released 2026-09-24, observed 2026-10-10).
- json-schema-to-typescript 16.0.0: https://www.npmjs.com/package/json-schema-to-typescript
  (released 2026-08-28, observed 2026-10-10).
- Python `re` `$` semantics: https://docs.python.org/3/library/re.html (observed 2026-10-10).
- PRP-01: `PRPs/active/PRP-01-contracts-and-schemas.md`.
