"""Shared evidence-directory confinement for the live gate scripts (PRP-59 item 6, #214).

A CLI-supplied ``--evidence-dir`` is untrusted input: it is resolved and must sit inside an
allowed root before anything is written. Keeping the check in one place leaves a single place
for static analysis to flag and a single justification (``docs/security/snyk-justifications.md``).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


class RefusedError(RuntimeError):  # shared by both G01 scripts
    """The evidence directory resolves outside every allowed root."""


def confine_evidence_dir(
    raw: str, allowed_roots: Sequence[Path], label: str = "the G01 evidence directory"
) -> Path:
    """Resolve a CLI-supplied evidence dir and require it inside an allowed root.

    Refuses (``RefusedError``) traversal and absolute out-of-root paths before anything is
    written.
    """
    resolved = Path(raw).resolve()
    for root in allowed_roots:
        if resolved.is_relative_to(Path(root).resolve()):
            return resolved
    raise RefusedError(f"--evidence-dir must resolve inside {label}.")
