"""Response models of the compliance read API (PRP-56 item 5).

The bundle itself is the contract ``EvidenceBundle``. These models describe the framework list
and one framework's mapped controls. Metadata only: no verdict, score or percentage.
"""

from pydantic import BaseModel, ConfigDict


class FrameworkSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    framework_id: str
    title: str
    framework_version: str
    source_url: str
    source_retrieved: str
    control_count: int


class FrameworkListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    library_version: str
    frameworks: list[FrameworkSummary]


class MappedControlView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    control_id: str
    title: str
    source_url: str
    source_retrieved: str
    support_status: str
    evidence_sources: list[str]


class FrameworkDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    library_version: str
    framework_id: str
    title: str
    framework_version: str
    source_url: str
    source_retrieved: str
    controls: list[MappedControlView]
