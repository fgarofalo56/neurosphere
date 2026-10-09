# PRPs

Product Requirement Prompts: PRD slice + curated codebase context + runbook +
executable validation gates. One PRP is one `/prp:prp-execute` session.

| Path | Meaning |
|---|---|
| `PRP-MASTER-neurosphere.md` | **Start here.** Run order, waves, model per PRP, phase gates, binding decisions |
| `backlog/` | Not started. Named `PRP-NN-<kebab-name>.md` |
| `active/` | Being executed (the executor moves the file here) |
| `shipped/` | Merged, PR open, CI green; completion note filled |
| `templates/prp-template.md` | The kit template every PRP follows |

Rules that apply to every PRP here:

- The preamble in `PRP.md` §1–§3 (delivery contract, stack and boundaries,
  contracts before implementations) is inherited by reference and is binding.
- Each work item declares owned files and must-not-touch files. Items that share
  no files and no dependency edge are `[P]` and may run as parallel worktree lanes
  (WIP limit 4).
- Gate command, with forward slashes:
  `powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast`
  (full mode before merge). Feature-specific checks are listed per PRP.
- Items under `scripts/gates/` need `NS_LIVE_APPROVED=1` and operator approval.
  If a live gate did not run, the PRP's completion note says **OPEN**, and
  `docs/RESEARCH-AND-GATES.md` is updated.
- `scripts/validate_planning.py` fails if a PRP in the master index is missing,
  if a backlog file is not in the index, or if an NS requirement has no PRP.
