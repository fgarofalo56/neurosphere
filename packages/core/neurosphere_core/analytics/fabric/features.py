"""Fabric optional-feature flags, resolved from the capability matrix, never hard-coded.

CMK, workspace identity and Fabric IQ items are looked up as ``FeatureRequest`` rows for the
adapter's cloud and region via ``neurosphere_core.capabilities.validate_profile``. A feature
with no ``available`` row (including every Commercial feature today, which has no rows) is
disabled with the matrix reason. In GCC High the matrix says unsupported for all three.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, ValidationError

from neurosphere_core.capabilities import DeploymentProfile, FeatureRequest, validate_profile
from neurosphere_core.errors import InvalidSchemaError

FEATURES: Final = ("customer_managed_keys", "workspace_identity", "fabric_iq_items")


class FeatureFlag(BaseModel):
    """One optional feature: enabled only when the matrix row says available."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    feature: str
    enabled: bool
    reason: str | None = None
    reason_code: str | None = None
    row_id: str | None = None


class FabricFeatureFlags(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    customer_managed_keys: FeatureFlag
    workspace_identity: FeatureFlag
    fabric_iq_items: FeatureFlag


def resolve_feature_flags(*, cloud: str, region: str) -> FabricFeatureFlags:
    try:
        profile = DeploymentProfile.model_validate(
            {
                "cloud": cloud,
                "regions": (region,),
                "hosting": "aks",  # irrelevant to the feature rows; only feature results are read
                "analytics": "fabric",
                "features": tuple(FeatureRequest(service="fabric", feature=f) for f in FEATURES),
            }
        )
    except ValidationError:
        raise InvalidSchemaError(
            "cloud or region is invalid for Fabric feature flags", reason="fabric_feature_profile"
        ) from None
    flags: dict[str, FeatureFlag] = {}
    for result in validate_profile(profile).results:
        if result.kind == "feature" and result.service == "fabric":
            flags[result.feature] = FeatureFlag(
                feature=result.feature,
                enabled=result.status == "supported",
                reason=result.reason,
                reason_code=result.reason_code,
                row_id=result.row_id,
            )
    return FabricFeatureFlags.model_validate(flags)


__all__ = ["FEATURES", "FabricFeatureFlags", "FeatureFlag", "resolve_feature_flags"]
