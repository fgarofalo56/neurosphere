"""CloudEvents 1.0 envelope (structured and batch JSON modes), validated without the SDK.

The ``cloudevents`` SDK is deliberately not a dependency (its transitive dependencies fail the
licence gate), so only the required context attributes are checked: ``specversion`` "1.0",
``id``, ``source`` and ``type``. Extension attributes are kept (``REQUEST_ID_EXTENSION`` carries
the request id for cost events). Media types: ``application/cloudevents+json`` (one event) and
``application/cloudevents-batch+json`` (a JSON array of events).
"""

from __future__ import annotations

from typing import Any, Final, Literal

from neurosphere_core.payload import REQUEST_ID_EXTENSION
from pydantic import BaseModel, ConfigDict, Field

STRUCTURED_MEDIA_TYPE: Final = "application/cloudevents+json"
BATCH_MEDIA_TYPE: Final = "application/cloudevents-batch+json"


class CloudEvent(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, hide_input_in_errors=True)

    specversion: Literal["1.0"]
    id: str = Field(min_length=1, max_length=256)
    source: str = Field(min_length=1, max_length=1024)
    type: str = Field(min_length=1, max_length=256)
    time: str | None = None
    datacontenttype: str | None = None
    data: dict[str, Any] | None = None

    @property
    def request_id(self) -> str | None:
        value = (self.model_extra or {}).get(REQUEST_ID_EXTENSION)
        return value if isinstance(value, str) and 0 < len(value) <= 256 else None
