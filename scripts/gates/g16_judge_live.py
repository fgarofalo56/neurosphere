"""G16 live judge run (PRP-16 items 2 and 7): an optional, operator-approved paid judge call.

Refuses unless NS_LIVE_APPROVED=1. The check is the first statement of ``main`` and runs before
any project, azure or network import: this module imports only ``os`` and ``sys`` at top level.

With approval it builds ``EndpointJudge`` (an approved Azure OpenAI-style chat-completions
endpoint; Entra / managed identity via DefaultAzureCredential, no key from arguments or
environment) and scores one SYNTHETIC request. Configuration comes from environment variables:

    NS_CLOUD                   commercial | government   (the endpoint must belong to this cloud)
    NS_G16_JUDGE_ENDPOINT      https endpoint of the approved account
    NS_G16_JUDGE_DEPLOYMENT    deployment name
    NS_G16_JUDGE_API_VERSION   optional

The full pilot run (``EvaluationService.run_offline`` over the synthetic dataset with a small
``BudgetLedger``) and the evidence write to docs/evidence/G16/ remain OPEN: this script prints
whitelisted fields only (verdict kind, token counts) and is not evidence until an operator runs it
and records the result.

Exit codes: 2 REFUSED (approval missing; nothing was run); 3 OPEN (approved but configuration
missing or the endpoint refused for the cloud; nothing was run); 0 only after a real judge call
returned a verdict or an abstention.
"""

from __future__ import annotations

import asyncio
import os
import sys


def _config_error() -> str | None:
    if os.environ.get("NS_CLOUD") not in ("commercial", "government"):
        return "NS_CLOUD must be commercial or government"
    for name in ("NS_G16_JUDGE_ENDPOINT", "NS_G16_JUDGE_DEPLOYMENT"):
        if not os.environ.get(name):
            return f"{name} is not set"
    return None


async def _run() -> int:
    # Deferred imports: only reached after approval and configuration checks.
    from azure.identity.aio import DefaultAzureCredential
    from neurosphere_core.copilot.models.endpoints import AdapterConfig
    from neurosphere_core.errors import NeuroSphereError
    from neurosphere_core.evaluation.endpoint_judge import EndpointJudge
    from neurosphere_core.evaluation.judge import JudgeRequest

    cloud = "government" if os.environ["NS_CLOUD"] == "government" else "commercial"
    config = AdapterConfig(
        kind="approved_endpoint",
        endpoint=os.environ["NS_G16_JUDGE_ENDPOINT"],
        deployment=os.environ["NS_G16_JUDGE_DEPLOYMENT"],
        api_version=os.environ.get("NS_G16_JUDGE_API_VERSION") or None,
    )
    async with DefaultAzureCredential() as credential:
        try:
            judge = EndpointJudge(config, cloud=cloud, credential=credential)
            response = await judge.score(
                JudgeRequest(
                    judge_config_id="g16-live",
                    judge_config_version="1",
                    rubric_id="g16-groundedness",
                    rubric_version="1",
                    dimension="groundedness",
                    item_id="g16-synthetic-1",
                    classification="public",
                    payload={"answer": "Paris is the capital of France.", "context": ["France"]},
                )
            )
        except NeuroSphereError as exc:
            print(f"OPEN: G16 live judge call did not complete: {type(exc).__name__}.")
            return 3
    kind = "abstained" if response.abstained else "scored"
    print(
        f"G16 live judge call returned ({kind}); input_tokens={response.input_tokens} "
        f"output_tokens={response.output_tokens}. Record the result in docs/evidence/G16/."
    )
    return 0


def main() -> int:
    if os.environ.get("NS_LIVE_APPROVED") != "1":
        print(
            "REFUSED: g16_judge_live.py would make a paid judge call and needs operator approval; "
            "set NS_LIVE_APPROVED=1. No connection was attempted.",
            file=sys.stderr,
        )
        return 2
    problem = _config_error()
    if problem is not None:
        print(f"OPEN: G16 live judge run did not run: {problem}.")
        return 3
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
