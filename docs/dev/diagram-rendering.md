# Rendering Mermaid diagrams locally

Contributor note. The compliance plan diagrams in `docs/compliance/plans/diagrams/` are
rendered with the pinned Mermaid CLI:

```bash
pnpm dlx @mermaid-js/mermaid-cli@12.0.0 -i <name>.mmd -o <name>.svg
```

`scripts/render_mermaid.py` trims SVG coordinates to two decimals so the repository PII scan
does not misread long digit runs. Keep the fenced block in each plan identical to its
`diagrams/<name>.mmd` source (`tests/compliance/test_plan_mermaid_matches_source.py` checks it).

## Machine-specific workaround

If puppeteer's own headless shell is not installed on your machine, point puppeteer at an
installed Google Chrome through a puppeteer config file passed with `-p`:

```json
{ "executablePath": "C:/Program Files/Google/Chrome/Application/chrome.exe" }
```

The CLI and version stay the pinned ones. This is a local convenience, not part of the
compliance evidence.
