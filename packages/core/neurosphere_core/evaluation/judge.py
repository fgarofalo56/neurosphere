"""Judge protocol and the recorded-fixture judge (PRP-16 item 1).

No network and no SDK imports. CI never makes a paid judge call: judge behaviour in tests comes
from ``RecordedFixtureJudge``, a map of request hash to canned response. A request with no
recorded fixture raises; a score is never fabricated.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Protocol, Self, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from neurosphere_core.evaluation.registry.models import Dimension, OpaqueId, Version

__all__ = [
    "Judge",
    "JudgeRequest",
    "JudgeResponse",
    "MissingFixtureError",
    "RecordedFixtureJudge",
    "request_hash",
]


class JudgeRequest(BaseModel):
    """One scoring request. ``payload`` is redacted, JSON-safe content; ``classification`` is
    carried so the caller's approval check and the audit trail see what was sent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    judge_config_id: OpaqueId
    judge_config_version: Version
    rubric_id: OpaqueId
    rubric_version: Version
    dimension: Dimension
    item_id: OpaqueId
    classification: str | None
    payload: dict[str, Any]

    @model_validator(mode="after")
    def _payload_is_json_safe(self) -> Self:
        try:
            json.dumps(self.payload)
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must be JSON-serialisable") from exc
        return self


def request_hash(request: JudgeRequest) -> str:
    """sha256 over canonical JSON (sorted keys, compact separators) of the request."""
    canonical = json.dumps(
        request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class JudgeResponse(BaseModel):
    """``value`` is null only when the judge abstained; unknown is never 0."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: float | None
    abstained: bool
    input_tokens: Annotated[int, Field(ge=0)]
    output_tokens: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _abstention_consistent(self) -> Self:
        if self.abstained != (self.value is None):
            raise ValueError("value must be null exactly when the judge abstained")
        return self


@runtime_checkable
class Judge(Protocol):
    async def score(self, request: JudgeRequest) -> JudgeResponse: ...


class MissingFixtureError(LookupError):
    """No recorded response exists for a request hash."""

    def __init__(self, digest: str, item_id: str) -> None:
        super().__init__(f"no recorded judge fixture for request {digest} (item {item_id})")
        self.digest = digest


class RecordedFixtureJudge:
    """Replays recorded responses keyed by ``request_hash``; records every call it receives."""

    def __init__(self, fixtures: Mapping[str, JudgeResponse | Mapping[str, Any]]) -> None:
        self._fixtures: dict[str, JudgeResponse] = {
            digest: r if isinstance(r, JudgeResponse) else JudgeResponse.model_validate(r)
            for digest, r in fixtures.items()
        }
        self.calls: list[JudgeRequest] = []

    @classmethod
    def from_file(cls, path: Path | str) -> Self:
        """Load ``{"responses": {hash: response}}`` (or a bare hash map) from a JSON file."""
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        responses = doc["responses"] if isinstance(doc, dict) and "responses" in doc else doc
        return cls(responses)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def has_fixture(self, request: JudgeRequest) -> bool:
        """Whether a response is recorded for ``request`` (does not count as a call)."""
        return request_hash(request) in self._fixtures

    async def score(self, request: JudgeRequest) -> JudgeResponse:
        self.calls.append(request)
        digest = request_hash(request)
        try:
            return self._fixtures[digest]
        except KeyError:
            raise MissingFixtureError(digest, request.item_id) from None
