"""The registered gateway one connector instance is bound to."""

from __future__ import annotations

import re
from dataclasses import dataclass

from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.gateway.models import GATEWAY_ID_PATTERN, normalize_arm_id

__all__ = ["GatewayRef"]

_GATEWAY_ID = re.compile(GATEWAY_ID_PATTERN)


@dataclass(frozen=True)
class GatewayRef:
    """A PRP-33 registration: deterministic id, cloud and the APIM service ARM id."""

    gateway_id: str
    cloud: CloudName
    arm_resource_id: str

    def __post_init__(self) -> None:
        if not _GATEWAY_ID.fullmatch(self.gateway_id):
            raise ValueError("invalid gateway_id")
        normalize_arm_id(self.arm_resource_id)
