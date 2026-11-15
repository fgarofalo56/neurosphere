# Adding variables to `.env.example`

Coding agents cannot edit `.env.example`. A repository hook blocks every agent write to
`.env*` files so that a session can never read or leak a real value. That block also covers the
tracked template, so new `NS_*` names reach `.env.example` through the operator, in one batch.

## The rule for every PRP

1. A PRP that introduces a new `NS_*` variable does not touch `.env.example`.
2. It lists each new name in its completion note under **Env vars for the operator**, with a one
   line purpose and the default the code uses when the variable is unset.
3. It documents the same names in the runbook the PRP names.
4. Names only. Never put a value that looks like a secret (a key, token, connection string or
   password) in the note, the runbook or the script. Use `<value>` placeholders.

## Operator step: one batched script

After one or more PRPs merge, the operator collects the names from the completion notes and runs
a single script. The script appends a line only when the name is not already present, so it is
safe to run twice.

Template for `temp/add-env-example.sh` (`temp/` is gitignored; do not commit the script):

```bash
#!/usr/bin/env bash
# Append missing NS_* names to .env.example. Idempotent. Names and placeholders only.
set -euo pipefail
file=".env.example"

add() {
  local name="$1" comment="$2"
  if grep -q "^${name}=" "$file"; then
    echo "present  ${name}"
  else
    printf '# %s\n%s=\n' "$comment" "$name" >> "$file"
    echo "added    ${name}"
  fi
}

# One line per new variable, copied from the completion notes:
add "NS_EXAMPLE_NAME" "What it does; default when unset"
```

Rules for the script:

- Each `add` line carries the name and a comment. The value stays empty, or a non-secret
  default that the completion note states.
- Never paste a real credential, even a throwaway one.
- Review `git diff .env.example`, then commit it as a normal docs change.

## Why not let agents edit the file

`.env.example` sits next to real `.env` files that hold secrets. The hook cannot tell a harmless
template edit from a read of a neighbouring file, so it blocks the whole family. A batched
operator step is cheaper than weakening the guard, and it keeps the completion note as the
audit trail for which PRP added which name.
