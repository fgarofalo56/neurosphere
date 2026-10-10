# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated

from pydantic import Field, RootModel, StrictStr


class CanonicalId(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            max_length=512,
            min_length=9,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$",
            title="CanonicalId",
        ),
    ]
    """
    Canonical ID grammar cloud:customer:source:type:id. cloud is commercial or government; customer, source and type are lowercase [a-z0-9._-]; id is lowercase [a-z0-9._-] plus '/' and '='; no segment may contain ':'. Corpus: id-corpus.json. Python validator validate_canonical_id_fullmatch re-checks with re.fullmatch because Python re.search lets '$' match before a trailing newline.
    """


class CloudSegment(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^(commercial|government)$")]


class Segment(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[a-z0-9._-]+$")]


class IdSegment(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[a-z0-9._/=-]+$")]
