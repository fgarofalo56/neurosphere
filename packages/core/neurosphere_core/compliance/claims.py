"""No-claim scanner for compliance text (PRP-56 item 3).

The compliance mapping collects and maps; it never judges. :func:`scan_for_claims` returns a
description of each affirmative overclaim in a text so tests (and the bundle builder) can refuse
it. Modelled on the PRP-23 detector (``tests/compliance/test_control_mapping.py``); there is no
code import from ``scripts/`` or ``tests/``.

Rules:

* "compliant" is never allowed (the vocabulary has no such value);
* "certified" is never allowed;
* "authorized" is allowed only when negated in the same clause ("not FedRAMP authorized") or when
  it qualifies a named actor class (custodians, users, connectors, principals, callers,
  personnel, operators, roles); "authorizing official" is a different word and passes;
* an ATO claim ("has an ATO", "ATO granted") is allowed only when negated;
* a percentage is never allowed (no score);
* a date on a sentence about certification, authorization or an ATO is never allowed.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ["DISCLAIMER", "scan_for_claims"]

#: Fragment every Markdown bundle and the runbook must contain (PRP-23 wording).
DISCLAIMER: Final = "not FedRAMP authorized; the authorizing official decides"

_NEGATION = re.compile(r"\b(not|no|never|cannot|nor|neither)\b", re.IGNORECASE)
_AUTHORIZED = re.compile(r"\bauthori[sz]ed\b", re.IGNORECASE)
_AUTHORIZED_OK_NEXT = re.compile(
    r"\s+(custodians?|users?|connectors?|principals?|callers?|personnel|operators?|roles?)\b",
    re.IGNORECASE,
)
_COMPLIANT = re.compile(r"\bcompliant\b", re.IGNORECASE)
_CERTIFIED = re.compile(r"\bcertified\b", re.IGNORECASE)
_PERCENT = re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%")
_ATO_CLAIM = re.compile(
    r"\b(?:has|have|holds?|received|granted|achieved|obtained)\b[^.;\n]{0,20}\bATO\b"
    r"|\bATO\s+(?:granted|achieved|issued|received)\b",
    re.IGNORECASE,
)
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_DATE_TOPIC = re.compile(r"\b(?:certif\w*|authori[sz]\w*|ATO)\b", re.IGNORECASE)


def _clause_prefix(text: str, start: int, width: int = 25) -> str:
    prefix = text[max(0, start - width) : start]
    return re.split(r"[.;:\n]", prefix)[-1]


def _negated(text: str, start: int) -> bool:
    return _NEGATION.search(_clause_prefix(text, start)) is not None


def _snippet(text: str, start: int) -> str:
    return text[max(0, start - 20) : start + 25].replace("\n", " ")


def scan_for_claims(text: str) -> list[str]:
    """Descriptions of every affirmative overclaim found in ``text`` (empty when clean)."""
    found: list[str] = []
    found += [f"compliant: {m.group(0)!r}" for m in _COMPLIANT.finditer(text)]
    found += [f"certified: {m.group(0)!r}" for m in _CERTIFIED.finditer(text)]
    for m in _AUTHORIZED.finditer(text):
        if _negated(text, m.start()) or _AUTHORIZED_OK_NEXT.match(text, m.end()):
            continue
        found.append(f"authorized: {_snippet(text, m.start())!r}")
    found += [
        f"ato: {m.group(0)!r}" for m in _ATO_CLAIM.finditer(text) if not _negated(text, m.start())
    ]
    found += [f"percentage: {m.group(0)!r}" for m in _PERCENT.finditer(text)]
    for sentence in re.split(r"(?<=[.;])\s+|\n", text):
        if _DATE.search(sentence) and _DATE_TOPIC.search(sentence):
            found.append(f"dated claim: {sentence.strip()[:60]!r}")
    return found
