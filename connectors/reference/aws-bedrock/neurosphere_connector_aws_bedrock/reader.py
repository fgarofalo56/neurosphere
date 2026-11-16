"""Read side of the connector: a metadata-only protocol and its documented AWS surface.

Verified API surface (each read in the PRP-62 session, observed 2026-11-16):

| Service (boto3 client) | Operation | IAM action |
|---|---|---|
| bedrock | ListFoundationModels | bedrock:ListFoundationModels |
| bedrock | ListCustomModels | bedrock:ListCustomModels |
| bedrock | ListProvisionedModelThroughputs | bedrock:ListProvisionedModelThroughputs |
| bedrock | ListGuardrails | bedrock:ListGuardrails |
| bedrock | GetModelInvocationLoggingConfiguration | bedrock:GetModelInvocationLoggingConfiguration |
| bedrock-agent | ListAgents | bedrock:ListAgents |
| cloudwatch | GetMetricData | cloudwatch:GetMetricData |
| ce | GetCostAndUsage | ce:GetCostAndUsage |

Sources: the botocore service models shipped in botocore 1.44.3 (operation names, parameters,
response shapes); the AWS Service Reference JSON
(https://servicereference.us-east-1.amazonaws.com/v1/{bedrock,ce,cloudwatch}/*.json) for the
IAM action names and their read-only classification (``IsWrite`` false for all of them);
https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-cw.html for the ``AWS/Bedrock``
metrics ``Invocations``, ``InputTokenCount``, ``OutputTokenCount`` and the ``ModelId``
dimension; https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/
API_GetCostAndUsage.html for ``GetCostAndUsage`` (``Granularity`` DAILY, ``Metrics``
``UnblendedCost``, ``ResultsByTime[].Estimated``, ``NextPageToken``); and
https://docs.aws.amazon.com/cost-management/latest/userguide/ce-api.html for the request price
(each Cost Explorer API request costs 0.01 USD on the primary billing view).

The protocol exposes read operations that return bounded metadata only. It has no invoke,
``converse``, log-read or object-read operation, and a test enumerates the protocol to keep it
that way. Readers return *normalised* mappings holding only whitelisted keys, so nothing a
service might add to a response can reach the typed models.
"""

# ruff: noqa: E501  (the verified-API table in the module docstring)

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from neurosphere_connector_aws_bedrock.models import CostWindow, UsageWindow

__all__ = [
    "INVENTORY_SOURCES",
    "READER_OPERATIONS",
    "BedrockReader",
    "ReaderPage",
]

#: Inventory source names, also the keys of ``BedrockInventory.failed_sources``.
INVENTORY_SOURCES = (
    "foundation_models",
    "custom_models",
    "provisioned_throughput",
    "guardrails",
    "agents",
)

#: The complete public operation set of a reader. A test pins this.
READER_OPERATIONS = frozenset(
    {
        "list_foundation_models",
        "list_custom_models",
        "list_provisioned_throughput",
        "list_guardrails",
        "list_agents",
        "get_usage",
        "get_cost",
        "get_invocation_logging",
        "close",
    }
)


@dataclass(frozen=True)
class ReaderPage:
    """Normalised items plus whether more existed than the cap or page budget allowed."""

    items: tuple[Mapping[str, Any], ...]
    truncated: bool = False


@runtime_checkable
class BedrockReader(Protocol):
    """Metadata-only reads. ``limit`` is a hard cap on returned items."""

    async def list_foundation_models(self, *, limit: int) -> ReaderPage:
        """Items: id, name, status, provider, input_modalities, output_modalities."""
        ...

    async def list_custom_models(self, *, limit: int) -> ReaderPage:
        """Items: id, name, status, provider, created_at."""
        ...

    async def list_provisioned_throughput(self, *, limit: int) -> ReaderPage:
        """Items: id, name, status, created_at."""
        ...

    async def list_guardrails(self, *, limit: int) -> ReaderPage:
        """Items: id, name, status, created_at."""
        ...

    async def list_agents(self, *, limit: int) -> ReaderPage:
        """Items: id, name, status."""
        ...

    async def get_usage(
        self, *, model_ids: Sequence[str], window: UsageWindow, limit: int
    ) -> ReaderPage:
        """Items: model_id, metric, hour (aware datetime), value (float). Missing hours absent."""
        ...

    async def get_cost(
        self, *, window: CostWindow, services: Sequence[str], limit: int
    ) -> ReaderPage:
        """Items: day (date), service, amount (str), currency, estimated (bool or None)."""
        ...

    async def get_invocation_logging(self) -> Mapping[str, Any]:
        """Booleans ``cloudwatch`` and ``s3`` only: which destination types are configured."""
        ...

    async def close(self) -> None: ...
