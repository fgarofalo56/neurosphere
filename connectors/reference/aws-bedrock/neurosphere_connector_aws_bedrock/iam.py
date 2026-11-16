"""The least-privilege, read-only IAM policy the connector needs (single source of truth).

The README embeds ``policy_json()`` verbatim and a test keeps the two equal. The eight actions
are exactly ``manifest.IAM_ACTIONS``; each was read in the AWS Service Reference (observed
2026-11-16) and is a List or Read action (``IsWrite`` false). ``Resource`` is ``*`` because the
list and ``ce``/``cloudwatch`` read actions are not usefully resource-scoped here (the Service
Reference lists a ``guardrail`` resource type for ``ListGuardrails``, a ``billingview`` type for
``ce:GetCostAndUsage`` and a ``dataset`` type for ``cloudwatch:GetMetricData``; scoping them
is left to the operator and not verified here).

Deliberately absent: every ``bedrock:Invoke*``/``Converse*``, ``logs:*``, ``s3:*``, ``iam:*`` and
any write or tagging action.
"""

from __future__ import annotations

import json
from typing import Any

from neurosphere_connector_aws_bedrock.manifest import IAM_ACTIONS

__all__ = ["IAM_POLICY", "policy_json"]

IAM_POLICY: dict[str, Any] = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "NeuroSphereBedrockMetadataRead",
            "Effect": "Allow",
            "Action": list(IAM_ACTIONS),
            "Resource": "*",
        }
    ],
}


def policy_json() -> str:
    return json.dumps(IAM_POLICY, indent=2)
