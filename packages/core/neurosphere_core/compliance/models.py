"""Typed views of the compliance control library (PRP-56 item 2).

The wire shapes are the ``neurosphere_contracts.compliance.v1`` models; this module adds the
immutable library container the loader returns and the shared vocabulary constants. Nothing here
judges: there is no pass, fail, score or percentage.
"""

from __future__ import annotations

from typing import Final, Literal

from neurosphere_contracts.compliance.v1.control import Control
from neurosphere_contracts.compliance.v1.control_framework import ControlFramework
from neurosphere_contracts.compliance.v1.control_mapping import ControlMapping
from pydantic import BaseModel, ConfigDict

__all__ = [
    "EVIDENCE_SOURCE_IDS",
    "EVIDENCE_STATUSES",
    "LIBRARY_VERSION",
    "PATH_REQUIRED_STATUSES",
    "SUMMARY_WORDS",
    "SUPPORT_STATUSES",
    "ControlLibrary",
    "EvidenceSourceId",
    "LibraryFramework",
    "MappedControl",
    "ObservationStatus",
    "SummaryWord",
    "SupportStatus",
]

#: Version of the shipped library data. Bump when a control or mapping row changes.
LIBRARY_VERSION: Final = "1.0.0"

SupportStatus = Literal[
    "designed", "implemented_tested", "inherited", "customer", "planned", "not_applicable"
]
SUPPORT_STATUSES: Final[tuple[str, ...]] = (
    "designed",
    "implemented_tested",
    "inherited",
    "customer",
    "planned",
    "not_applicable",
)
#: Statuses whose mapping must cite repository paths (the test checks the paths exist).
PATH_REQUIRED_STATUSES: Final[frozenset[str]] = frozenset({"designed", "implemented_tested"})

EvidenceSourceId = Literal[
    "catalog_ownership",
    "audit_chain",
    "hitl_decisions",
    "evaluation_results",
    "cost_attribution",
    "configuration_findings",
]
EVIDENCE_SOURCE_IDS: Final[tuple[str, ...]] = (
    "catalog_ownership",
    "audit_chain",
    "hitl_decisions",
    "evaluation_results",
    "cost_attribution",
    "configuration_findings",
)

ObservationStatus = Literal["observed", "partial", "unavailable", "not_collected"]
EVIDENCE_STATUSES: Final[tuple[str, ...]] = ("observed", "partial", "unavailable", "not_collected")

SummaryWord = Literal[
    "evidence_present", "evidence_partial", "no_evidence", "customer_responsibility"
]
SUMMARY_WORDS: Final[tuple[str, ...]] = (
    "evidence_present",
    "evidence_partial",
    "no_evidence",
    "customer_responsibility",
)


class MappedControl(BaseModel):
    """A library control with NeuroSphere's mapping for it."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    control: Control
    mapping: ControlMapping


class LibraryFramework(BaseModel):
    """One framework with its mapped controls, in library order."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    framework: ControlFramework
    controls: tuple[MappedControl, ...]


class ControlLibrary(BaseModel):
    """The validated, immutable control library."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    version: str
    frameworks: tuple[LibraryFramework, ...]

    def framework(self, framework_id: str) -> LibraryFramework | None:
        return next(
            (f for f in self.frameworks if f.framework.framework_id.root == framework_id), None
        )

    def control(self, control_id: str) -> MappedControl | None:
        for fw in self.frameworks:
            for mapped in fw.controls:
                if mapped.control.control_id == control_id:
                    return mapped
        return None

    def control_ids(self) -> tuple[str, ...]:
        return tuple(m.control.control_id for fw in self.frameworks for m in fw.controls)
