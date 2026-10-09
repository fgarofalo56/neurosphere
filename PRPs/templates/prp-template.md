---
name:
status: backlog   # backlog | active | shipped
review: none      # required | none  (required = one reviewer pass, approve unless blocking)
created:
---

# PRP: <feature name>

## Goal
<one paragraph: what ships, for whom, why now>

## Acceptance criteria
<measurable, testable outcomes — Given/When/Then where useful>
- [ ]

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
|   |          |                 |          |

## Context manifest (curated codebase intelligence)

### Files that matter
<path — why it matters>

### Patterns to match
<path:lines — what it demonstrates; the implementer copies THIS style>

### Conventions
<naming, error handling, test structure — as practiced, verified by reading>

### Gotchas
<footguns, load-bearing hacks, version constraints, deprecated patterns present in the code that must NOT be copied>

### External references
<specific doc URLs and sections, never "see the docs">

## Implementation blueprint
<ordered work items, each self-contained. Items sharing no files and no dependency edge are parallel candidates — mark them [P].>

### Item 1 — <name>  [P?]
- Deliverable:
- Owned files (may edit):
- Must NOT touch:
- Depends on: <none | item #>
- Acceptance criteria:
- Pattern references: <from manifest>

## Validation gates
<the exact commands that define done — default `powershell -NoProfile -ExecutionPolicy Bypass -File .claude/hooks/run-tests.ps1 -Fast`, plus feature-specific checks (manual QA steps, migration dry-runs). Forward slashes are deliberate: implementer and verifier run this through bash, which eats backslashes and exits `127`. The full suite runs in CI.>

## Definition of Ready check
- [ ] Every item has owned files declared
- [ ] Every item has acceptance criteria and pattern references
- [ ] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed

## Completion note (filled at ship)
<date, merged commits, deviations from blueprint + why, descoped items, follow-ups>
