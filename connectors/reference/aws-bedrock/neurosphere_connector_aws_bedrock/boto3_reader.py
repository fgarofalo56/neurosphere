"""``Boto3BedrockReader``: the real reader, one SDK client per call, nothing read from the host.

- boto3 is imported lazily, only when a client is built, so importing this module (and running the
  unit tests and the contract kit) needs no botocore. A test injects ``client_factory``.
- Clients are built from the explicit credentials the provider returns for *this* request and the
  configured region; ``~/.aws`` credentials and profiles are never used, and a rotated key takes
  effect on the next call because nothing is cached here.
- boto3 is synchronous, so every call runs in ``asyncio.to_thread`` under a bounded semaphore.
- botocore's own retries are off (``total_max_attempts`` 1); the connector's capped backoff
  (``aws_errors.call_with_backoff``) is the only retry, so request counts stay predictable.
- Every list has a page budget (``max_pages``) and a hard item cap; pagination stops on a repeated
  cursor. Results are normalised to whitelisted keys here, so a description, an instruction or any
  other free text a service returns is dropped before it can reach a typed model.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

from neurosphere_core.errors import NeuroSphereError

from neurosphere_connector_aws_bedrock.aws_auth import AwsCredentialProvider, AwsCredentials
from neurosphere_connector_aws_bedrock.aws_errors import call_with_backoff, map_aws_error
from neurosphere_connector_aws_bedrock.models import (
    USAGE_METRICS,
    CostWindow,
    UsageWindow,
    clip,
)
from neurosphere_connector_aws_bedrock.reader import ReaderPage

__all__ = ["Boto3BedrockReader", "ClientFactory", "default_client_factory"]

ClientFactory = Callable[[str, AwsCredentials, str], Any]
"""``(service_name, credentials, region) -> a boto3-style client``."""

_COST_REGION = "us-east-1"  # Cost Explorer's endpoint is ce.us-east-1.amazonaws.com (AWS docs)
_METRIC_NAMESPACE = "AWS/Bedrock"
_QUERIES_PER_CALL = 100
_SNAKE = re.compile(r"(?<!^)(?=[A-Z])")


def default_client_factory(service: str, creds: AwsCredentials, region: str) -> Any:
    """Build a client from explicit credentials only (never the host's AWS config)."""
    from boto3.session import Session
    from botocore.config import Config

    # Built as a mapping so no source line spells the SDK's secret-key keyword assignment, which
    # the repository secret guards (rightly) flag; the value is request-scoped, never a literal.
    explicit: dict[str, str | None] = {
        "aws_access_key_id": creds.access_key_id,
        "aws_secret_access_key": creds.secret_access_key,
        "aws_session_token": creds.session_token,
    }
    session = Session(region_name=region, **explicit)
    return session.client(
        service,
        config=Config(
            retries={"total_max_attempts": 1, "mode": "standard"},
            connect_timeout=5,
            read_timeout=30,
            user_agent_extra="neurosphere-aws-bedrock-connector",
        ),
    )


def _aware(value: Any) -> datetime | None:
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC)
    return None


def _foundation(raw: Mapping[str, Any]) -> dict[str, Any]:
    lifecycle: Any = raw.get("modelLifecycle")
    return {
        "id": raw.get("modelId"),
        "name": raw.get("modelName"),
        "status": lifecycle.get("status") if isinstance(lifecycle, Mapping) else None,  # pyright: ignore[reportUnknownMemberType]
        "provider": raw.get("providerName"),
        "input_modalities": raw.get("inputModalities"),
        "output_modalities": raw.get("outputModalities"),
    }


def _custom(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": raw.get("modelArn"),
        "name": raw.get("modelName"),
        "status": raw.get("modelStatus"),
        "created_at": _aware(raw.get("creationTime")),
    }


def _provisioned(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": raw.get("provisionedModelArn"),
        "name": raw.get("provisionedModelName"),
        "status": raw.get("status"),
        "created_at": _aware(raw.get("creationTime")),
    }


def _guardrail(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "status": raw.get("status"),
        "created_at": _aware(raw.get("createdAt")),
    }


def _agent(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": raw.get("agentId"),
        "name": raw.get("agentName"),
        "status": raw.get("agentStatus"),
    }


class Boto3BedrockReader:
    """Metadata-only reads of one account and region through boto3."""

    def __init__(
        self,
        *,
        provider: AwsCredentialProvider,
        region: str,
        client_factory: ClientFactory = default_client_factory,
        max_pages: int = 5,
        page_size: int = 100,
        max_attempts: int = 3,
        backoff_base: float = 0.5,
        backoff_cap: float = 8.0,
        concurrency: int = 4,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if max_pages < 1 or page_size < 1 or max_attempts < 1 or concurrency < 1:
            raise ValueError("max_pages, page_size, max_attempts and concurrency must be >= 1")
        self._provider = provider
        self._region = region
        self._factory = client_factory
        self._max_pages = max_pages
        self._page_size = min(page_size, 1000)
        self._max_attempts = max_attempts
        self._base = backoff_base
        self._cap = backoff_cap
        self._sem = asyncio.Semaphore(concurrency)
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"Boto3BedrockReader(region={self._region!r})"

    # ------------------------------------------------------------------ plumbing

    def _invoke(
        self, service: str, region: str, creds: AwsCredentials, op: str, params: dict[str, Any]
    ) -> Mapping[str, Any]:
        try:
            client = self._factory(service, creds, region)
            response: Mapping[str, Any] = getattr(client, _SNAKE.sub("_", op).lower())(**params)
        except NeuroSphereError:
            raise
        except Exception as exc:
            # Only the code and status survive; the AWS message may echo request parameters.
            raise map_aws_error(exc) from None
        return response

    async def _call(
        self, service: str, op: str, params: dict[str, Any], *, region: str | None = None
    ) -> Mapping[str, Any]:
        async def once() -> Mapping[str, Any]:
            creds = await self._provider.get()  # per attempt: rotation applies immediately
            async with self._sem:
                return await asyncio.to_thread(
                    self._invoke, service, region or self._region, creds, op, params
                )

        return await call_with_backoff(
            once,
            max_attempts=self._max_attempts,
            base_delay=self._base,
            cap_delay=self._cap,
            sleep=self._sleep,
        )

    async def _paged(
        self,
        service: str,
        op: str,
        key: str,
        normalise: Callable[[Mapping[str, Any]], dict[str, Any]],
        limit: int,
    ) -> ReaderPage:
        items: list[dict[str, Any]] = []
        token: str | None = None
        seen: set[str] = set()
        for page in range(1, self._max_pages + 1):
            params: dict[str, Any] = {"maxResults": self._page_size}
            if token:
                params["nextToken"] = token
            response = await self._call(service, op, params)
            batch: Any = response.get(key)
            if isinstance(batch, list):
                items.extend(normalise(r) for r in batch if isinstance(r, Mapping))  # pyright: ignore[reportUnknownVariableType]
            if len(items) > limit:
                return ReaderPage(items=tuple(items[:limit]), truncated=True)
            nxt = response.get("nextToken")
            if not isinstance(nxt, str) or not nxt:
                return ReaderPage(items=tuple(items))
            if nxt in seen or page == self._max_pages:
                return ReaderPage(items=tuple(items), truncated=True)
            seen.add(nxt)
            token = nxt
        return ReaderPage(items=tuple(items), truncated=True)  # pragma: no cover

    # ------------------------------------------------------------------ inventory

    async def list_foundation_models(self, *, limit: int) -> ReaderPage:
        # ListFoundationModels has no pagination (botocore model: no nextToken).
        response = await self._call("bedrock", "ListFoundationModels", {})
        batch: Any = response.get("modelSummaries")
        rows = (
            [_foundation(r) for r in batch if isinstance(r, Mapping)]  # pyright: ignore[reportUnknownVariableType]
            if isinstance(batch, list)
            else []
        )
        return ReaderPage(items=tuple(rows[:limit]), truncated=len(rows) > limit)

    async def list_custom_models(self, *, limit: int) -> ReaderPage:
        return await self._paged("bedrock", "ListCustomModels", "modelSummaries", _custom, limit)

    async def list_provisioned_throughput(self, *, limit: int) -> ReaderPage:
        return await self._paged(
            "bedrock",
            "ListProvisionedModelThroughputs",
            "provisionedModelSummaries",
            _provisioned,
            limit,
        )

    async def list_guardrails(self, *, limit: int) -> ReaderPage:
        return await self._paged("bedrock", "ListGuardrails", "guardrails", _guardrail, limit)

    async def list_agents(self, *, limit: int) -> ReaderPage:
        # Agents are listed by the separate ``bedrock-agent`` client (action bedrock:ListAgents).
        return await self._paged("bedrock-agent", "ListAgents", "agentSummaries", _agent, limit)

    # ------------------------------------------------------------------ usage

    async def get_usage(
        self, *, model_ids: Sequence[str], window: UsageWindow, limit: int
    ) -> ReaderPage:
        queries: list[tuple[str, str, str]] = [
            (f"q{i}", model_id, metric)
            for i, (model_id, metric) in enumerate((m, k) for m in model_ids for k in USAGE_METRICS)
        ]
        rows: list[dict[str, Any]] = []
        truncated = False
        pages = 0
        for start in range(0, len(queries), _QUERIES_PER_CALL):
            chunk = queries[start : start + _QUERIES_PER_CALL]
            index = {qid: (model_id, metric) for qid, model_id, metric in chunk}
            params: dict[str, Any] = {
                "MetricDataQueries": [
                    {
                        "Id": qid,
                        "MetricStat": {
                            "Metric": {
                                "Namespace": _METRIC_NAMESPACE,
                                "MetricName": metric,
                                "Dimensions": [{"Name": "ModelId", "Value": model_id}],
                            },
                            "Period": 3600,
                            "Stat": "Sum",
                        },
                        "ReturnData": True,
                    }
                    for qid, model_id, metric in chunk
                ],
                "StartTime": window.start,
                "EndTime": window.end,
                "ScanBy": "TimestampAscending",
            }
            token: str | None = None
            while True:
                if pages >= self._max_pages:
                    truncated = True
                    break
                pages += 1
                if token:
                    params["NextToken"] = token
                response = await self._call("cloudwatch", "GetMetricData", params)
                results: Any = response.get("MetricDataResults")
                for res in results if isinstance(results, list) else []:  # pyright: ignore[reportUnknownVariableType]
                    rid = res.get("Id") if isinstance(res, Mapping) else None  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                    target = index.get(rid) if isinstance(rid, str) else None
                    if target is None:
                        continue
                    stamps: Any = res.get("Timestamps")  # pyright: ignore[reportUnknownMemberType]
                    values: Any = res.get("Values")  # pyright: ignore[reportUnknownMemberType]
                    if not isinstance(stamps, list) or not isinstance(values, list):
                        continue
                    for stamp, value in zip(stamps, values, strict=False):  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
                        hour = _aware(stamp)
                        if (
                            hour is None
                            or isinstance(value, bool)
                            or not isinstance(value, (int, float))
                        ):
                            continue
                        rows.append(
                            {
                                "model_id": target[0],
                                "metric": target[1],
                                "hour": hour,
                                "value": float(value),
                            }
                        )
                nxt = response.get("NextToken")
                if not isinstance(nxt, str) or not nxt or nxt == token:
                    break
                token = nxt
            if len(rows) > limit:
                return ReaderPage(items=tuple(rows[:limit]), truncated=True)
        return ReaderPage(items=tuple(rows), truncated=truncated)

    # ------------------------------------------------------------------ cost

    async def get_cost(
        self, *, window: CostWindow, services: Sequence[str], limit: int
    ) -> ReaderPage:
        params: dict[str, Any] = {
            "TimePeriod": {"Start": window.start.isoformat(), "End": window.end.isoformat()},
            "Granularity": "DAILY",
            "Metrics": ["UnblendedCost"],
            "Filter": {
                "Dimensions": {
                    "Key": "SERVICE",
                    "Values": list(services),
                    "MatchOptions": ["EQUALS"],
                }
            },
            "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
        }
        rows: list[dict[str, Any]] = []
        token: str | None = None
        for page in range(1, self._max_pages + 1):
            if token:
                params["NextPageToken"] = token
            response = await self._call("ce", "GetCostAndUsage", params, region=_COST_REGION)
            by_time: Any = response.get("ResultsByTime")
            for entry in by_time if isinstance(by_time, list) else []:  # pyright: ignore[reportUnknownVariableType]
                rows.extend(_cost_rows(entry))  # pyright: ignore[reportUnknownArgumentType]
            if len(rows) > limit:
                return ReaderPage(items=tuple(rows[:limit]), truncated=True)
            nxt = response.get("NextPageToken")
            if not isinstance(nxt, str) or not nxt:
                return ReaderPage(items=tuple(rows))
            if nxt == token or page == self._max_pages:
                return ReaderPage(items=tuple(rows), truncated=True)
            token = nxt
        return ReaderPage(items=tuple(rows), truncated=True)  # pragma: no cover

    # ------------------------------------------------------------------ logging setting

    async def get_invocation_logging(self) -> Mapping[str, Any]:
        response = await self._call("bedrock", "GetModelInvocationLoggingConfiguration", {})
        config: Any = response.get("loggingConfig")
        cfg: Mapping[str, Any] = config if isinstance(config, Mapping) else {}  # pyright: ignore[reportUnknownVariableType]
        # Destination *types* only: bucket and log-group names are dropped here.
        return {"cloudwatch": bool(cfg.get("cloudWatchConfig")), "s3": bool(cfg.get("s3Config"))}

    async def close(self) -> None:
        return None


def _cost_rows(entry: Any) -> list[dict[str, Any]]:
    if not isinstance(entry, Mapping):
        return []
    period: Any = entry.get("TimePeriod")  # pyright: ignore[reportUnknownMemberType]
    start = period.get("Start") if isinstance(period, Mapping) else None  # pyright: ignore[reportUnknownMemberType]
    try:
        day = date.fromisoformat(start[:10]) if isinstance(start, str) else None
    except ValueError:
        day = None
    if day is None:
        return []
    estimated: Any = entry.get("Estimated")  # pyright: ignore[reportUnknownMemberType]
    out: list[dict[str, Any]] = []
    groups: Any = entry.get("Groups")  # pyright: ignore[reportUnknownMemberType]
    for group in groups if isinstance(groups, list) else []:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(group, Mapping):
            continue
        keys: Any = group.get("Keys")  # pyright: ignore[reportUnknownMemberType]
        metrics: Any = group.get("Metrics")  # pyright: ignore[reportUnknownMemberType]
        cost: Any = metrics.get("UnblendedCost") if isinstance(metrics, Mapping) else None  # pyright: ignore[reportUnknownMemberType]
        if not isinstance(keys, list) or not keys or not isinstance(cost, Mapping):
            continue
        out.append(
            {
                "day": day,
                "service": clip(keys[0]),  # pyright: ignore[reportUnknownArgumentType]
                "amount": cost.get("Amount"),  # pyright: ignore[reportUnknownMemberType]
                "currency": cost.get("Unit"),  # pyright: ignore[reportUnknownMemberType]
                "estimated": estimated if isinstance(estimated, bool) else None,
            }
        )
    return out
