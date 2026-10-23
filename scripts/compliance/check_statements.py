"""Check docs/compliance/**/*.md for the required disclaimer and for affirmative claims.

Fails (exit 1, files named) when:

1. a document lacks the exact fragment ``not FedRAMP authorized; the authorizing official
   decides`` (whitespace runs are collapsed first so hard-wrapped lines still match; the
   words and case are exact), or
2. a sentence affirmatively claims FedRAMP/DoD authorization or certification, a granted ATO,
   compliance parity, a certification or authorization date, or a compliance percentage.

A sentence containing a negation or condition word (not, no, never, cannot, without, whether,
unless, until, if, before) is not an affirmative claim. ``authorizing official`` and
``authorized custodians/users/connectors`` are not claims about NeuroSphere.

Usage:
    python scripts/compliance/check_statements.py
    python scripts/compliance/check_statements.py --root DIR
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIRED = "not FedRAMP authorized; the authorizing official decides"

NEGATION_RE = re.compile(
    r"\b(?:not|no|never|cannot|without|nor|neither|whether|unless|until|if|before|"
    r"does\s+not|do\s+not|must\s+not)\b|n't",
    re.IGNORECASE,
)

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
_AUTH_WORD = r"(?:authori[sz]ed|certified|accredited|compliant)"
_NOT_A_CLAIM = r"(?!\s+(?:custodians?|users?|connectors?|principals?|callers?|personnel|roles?))"
_CERT_NOUN = r"(?:certification|authori[sz]ation|ATO|authority\s+to\s+operate)"

# (rule name, regex). Keep this list small and explicit.
CLAIM_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "authorization or certification claim",
        re.compile(
            r"\b(?:FedRAMP|DoD|IL[2-6]|Impact\s+Level\s+\d)\b[^.\n]{0,60}?\b"
            + _AUTH_WORD
            + r"\b"
            + _NOT_A_CLAIM
            + r"|\bNeuroSphere\s+(?:is|are|has\s+been|was)\s+(?:\w+\s+)?"
            + _AUTH_WORD
            + r"\b"
            + _NOT_A_CLAIM,
            re.IGNORECASE,
        ),
    ),
    (
        "ATO granted claim",
        re.compile(
            r"\b(?:has|have|had|was|were|been|holds?|received|granted|obtained|achieved|issued)"
            r"\b[^.\n]{0,30}?\b(?:ATO|authority\s+to\s+operate)\b|"
            r"\b(?:ATO|authority\s+to\s+operate)\b[^.\n]{0,20}?\b"
            r"(?:granted|issued|received|obtained|achieved)\b",
            re.IGNORECASE,
        ),
    ),
    ("parity claim", re.compile(r"\bparity\b", re.IGNORECASE)),
    (
        "certification or authorization date",
        re.compile(
            r"\b"
            + _CERT_NOUN
            + r"\b[^.\n]{0,30}?\b(?:date|dated|on|by|in|expected|targeted|scheduled)\b\W{0,4}"
            r"(?:\d{4}-\d{2}-\d{2}|20\d{2}\b|" + _MONTH + r"\s+\d{1,2}|Q[1-4]\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "compliance percentage",
        re.compile(
            r"\b(?:complian\w*|coverage|controls?\s+(?:implemented|satisfied|met))\b"
            r"[^.\n]{0,40}?\d+(?:\.\d+)?\s*%|"
            r"\d+(?:\.\d+)?\s*%[^.\n]{0,40}?\b(?:complian\w*|controls?)\b",
            re.IGNORECASE,
        ),
    ),
)

BLOCK_START_RE = re.compile(r"^\s*(?:[|#>*+-]|\d+\.)")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|;\s*|\|")


def has_statement(text: str) -> bool:
    return REQUIRED in " ".join(text.split())


def _units(text: str) -> list[tuple[int, str]]:
    """Split markdown into (first line number, text) units: table/list/heading lines stand
    alone, other consecutive lines form a paragraph."""
    units: list[tuple[int, str]] = []
    para: list[str] = []
    start = 0
    for no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            if para:
                units.append((start, " ".join(para)))
                para = []
        elif BLOCK_START_RE.match(line):
            if para:
                units.append((start, " ".join(para)))
                para = []
            units.append((no, line.strip()))
        else:
            if not para:
                start = no
            para.append(line.strip())
    if para:
        units.append((start, " ".join(para)))
    return units


def find_claims(text: str) -> list[tuple[int, str, str]]:
    """Return (line, rule, sentence) for each affirmative claim."""
    found: list[tuple[int, str, str]] = []
    for line_no, unit in _units(text):
        for sentence in SENTENCE_SPLIT_RE.split(unit):
            sentence = sentence.strip()
            if not sentence or NEGATION_RE.search(sentence):
                continue
            for name, rx in CLAIM_RULES:
                if rx.search(sentence):
                    found.append((line_no, name, sentence[:120]))
    return found


def check(root: Path) -> list[str]:
    """Return failure messages for every doc under root/docs/compliance."""
    base = root / "docs" / "compliance"
    failures: list[str] = []
    for path in sorted(base.rglob("*.md")) if base.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        if not has_statement(text):
            failures.append(f"{rel}: missing required sentence '{REQUIRED}'")
        for line_no, rule, sentence in find_claims(text):
            failures.append(f"{rel}:{line_no}: {rule}: {sentence}")
    return failures


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check compliance docs for the disclaimer.")
    ap.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    args = ap.parse_args(argv)
    root: Path = args.root.resolve()
    failures = check(root)
    if failures:
        print("FAIL: compliance statement check")
        for item in failures:
            print(f"  - {item}")
        return 1
    count = len(list((root / "docs" / "compliance").rglob("*.md")))
    print(f"PASS: {count} compliance document(s) carry the statement and make no affirmative claim")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
