"""Fabric provisioning adapter (PRP-08 item 6), gated by the capability matrix."""

from neurosphere_core.deploy.fabric.endpoints import FabricEndpoints, fabric_endpoints_for
from neurosphere_core.deploy.fabric.provisioner import CapacityRef, FabricProvisioner, WorkspaceRef
from neurosphere_core.deploy.fabric.transport import (
    FabricHttp,
    FabricResponse,
    RecordedCall,
    RecordingFabricHttp,
)

__all__ = [
    "CapacityRef",
    "FabricEndpoints",
    "FabricHttp",
    "FabricProvisioner",
    "FabricResponse",
    "RecordedCall",
    "RecordingFabricHttp",
    "WorkspaceRef",
    "fabric_endpoints_for",
]
