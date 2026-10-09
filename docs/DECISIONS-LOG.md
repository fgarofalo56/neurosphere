# Decisions log

Operator decisions that bind the build but are not architecture (those are ADRs
in `docs/adr/`). Newest first. Each entry: date, decision, options considered,
why, and what it changes.

## 2026-10-08

| # | Decision | Options considered | Why | Effect |
|---|---|---|---|---|
| D1 | Repository is **private** | keep public; private; private + move to HouseGarofalo org | Government-governance product plan; operator's default is private for new repos | Visibility flipped the same day; secret-scan comment updated; pushes still treated as publication |
| D2 | Harness is the **orchestrated-PRP kit only** | kit only; kit + tasks.json; tasks.json only | One convention across the operator's repos | ADR-0003; PRP.md §5 removed |
| D3 | Legacy Kong/DAB/Artemis scaffold **deleted** | delete; delete code and keep one archive; move to docs/archive | Git history (`21ab22b`, `9fbf5f4`) already preserves it | `data/`, `services/`, `client/`, `tools/`, demo docs, `docs/archive/` removed |
| D4 | **One PRP per epic**, 27 PRPs | per epic; per phase chunk (~9) | Each PRP stays a single session with disjoint-ownership items | `PRPs/backlog/PRP-00..27` |
| D5 | Stack defaults accepted, with research-driven adjustments | accept; accept with changes | Support windows and licences | ADR-0002: Node 24 not 22, TS 6.0.x not 7, Helm 4, MkDocs Material 9.7 with Zensical evaluation, no @cosmograph, vega-interpreter |
| D6 | Model policy: **Sonnet default, Opus for risky PRPs, Haiku verify** | Sonnet default + Opus risky; Opus everywhere; Sonnet everywhere | Cost rules; risk concentrated in contracts, authz, actions, MCP | Master index `model:` column |
| D7 | **Commercial Azure subscription available**, live gates approved per PRP; Government stays an open gate | commercial per-PRP; none until told; both clouds | Operator has MCAPS credits; no Government subscription | Live items end each PRP, gated by `NS_LIVE_APPROVED=1` |
| D8 | Local dev is **Docker Compose with Azure emulators** | compose; in-memory fakes only; compose + devcontainer | Same SDKs as production, no paid calls | `docker-compose.yml`; devcontainer deferred to PRP-03 |
| D9 | **G03 emulator evidence exits Phase 0**; live benchmark required before PRP-10 merges | emulator exits; live before wave 4 | Unblocks waves 4 without paid work; first real partition logic is PRP-10 | Master index wave gates |
| D10 | **Video render descoped** to PRP-27, budget-gated; PRP-26 ships deck + scripts | descope; include | Needs approved generation budget | PRP-26/PRP-27 split |
| D11 | `packages/core` is the shared Python library for api and workers | shared lib; duplicate per service | Workers must not import the API app | Repo layout in master index |
