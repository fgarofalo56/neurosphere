"""The one definition of "may read raw observations" (PRP-43 item 3).

Lives outside ``repo/engine.py`` so ``graph/query.py`` does not import the repository engine.
``repo.engine`` re-exports it for existing callers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from neurosphere_core.catalog.rules import parse_timestamp
from neurosphere_core.scope import IdentityScope

AUDITOR_ROLE: Final = "security_auditor"


def auditor_domains(scope: IdentityScope, now: datetime) -> tuple[str, ...]:
    """Domains where ``scope`` holds an unexpired ``security_auditor`` role (and can read).

    ``list_observations`` enforces it and ``GraphQuery``'s raw view asks it explicitly instead of
    probing with an unknown edge ID.
    """
    granted: dict[str, None] = {}
    if not isinstance(scope, IdentityScope):
        raise TypeError("an IdentityScope is required as the first argument")
    for assignment in scope.to_contract().roles:
        if assignment.role != AUDITOR_ROLE:
            continue
        if assignment.expires_at is not None and parse_timestamp(assignment.expires_at.root) <= now:
            continue
        for domain in assignment.domain_ids:
            granted.setdefault(domain.root)
    return tuple(d for d in scope.allowed_domains if d in granted)
