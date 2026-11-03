"""Shared claims lint rules for the marketing sources (PRP-26).

This is an importable module, NOT a test file (its name does not match test_*.py).

How a sibling test imports it (tests/marketing has no __init__.py, so a plain
``import claims_rules`` works only when pytest puts this directory on sys.path; the
loader below does not depend on that and is safe against the same-named test package
clash)::

    import importlib.util
    import sys
    from pathlib import Path

    _PATH = Path(__file__).with_name("claims_rules.py")
    _SPEC = importlib.util.spec_from_file_location("claims_rules", _PATH)
    assert _SPEC is not None and _SPEC.loader is not None
    claims_rules = importlib.util.module_from_spec(_SPEC)
    sys.modules["claims_rules"] = claims_rules  # dataclasses need this before exec
    _SPEC.loader.exec_module(claims_rules)

    violations = claims_rules.find_violations(text)

How the rules work
------------------
The text is cut into sentences: a sentence ends at a newline, or at ``.``, ``!`` or ``?``
followed by whitespace. A semicolon does NOT end a sentence.

1. Banned phrases (``BANNED_PHRASES``): authorized, ATO, FedRAMP status words, parity,
   unique, first, only, best, guaranteed, compliant, savings, completeness and superlative
   words. A match is allowed when the same sentence has a negation word BEFORE the match
   (not, no, never, cannot, without, nor, n't) in the SAME CLAUSE (clauses split on commas,
   semicolons and " but ", " and ", " yet ", " while "), or when the sentence is a labelled
   "We do not claim" / "Does not claim" line. Double negatives are not understood.
   Authorization levels ("FedRAMP High", "IL4/IL5") and savings forms (save, saves, saving)
   are banned the same way.
2. Unlabelled numbers (``NUMBER_PATTERN``): a sentence with a performance-style number
   (a percent, a duration or rate unit, or a p95 style percentile) must either contain the
   word "target" or cite an evidence path (``docs/evidence/...``). Otherwise it is flagged.
   A duration in seconds or minutes ("11 s", "2.0 min") on a sentence containing "estimate"
   AND a runtime/duration/length/timing/narration/scene word is a timing estimate and is not
   flagged; any other number is still flagged.
3. Em-dashes are flagged (repo rule: no em-dashes in docs).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import yaml

# Rule name -> compiled pattern. Names are stable: tests and item 3 may assert on them.
BANNED_PHRASES: dict[str, re.Pattern[str]] = {
    "authorized": re.compile(r"\bauthori[sz]ed\b", re.IGNORECASE),
    "ato": re.compile(r"\bATO\b"),  # case sensitive, so "ato" inside a word never matches
    "fedramp-status": re.compile(
        r"\bFedRAMP[\s-]+(?:compliant|authori[sz]ed|certified|approved|ready)\b", re.IGNORECASE
    ),
    # Authorization-level phrasing: "FedRAMP High/Moderate/Low" and DoD "IL4/IL5".
    "fedramp-level": re.compile(
        r"\b(?i:FedRAMP)[\s-]+(?:High|Moderate|Low)\b|\bIL-?[45](?:\s*/\s*(?:IL-?)?[45])?\b"
    ),
    "parity": re.compile(r"\bparity\b", re.IGNORECASE),
    "unique": re.compile(r"(?<![\w-])unique(?:ly|ness)?(?![\w-])", re.IGNORECASE),
    "first": re.compile(r"(?<![\w-])first(?![\w-])", re.IGNORECASE),
    "only": re.compile(r"(?<![\w-])only(?![\w-])", re.IGNORECASE),  # "read-only" is allowed
    "best": re.compile(r"(?<![\w-])best(?![\w-])", re.IGNORECASE),
    "guaranteed": re.compile(r"\bguarantee[sd]?\b", re.IGNORECASE),
    "compliant": re.compile(r"\b(?:compliant|certified)\b", re.IGNORECASE),
    # Savings CLAIMS only: "save", "saves", "saving(s)", or "saved 30 ..." / "saved $5". The plain
    # past participle in "saved reports" is not a claim.
    "savings": re.compile(r"\bsav(?:es?|ing|ings)\b|\bsaved\s+(?:\$\s?)?\d", re.IGNORECASE),
    "completeness": re.compile(
        r"\b(?:complete(?:ly|ness)?|comprehensive|industry-leading|world-class)\b",
        re.IGNORECASE,
    ),
}

# A negation word that appears before the banned phrase in the SAME CLAUSE exempts it.
NEGATION = re.compile(r"\b(?:not|no|never|cannot|without|nor)\b|n't", re.IGNORECASE)
# Clause boundaries inside a sentence: comma, semicolon, " but ", " and ", " yet ", " while ".
CLAUSE_SPLIT = re.compile(r"[,;]|\s(?:but|and|yet|while)\s", re.IGNORECASE)

# A whole sentence that starts with one of these labels is a statement of what is NOT claimed.
NOT_CLAIM_LABEL = re.compile(
    r"^\s*(?:[-*]\s*)?(?:we do not claim|does not claim|not claimed)\b", re.IGNORECASE
)

# Performance-style numbers: percent, ms, seconds, fps, 2k style counts, p95 style percentiles.
NUMBER_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:%|percent\b|per\s?cent\b|ms\b|s\b|seconds?\b|fps\b|k\b)|\bp\d{2}\b",
    re.IGNORECASE,
)
TARGET_WORD = re.compile(r"\btargets?\b", re.IGNORECASE)
EVIDENCE_PATH = re.compile(r"docs/evidence/\S+")

# A duration (seconds or minutes) on a sentence that says "estimate"/"estimated" is a timing
# estimate for the asset itself (for example a video runtime), not a performance claim.
TIMING_UNIT = re.compile(r"\d+(?:\.\d+)?\s?(?:s|seconds?|min|minutes?)", re.IGNORECASE)
ESTIMATE_WORD = re.compile(r"\bestimate[sd]?\b", re.IGNORECASE)
# The estimate exemption also needs a runtime/duration-style word in the sentence.
DURATION_CONTEXT = re.compile(
    r"\b(?:run-?times?|durations?|lengths?|timings?|narrations?|scenes?)\b", re.IGNORECASE
)

EM_DASH = "—"

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n")


@dataclass(frozen=True)
class Violation:
    """One lint finding. ``line`` is 1-based."""

    rule: str
    phrase: str
    sentence: str
    line: int


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Split a Markdown file into (front matter mapping, body).

    The front matter is a YAML block between a first line of ``---`` and the next line of
    ``---``. Raises ValueError when it is missing, unterminated or not a mapping.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing front matter: first line must be '---'")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            loaded = yaml.safe_load("\n".join(lines[1:index]))
            if not isinstance(loaded, dict):
                raise ValueError("front matter must be a YAML mapping")
            return loaded, "\n".join(lines[index + 1 :]).lstrip("\n")
    raise ValueError("unterminated front matter: no closing '---'")


def _sentences(text: str) -> list[tuple[int, str]]:
    """Return (1-based line of sentence start, sentence) pairs."""
    result: list[tuple[int, str]] = []
    line = 1
    pos = 0
    for match in _SENTENCE_END.finditer(text):
        chunk = text[pos : match.start()]
        if chunk.strip():
            result.append((line, chunk))
        line += text.count("\n", pos, match.end())
        pos = match.end()
    tail = text[pos:]
    if tail.strip():
        result.append((line, tail))
    return result


def _negated(sentence: str, start: int) -> bool:
    """True when a negation word precedes ``start`` within the same clause."""
    clause_start = 0
    for split in CLAUSE_SPLIT.finditer(sentence, 0, start):
        clause_start = split.end()
    return bool(NEGATION.search(sentence[clause_start:start]))


def _first_unlabelled_number(sentence: str) -> re.Match[str] | None:
    """First performance-style number, skipping s/min durations on an "estimate" sentence."""
    is_estimate = bool(ESTIMATE_WORD.search(sentence) and DURATION_CONTEXT.search(sentence))
    for match in NUMBER_PATTERN.finditer(sentence):
        if is_estimate and TIMING_UNIT.fullmatch(match.group(0)):
            continue
        return match
    return None


def find_violations(text: str) -> list[Violation]:
    """Lint ``text`` and return every violation (empty list means the text passes)."""
    found: list[Violation] = []
    for line, sentence in _sentences(text):
        not_claim_line = bool(NOT_CLAIM_LABEL.match(sentence))
        for rule, pattern in BANNED_PHRASES.items():
            for match in pattern.finditer(sentence):
                if not_claim_line or _negated(sentence, match.start()):
                    continue
                found.append(Violation(rule, match.group(0), sentence.strip(), line))
        number = _first_unlabelled_number(sentence)
        if number is not None and not (
            TARGET_WORD.search(sentence) or EVIDENCE_PATH.search(sentence)
        ):
            found.append(Violation("unlabelled-number", number.group(0), sentence.strip(), line))
        if EM_DASH in sentence:
            found.append(Violation("em-dash", EM_DASH, sentence.strip(), line))
    return found
