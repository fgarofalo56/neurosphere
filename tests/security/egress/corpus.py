"""Deny-corpus loader and host matcher shared by the egress tests.

Scope: static and compose only; in-cluster proof OPEN (no Government subscription, D7).
"""

from __future__ import annotations

import re
from pathlib import Path

CORPUS_PATH = Path(__file__).with_name("commercial_deny_corpus.txt")
PROBE_LABEL = "nsprobe"

# A host token may not be glued to more host characters on either side. A leading "." is allowed
# so subdomains of an exact Commercial host are caught as well.
_LEFT = r"(?<![A-Za-z0-9-])"
_RIGHT = r"(?![A-Za-z0-9-])"
_LABELS = r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+"


def load_corpus() -> list[str]:
    """Return the committed deny patterns (comments and blank lines dropped)."""
    lines = CORPUS_PATH.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def compile_pattern(pattern: str) -> re.Pattern[str]:
    """Compile one corpus entry to a host-bounded, case-insensitive regex."""
    if pattern.startswith("*."):
        body = _LABELS + re.escape(pattern[2:])
    else:
        body = re.escape(pattern)
    return re.compile(_LEFT + body + _RIGHT, re.IGNORECASE)


def compile_corpus() -> list[tuple[str, re.Pattern[str]]]:
    return [(p, compile_pattern(p)) for p in load_corpus()]


def concrete_host(pattern: str) -> str:
    """A plausible concrete hostname for a corpus pattern."""
    if pattern.startswith("*."):
        return f"{PROBE_LABEL}.{pattern[2:]}"
    return pattern


def find_hits(text: str) -> list[tuple[str, str]]:
    """Return (pattern, matched text) for every corpus pattern found in text."""
    hits: list[tuple[str, str]] = []
    for pattern, rx in compile_corpus():
        for match in rx.finditer(text):
            hits.append((pattern, match.group(0)))
    return hits
