# Reference

> Generated file. Do not edit; run `uv run python docs/reference/generate.py`.
> Source commit: `967d685b31dc55da1b2685e2824898c27cb8cb63`. Generated: 2026-11-16.
> Sources: see each page.

Generated reference pages. They are rebuilt from committed inputs and checked for drift by `tests/docs/test_reference_coverage.py`.

| Page | Contents | Count |
|---|---|---|
| [API reference](api.md) | Every REST operation plus the error taxonomy | 202 operations |
| [Connector SDK (Python)](sdk-python.md) | Public symbols of the Python SDK | 31 symbols |
| [Connector SDK (TypeScript)](sdk-ts.md) | Exports of the TypeScript SDK | 41 symbols |
| [MCP reference](mcp.md) | Tools with scope requirements, and resources | 7 tools |

## Regenerating

Run `uv run python docs/reference/generate.py`. Pages are stamped from `SOURCE_STAMP.json`, which records a hash of the inputs and the last commit that touched them; it is refreshed only when the inputs change, so a second run produces no diff.
