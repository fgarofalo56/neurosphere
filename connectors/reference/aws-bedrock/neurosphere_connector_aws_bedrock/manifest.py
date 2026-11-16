"""Manifest for the AWS Bedrock metadata connector: read-only, advisory, Commercial only."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from neurosphere_connector import build_manifest
from neurosphere_contracts.connectors.v1.connector_manifest import (
    ConnectorManifest,
    CredentialRef,
    Granularity,
)

__all__ = [
    "DOCUMENTATION_URL",
    "IAM_ACTIONS",
    "AuthMode",
    "build_aws_bedrock_manifest",
]

DOCUMENTATION_URL = "https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-cw.html"

#: The complete read-only IAM action set, verified against the AWS Service Reference
#: (observed 2026-11-16; all are ``IsWrite`` false). Declared as manifest scopes.
IAM_ACTIONS: tuple[str, ...] = (
    "bedrock:GetModelInvocationLoggingConfiguration",
    "bedrock:ListAgents",
    "bedrock:ListCustomModels",
    "bedrock:ListFoundationModels",
    "bedrock:ListGuardrails",
    "bedrock:ListProvisionedModelThroughputs",
    "ce:GetCostAndUsage",
    "cloudwatch:GetMetricData",
)

AuthMode = Literal["workload_identity_federation", "vault_reference"]


def build_aws_bedrock_manifest(
    *,
    auth_mode: AuthMode = "workload_identity_federation",
    credential_refs: Sequence[CredentialRef] = (),
) -> ConnectorManifest:
    """Federation carries no credential reference; a static key is a vault reference only."""
    return build_manifest(
        name="aws-bedrock-metadata",
        version="0.1.0",
        capabilities=["catalog_discovery", "usage_reports", "cost_ingest", "health_reporting"],
        supported_clouds=["commercial"],
        granularity=Granularity(time_grain="hour", subject_level="deployment"),
        scopes=IAM_ACTIONS,
        credential_refs=credential_refs,
        auth_mode=auth_mode,
        documentation_url=DOCUMENTATION_URL,
    )
