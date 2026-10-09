# ============================================================
#  Per-repo gate commands (PowerShell edition).
#  THIS IS THE ONE FILE YOU CUSTOMIZE.
#  This is the only per-repo input verify-gates.ps1 takes, on every platform.
#  config.sh is NOT an alternative to it: config.sh no longer feeds a gate
#  runner at all, it only carries LINT_FILE_CMD for the bash post-edit-check.
#
#  A gate command that does no work and exits 0 is reported as a full PASS.
#  The runner reads exit codes; it cannot tell "ran and passed" apart from
#  "silently did nothing." Prefer commands that fail loudly on no-op.
#
#  AN EMPTY GATE COMMAND IS A FAILURE, not a skip. verify-gates.ps1 exits 1
#  if a gate it expects has nothing to run, because "no command" and "passed"
#  must never look the same to an automated caller. If this repo legitimately
#  has no such gate, say so explicitly in $OptionalGates at the bottom.
#
#  This file is DOT-SOURCED by verify-gates.ps1, so anything it does lands in
#  the runner's own scope. Keep it to variable assignments: no Set-StrictMode,
#  no Set-Location, no side effects. In particular do not assign $Mode or
#  $ProjectDir - the runner snapshots those before dot-sourcing precisely
#  because a config that reassigns them would silently retarget the run.
#
#  ONE COMMAND PER GATE. A gate is judged by its exit code when it reports one.
#  When it reports none - which is MOST pure-PowerShell commands, since native
#  executables and `exit` set $LASTEXITCODE and most cmdlets do not - any error
#  record fails the gate instead. ("Cmdlets NEVER set it" is the tempting
#  shortcut and it is false: Invoke-Pester sets it deliberately, measured on
#  both hosts.) When a command DOES report a code, only an explicit Write-Error
#  overrules it:
#      'cmd /c "exit 0"; Write-Error boom'      ->  scored as FAIL
#      'Get-Item missing-file'                  ->  scored as FAIL
#      'cmd /c "exit 0"; Get-Item missing-file' ->  scored as PASS
#  That last one is a deliberate tradeoff: catching it would also fail every
#  wrapper that does routine -ErrorAction SilentlyContinue cleanup before its
#  real work, which is normal and correct. Those records are not lost - the run
#  prints a non-failing `note:` line naming how many went unscored. Expect that
#  line to be ON permanently for an inline Invoke-Pester gate on PS 5.1: module
#  autoload leaves two records behind even when the suite is all-green.
#
#  Do not reason about which branch your gate lands in. End it in a real exit
#  code and the question does not arise.
#
#  Also NOT caught is an earlier NATIVE failure, because PowerShell 5.1 keeps
#  only the last $LASTEXITCODE and a failing executable writes no error record:
#      'cmd /c "exit 1"; cmd /c "echo done"'    ->  scored as PASS
#  If a gate needs several steps, put them in a script and run that script as a
#  CHILD PROCESS, so its exit code is real:
#      $TestCmd = 'powershell -NoProfile -File .\scripts\test-gate.ps1'
#
#  A command that legitimately writes an error record and still means "pass"
#  has three remedies, all measured on both hosts:
#      - end the command with $Error.Clear()
#      - use -ErrorAction Ignore (SilentlyContinue does NOT work - it still
#        appends to $Error)
#      - report a ZERO exit code: a trailing native command that exits 0, or
#        `exit 0` inside an &-called .ps1, which sets $LASTEXITCODE without
#        ending the run. Either one moves the gate to the "reported a code"
#        rule above, and that rule ignores everything that is not a
#        Write-Error. It must be ZERO - a trailing non-zero is read as the
#        gate's answer and hard-fails it - and `exit 0` must live in a .ps1,
#        not in the gate command string itself, where a bare `exit` ends the
#        whole run (see below).
#  What does NOT rescue a command is Write-Error itself: it is read whatever the
#  exit code says. And only a CHILD PROCESS keeps a record out of the runner's
#  $Error entirely - dot-called or &-called, the script shares it.
#
#  Gate COMMANDS run in the runner's process too, so `exit` inside one ends the
#  whole run rather than the gate. The runner detects that and fails the run
#  instead of reporting a pass, but the gates after it still never execute -
#  use a child process with a real exit code, not a bare `exit`. Never call
#  [Environment]::Exit in a gate command: it skips the runner's guard entirely
#  and can end the process at 0 with nothing verified.
# ============================================================

# Fast per-file lint (runs automatically after every edit via hook; file path is appended)
$LintFileCmd = "uv run ruff check"
# $LintFileCmd = "npx eslint"                        # Node
# $LintFileCmd = "uv run ruff check"                 # Python (uv)
#
# FAIL ON ERRORS ONLY, matching the full lint. No `--max-warnings 0` here: a
# per-file lint stricter than $LintAllCmd reports LINT FAILED on every edit to
# a file with pre-existing warnings - code the full gate passes - and trains
# everyone to ignore the hook. The per-file lint previews the gate; it should
# ask the gate's question.
#
# If $LintAllCmd uses eslint `--cache`, do not let this command near that cache
# file: eslint run WITHOUT --cache deletes the cache at its location, and one
# run WITH it can store a stale verdict when an edit lands mid-run. Point the
# per-file lint at a private `--cache-location` and leave --cache off.
# claude-tools' .claude/hooks/lint-file.ps1 records the measurements.

# Which files the per-file lint above is handed. THREE DISTINCT STATES:
#
#     (leave unset)          lint EVERY file Claude edits  <- the default
#     $LintFileExtensions = @()            lint NOTHING (explicit opt-out)
#     $LintFileExtensions = @('.py','.pyi')  lint only those
#
# READ BY EVERY EDITION, as of #401. Three readers, identical semantics:
#
#   ~/.claude/hooks/PostToolUse/post-edit-check.ps1  (global; installed from
#       kits/orchestrated-prp/global/ by scripts/deploy-global.ps1)
#   .claude/hooks/post-edit-check.ps1                (per-repo, settings.windows.json)
#   .claude/hooks/post-edit-check.sh                 (per-repo, settings.json --
#       reads LINT_FILE_EXTENSIONS from config.sh, space-separated)
#
# This block used to carry a scope warning: the two per-repo hooks ignored the
# setting entirely, so a repo wired to those and not to the global hook got the
# markdown-through-ruff storm described below even with this set. #398 scoped
# the documentation rather than leave a claim that read as true and was not;
# #401 ported the gate, so the scope note is gone rather than merely reworded.
#
# WHY YOU PROBABLY WANT TO SET THIS. $LintFileCmd is language-specific, and
# the hook hands it every file that is edited. Pointing ruff -- a Python
# linter -- at .md/.yml/.txt/.ts reports each as broken Python and blocks the
# tool call behind a wall of syntax errors. The write has ALREADY SUCCEEDED
# by then, so nothing is protected and the whole cost is the agent's context
# window. Measured on one repo: 325 errors on an English commit message, 120
# on a plain-text file, several hundred on a .ts file.
#
# Unset means "everything" because the global hook runs in EVERY repo on the
# machine, and narrowing what other repos lint without their configs asking
# for it would be a silent behaviour change.
#
# SPELL IT AS AN ARRAY OF DOTTED EXTENSIONS. Matching is case-insensitive
# ('.PY' matches '.py'), but it is otherwise literal, and two near-misses are
# silent rather than loud -- measured:
#
#     @('py')   dot-less    -> matches NOTHING, i.e. lint nothing, no warning
#     ''        empty string -> matches only EXTENSIONLESS files (Makefile,
#                               LICENSE), because GetExtension returns ''
#
# The second is a plausible typo for @(). If you mean "lint nothing", write
# @() -- it is the state that is actually tested.
#
# NOTE ON THE HEADER ABOVE, which says "no Set-StrictMode" in this file. That
# guidance stands. The global hook is nevertheless written to survive a config
# that ignores it -- it reads every value through Get-Variable rather than
# bare -- because a hook that runs in every repo on the machine cannot assume
# every repo followed the advice (#366).
$LintFileExtensions = @('.py', '.pyi')

# Repo-wide lint (used in full gates)
$LintAllCmd = "uv run ruff check ."
# $LintAllCmd = "npx eslint ."                       # fails on errors only
# $LintAllCmd = "uv run ruff check ."
# $LintAllCmd = "dotnet format --verify-no-changes"

# Type check (repo-wide)
$TypecheckCmd = "uv run pyright"
# $TypecheckCmd = "npx tsc --noEmit"
# $TypecheckCmd = "uv run mypy ."

# Test suite
$TestCmd = "uv run pytest -q"
# $TestCmd = "npm test -- --run"
# $TestCmd = "uv run pytest -q"
# $TestCmd = "dotnet test"

# Build
$BuildCmd = ""
# $BuildCmd = "npm run build"
# $BuildCmd = "dotnet build -warnaserror"

# ------------------------------------------------------------
#  Stop gate: what must be green before Claude may END A SESSION.
#  Run by the global ~/.claude/hooks/Stop/stop-gate.ps1, which is inert in
#  any repo that leaves this blank.
#
#  NOTE THE INVERTED CONVENTION. For the four gates above, empty means
#  FAILURE unless listed in $OptionalGates. Here empty means OPT-OUT. The
#  difference is deliberate: those gates run when you ask for them, this one
#  runs unbidden at the end of every turn, so silence must mean "off".
#
#  BUDGET THIS HONESTLY. The gate is killed at $StopGateTimeoutSeconds and
#  then FAILS OPEN - the session ends with nothing verified. A command that
#  usually finishes just inside the budget is a gate that silently stops
#  gating the moment the machine is busy. Point it at something fast, or
#  raise the timeout to comfortably exceed the real runtime.
#
#  ONE COMMAND ONLY. The hook runs this through `cmd /c`, so only the LAST
#  command's exit code is seen: `npm test & pytest` reports GREEN whenever
#  pytest passes, however badly npm test failed. Measured. If you need
#  several steps, put them in a script and point at the script.
# ------------------------------------------------------------
$StopGateCmd = ""
# $StopGateCmd = 'powershell -NoProfile -ExecutionPolicy Bypass -File .claude\hooks\verify-gates.ps1 -Mode fast'

# Optional. Seconds before the stop gate gives up and fails OPEN. 300 if unset.
# MUST STAY BELOW the `timeout` registered for the Stop hook in
# ~/.claude/settings.json (deploy-global.ps1 sets 1020). The hook needs its
# budget + ~2 s to reach its own fail-open; if Claude Code cancels first, the
# gate's process tree is ORPHANED and keeps running detached.
# $StopGateTimeoutSeconds = 300

# Optional. Consecutive blocks before the gate gives up and lets the session
# end anyway, so a persistently red repo cannot become unstoppable. Backstop
# for anthropics/claude-code#54360, where stop_hook_active does not always
# propagate. 3 if unset; 0 disables blocking entirely.
# $StopGateMaxBlocks = 3

# ------------------------------------------------------------
#  Gates this repo legitimately does not have.
#  Names: lint, typecheck, tests, build. A gate listed here reports SKIP
#  instead of FAIL when its command is empty. Anything NOT listed here with an
#  empty command fails the run.
#
#  This is an allow-list of ABSENCES, not a list of what to run: a typo here
#  leaves the gate required, which is the safe direction to be wrong in.
#  Declaring every gate optional does not produce a pass - if zero gates
#  actually execute, the run fails, because nothing was verified.
# ------------------------------------------------------------
$OptionalGates = @('build')   # no build artefact until the frontend lands in PRP-04
# $OptionalGates = @('typecheck')            # e.g. a plain-JS repo
# $OptionalGates = @('typecheck','build')    # e.g. a script/library repo
