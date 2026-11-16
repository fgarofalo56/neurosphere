"""Read-only readers behind the detection rules (PRP-61 item 3)."""

from neurosphere_workers.detections.readers.arm import ArmDeploymentReader
from neurosphere_workers.detections.readers.graph import (
    AI_ACCOUNT_QUERY,
    ALLOWED_COLUMNS,
    ResourceGraphAccountReader,
)
from neurosphere_workers.detections.readers.stores import CatalogProjectReader, StoreGatewayReader

__all__ = [
    "AI_ACCOUNT_QUERY",
    "ALLOWED_COLUMNS",
    "ArmDeploymentReader",
    "CatalogProjectReader",
    "ResourceGraphAccountReader",
    "StoreGatewayReader",
]
