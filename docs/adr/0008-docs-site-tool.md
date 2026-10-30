# ADR-0008: Documentation site tool

- Status: accepted; implemented by PRP-25 item 1
- Date: 2026-10-30
- Deciders: Frank Garofalo
- Relates to: `docs/adr/0002-stack-pins.md` (MkDocs Material row), `docs/RESEARCH-AND-GATES.md` (toolchain support line), PRP-25

## Context

`docs/adr/0002-stack-pins.md` pinned MkDocs Material 9.7 with an end of life (EOL) of 2026-11-05 and asked PRP-25 to evaluate Zensical (MIT, same authors) before building the site. This ADR is written before any site configuration is committed. The site must publish an explicit allowlist of pages (not the whole `docs/` tree, which also holds evidence and internal planning), build in strict mode, and deploy to GitHub Pages from CI.

## Options

1. **MkDocs Material 9.8.x** (`mkdocs-material`, MkDocs build engine, `mkdocs.yml`).
2. **Zensical 0.0.x** (`zensical`, reads `mkdocs.yml` or `zensical.toml`).

## Criteria

EOL and maintenance, migration cost, search, admonitions, SVG diagram handling, licence, strict build and link validation.

## Evidence (observed 2026-10-30)

| Criterion | MkDocs Material | Zensical |
|---|---|---|
| Version and status | 9.8.0 uploaded 2026-10-24; PyPI classifier "Development Status :: 7 - Inactive" (https://pypi.org/project/mkdocs-material/) | 0.0.73 uploaded 2026-10-26; classifier "Development Status :: 3 - Alpha" (https://pypi.org/project/zensical/) |
| EOL | The 9.8.0 README states EOL on **2027-05-05**, with critical fixes and security updates until then. https://zensical.org/upcoming-changes/ states a six-month extension from the earlier 2026-11-05 date. The 2026-11-05 date in ADR-0002 is therefore superseded | No EOL. https://zensical.org/upcoming-changes/ states that Zensical 0.1.0 "will begin a dependable release line" on 2026-11-05; until then the 0.0.x line is pre-release |
| Licence | MIT (PyPI `license_expression`) | MIT (PyPI classifier; upstream states it remains MIT) |
| Migration cost | None; it is the baseline | Reads the existing `mkdocs.yml` (upstream migration guide: https://zensical.org/docs/compatibility/mkdocs/migration/). Plugin compatibility is the risk and is not fully covered |
| Strict build | Measured: a scratch project with a broken link and a missing image aborted with "Aborted with 2 warnings in strict mode!" using `mkdocs build --strict` (mkdocs-material 9.8.0) | Measured: `zensical build --strict` on the same scratch project aborted ("Aborted because --strict flag is set") using zensical 0.0.73. The warning detail was not shown, so link diagnostics are less informative |
| Search, admonitions, SVG | Built in search; `admonition` Markdown extension; SVGs are plain files referenced with `![](x.svg)` and are link-validated | Not measured in this item beyond the scratch build above; upstream documents compatibility but this ADR does not claim parity |

Not verified: Zensical plugin coverage for our needs, Zensical search behaviour on the real site, and any Material feature we may add later. No claim is made about them.

## Decision

Use **MkDocs Material 9.8.x**, pinned to `mkdocs-material==9.8.0`, with a single `mkdocs.yml`. Reasons: it is the only option with a stable (non-alpha) release line and a strict build whose warnings name the offending link, and its EOL is 2027-05-05, six months later than ADR-0002 recorded. Zensical is the successor and is deliberately kept cheap to adopt: the config is plain `mkdocs.yml` with no plugins, so `zensical build --strict` reads it unchanged.

Revisit after Zensical 0.1.0 ships (announced for 2026-11-05) and no later than 2027-02-05, three months before the MkDocs Material EOL. Only one config file (`mkdocs.yml`) exists; `zensical.toml` must not be added alongside it.

## Commands

Install is ad hoc (root `pyproject.toml` is not changed by this item):

- Build with strict mode (this is also the link check: `validation` in `mkdocs.yml` sets not-found, absolute and anchor link problems to `warn`, and strict turns warnings into failure):
  `uv run --no-project --with mkdocs-material==9.8.0 mkdocs build --strict --site-dir temp/site`
- Link check, same command. It validates internal links, images and anchors across published pages only. External URLs are not fetched.
- Tests: `uv run pytest tests/docs -q`

## Consequences

- The publish set is the nav allowlist in `mkdocs.yml`, and `exclude_docs` keeps every other file out of the built artifact. `docs/evidence/` and internal planning are never published. The public assistant (PRP-25 item 4) indexes the built site, not the repository.
- Follow-up: add `mkdocs-material` to a docs dependency group in the root `pyproject.toml` (owned by another item) so Dependabot tracks it; the workflow pin must then move with it.
- Follow-up: PRP-25 items 2 and 3 extend the nav and `exclude_docs` allowlist when `docs/reference/`, `docs/runbooks/` and `docs/walkthroughs/` exist.
- `docs/RESEARCH-AND-GATES.md` and ADR-0002 still record the 2026-11-05 EOL; correcting them is out of this item's ownership.
- This ADR makes no FedRAMP, ATO or parity claim.
