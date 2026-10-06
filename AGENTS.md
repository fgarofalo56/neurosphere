# AGENTS.md

Guidance for AI coding agents working in this repository. Claude Code reads
`CLAUDE.md`; other agents (Codex, Cursor, Gemini CLI, Aider) read this file.
See `CLAUDE.md` for the full operator notes — this is the short version.

## What this project is

NeuroSphere — enterprise AI agent governance, catalog, telemetry, and recommendation platform (Azure-first, FedRAMP-aligned, Purview-integrated)

**Stack:** unknown

## Conventions

- Match the existing code style in this repo.
- Run the project's existing lint + tests before committing.

## Always-pass gates (do not bypass)

- Lint / format must pass before any commit. Never bypass hooks (`--no-verify`).
- Tests must be green for the touched surface before shipping.
- Fix root causes — do not paper over a failing check.
- Never read or commit secrets (`.env`, `secrets/`, keys). Use env vars.

## Common tasks

See `README.md` → "Develop" for the exact lint / test / run commands.

_Scaffolded by ATLAS Coding Manager (Forge) on 2026._
