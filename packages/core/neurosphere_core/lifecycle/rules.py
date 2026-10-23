"""The written conflict rules (PRP-23 clarification 4) and audit identity.

Precedence, highest first:

1. audit immutability   - audit is never deleted, pseudonymized, expired or exported by the engine.
2. legal hold           - a held object cannot be deleted, pseudonymized or expired.
3. minimum retention    - a record younger than its class minimum cannot be removed on request.
4. subject request      - a deletion or pseudonymization request.
5. maximum retention    - expiry when the class maximum has passed.

A lower rule never overrides a higher one. A blocked request is queued and audited and runs when
the blocking rule lifts; it is never dropped and never forced.

Audit identity is decided here by the audit package's own document types and container names,
plus the target's reported record, not by the caller's labels alone.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

from neurosphere_core.audit.store import RECORD_DOC_TYPE, TAIL_DOC_TYPE
from neurosphere_core.lifecycle.models import Rule, TargetRecord, TargetRef

#: Container names the audit store is deployed under (records and the separate tail container).
AUDIT_CONTAINERS: Final = frozenset({"audit", "audit_tail"})
AUDIT_TARGET_KINDS: Final = frozenset({"audit", "audit_record", "audit_tail", "audit_chain"})
AUDIT_DOC_TYPES: Final = frozenset({RECORD_DOC_TYPE, TAIL_DOC_TYPE})
_AUDIT_RECORD_ID: Final = re.compile(r"^rec-\d{20}$")


def _norm(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def is_audit_label(ref: TargetRef) -> bool:
    """Identity from the reference alone: container, kind or the audit record id shape."""
    return (
        _norm(ref.container) in AUDIT_CONTAINERS
        or _norm(ref.target_kind) in AUDIT_TARGET_KINDS
        or _AUDIT_RECORD_ID.fullmatch(ref.record_id) is not None
    )


def is_audit_record(record: TargetRecord | None) -> bool:
    """Identity from what the store actually holds: the audit package's document types."""
    return record is not None and record.doc_type in AUDIT_DOC_TYPES


def is_audit_container(container: str) -> bool:
    return _norm(container) in AUDIT_CONTAINERS


def governing_rule(applicable: Iterable[Rule]) -> Rule | None:
    """The highest-precedence rule among those that apply (lowest number wins)."""
    rules = list(applicable)
    return min(rules) if rules else None


def outranks(first: Rule, second: Rule) -> bool:
    return first < second
