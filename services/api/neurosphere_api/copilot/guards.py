"""Policy checks the orchestrator applies around the model (PRP-19 item 2).

Nothing here trusts the model or the content it read:

* arguments are inspected for a raw query string or a domain the caller cannot reach BEFORE the
  tool registry runs (the registry still enforces scope, the allowlist and budgets itself);
* the model's text is checked after the loop for echoed system instructions, secret-shaped
  content and server-held secret values before a single token is released;
* citation markers in the text are parsed here, but a citation is only ever honoured when a tool
  result of the same turn produced that record id.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping
from typing import Any, Final

__all__ = [
    "SHINGLE_WORDS",
    "domain_filter_values",
    "extract_citation_ids",
    "has_raw_query",
    "leaks_system_prompt",
    "rewrite_domain_filter",
    "secret_shaped",
    "substitute_citations",
]

SHINGLE_WORDS: Final = 6
_CITE: Final = re.compile(r"\[cite:([^\]\s]{1,512})\]")
_WORDS: Final = re.compile(r"[a-z0-9']+")
_SECRET_PATTERNS: Final = tuple(
    re.compile(p)
    for p in (
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}",
        r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}",
        (
            r"(?i)\b[\w-]*(?:key|secret|token|password|pwd|sig)\s*[=:]\s*"
            r"(?=[A-Za-z0-9+/=_.-]*\d)[A-Za-z0-9+/=_.-]{12,}"
        ),
        r"\b(?:sk|pk|ghp|gho|xox[bap])[-_][A-Za-z0-9_-]{16,}\b",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\b[A-Za-z0-9+/_-]{40,}={0,2}",
    )
)


# -- citations ----------------------------------------------------------------------------------


def extract_citation_ids(text: str) -> list[str]:
    """Record ids the text cites, in first-use order, without duplicates."""
    seen: dict[str, None] = {}
    for found in _CITE.findall(text):
        seen.setdefault(found, None)
    return list(seen)


def substitute_citations(text: str, order: Mapping[str, int]) -> str:
    """Replace each ``[cite:<id>]`` marker by ``[n]`` using the 1-based citation ``order``."""
    return _CITE.sub(lambda m: f"[{order[m.group(1)]}]" if m.group(1) in order else "", text)


# -- output guard -------------------------------------------------------------------------------


def _shingles(text: str) -> set[tuple[str, ...]]:
    words = _WORDS.findall(text.lower())
    return {tuple(words[i : i + SHINGLE_WORDS]) for i in range(len(words) - SHINGLE_WORDS + 1)}


def leaks_system_prompt(text: str, system: str) -> bool:
    """True when the text repeats any run of ``SHINGLE_WORDS`` consecutive words of ``system``."""
    return not _shingles(system).isdisjoint(_shingles(text))


def secret_shaped(text: str, protected_values: Iterable[str]) -> bool:
    """True for key/token/credential-shaped content or a server-held secret value."""
    if any(value and value in text for value in protected_values):
        return True
    return any(p.search(text) for p in _SECRET_PATTERNS)


# -- tool-argument inspection -------------------------------------------------------------------


def has_raw_query(raw_args: Mapping[str, object]) -> bool:
    """A free-text ``query`` argument: query text is never accepted, only a structured query."""
    return isinstance(raw_args.get("query"), str)


def _filters(raw_args: Mapping[str, object]) -> list[Any]:
    query = raw_args.get("query")
    if isinstance(query, Mapping):
        filters = query.get("filters")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if isinstance(filters, list):
            return filters  # pyright: ignore[reportUnknownVariableType]
    return []


def domain_filter_values(raw_args: Mapping[str, object]) -> list[str]:
    """Every domain id the arguments ask for through a ``domain_id`` filter."""
    found: list[str] = []
    for flt in _filters(raw_args):
        if isinstance(flt, Mapping) and flt.get("field") == "domain_id":  # pyright: ignore[reportUnknownMemberType]
            value = flt.get("value")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            values = flt.get("values")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            if isinstance(value, str):
                found.append(value)
            if isinstance(values, list):
                found.extend(v for v in values if isinstance(v, str))  # pyright: ignore[reportUnknownVariableType]
    return found


def rewrite_domain_filter(
    raw_args: Mapping[str, object], applied: tuple[str, ...]
) -> dict[str, object]:
    """Copy of the arguments whose ``domain_id`` filter is exactly the narrowed domains.

    The model's own domain filters are intersected with ``applied`` (a focus that excludes them
    wins); with none, the narrowed set is imposed. Never widens: ``applied`` is a subset of the
    domains the caller may already read.
    """
    out = copy.deepcopy(dict(raw_args))
    query = out.get("query")
    if not isinstance(query, dict):
        return out
    requested = domain_filter_values(raw_args)
    wanted = tuple(d for d in applied if d in requested) or applied
    kept = [
        f
        for f in _filters(raw_args)
        if not (isinstance(f, Mapping) and f.get("field") == "domain_id")  # pyright: ignore[reportUnknownMemberType]
    ]
    if len(wanted) == 1:
        kept.append({"field": "domain_id", "op": "eq", "value": wanted[0]})
    else:
        kept.append({"field": "domain_id", "op": "in", "values": list(wanted)})
    query["filters"] = kept  # pyright: ignore[reportUnknownMemberType]
    return out
