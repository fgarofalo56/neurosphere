"""In-memory APIM test double: an ARM resource tree with ETags, implementing ``ApimArm``.

Used by every unit test of this package (and available to later PRP-34 items and the worker
tests). It applies the same path guard and secret stripping as ``HttpApimArm`` and models the
documented APIM concurrency contract: an update without ``If-Match`` or with a stale one fails
with ``412`` (``stale_version``), a create on an existing path without ``If-Match`` fails the same
way, and every successful write mints a new ETag.

Failure injection: ``fail(method, path, error, times=1)`` raises ``error`` on the next matching
call(s); ``before`` is called with ``(method, path)`` ahead of every call so a test can simulate a
concurrent change between the planner's read and the applier's write.
"""

from __future__ import annotations

import copy
import itertools
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from neurosphere_core.errors import InvalidSchemaError

from neurosphere_connector_apim_gateway.arm import (
    ArmResource,
    check_path,
    map_status,
    strip_secrets,
)
from neurosphere_connector_apim_gateway.models import ResourceType, classify_path

__all__ = ["ArmCall", "InMemoryApim"]

_POLICY_TYPES = frozenset(
    {ResourceType.POLICY_FRAGMENT, ResourceType.API_POLICY, ResourceType.PRODUCT_POLICY}
)


@dataclass(frozen=True)
class ArmCall:
    method: str
    path: str
    if_match: str | None = None


@dataclass
class _Failure:
    error: Exception
    remaining: int


@dataclass
class InMemoryApim:
    """A fake API Management service. ``resources`` maps relative path -> (properties, etag)."""

    service_etag: str = '"svc-1"'
    reformat_policies: bool = False
    resources: dict[str, tuple[dict[str, Any], str]] = field(
        default_factory=dict[str, tuple[dict[str, Any], str]]
    )
    calls: list[ArmCall] = field(default_factory=list[ArmCall])
    before: Callable[[str, str], None] | None = None
    _failures: dict[tuple[str, str], _Failure] = field(
        default_factory=dict[tuple[str, str], _Failure]
    )
    _counter: itertools.count[int] = field(default_factory=lambda: itertools.count(1))

    # -- test helpers ----------------------------------------------------------------------

    def seed(self, path: str, properties: Mapping[str, Any]) -> str:
        """Place a resource directly (no call recorded); returns its ETag."""
        etag = self._mint()
        self.resources[path] = (copy.deepcopy(dict(properties)), etag)
        return etag

    def fail(self, method: str, path: str, error: Exception, *, times: int = 1) -> None:
        self._failures[(method, path)] = _Failure(error, times)

    def writes(self) -> list[ArmCall]:
        return [c for c in self.calls if c.method != "GET"]

    def etag_of(self, path: str) -> str | None:
        entry = self.resources.get(path)
        return entry[1] if entry else None

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {p: copy.deepcopy(props) for p, (props, _) in self.resources.items()}

    # -- internals -------------------------------------------------------------------------

    def _mint(self) -> str:
        return f'"etag-{next(self._counter)}"'

    def _enter(self, method: str, path: str, if_match: str | None = None) -> None:
        self.calls.append(ArmCall(method, path, if_match))
        if self.before is not None:
            self.before(method, path)
        failure = self._failures.get((method, path))
        if failure is not None and failure.remaining > 0:
            failure.remaining -= 1
            raise failure.error

    # -- ApimArm ---------------------------------------------------------------------------

    async def get(self, path: str) -> ArmResource | None:
        rtype = check_path(path, allow_service=True)
        self._enter("GET", path)
        if path == "":
            return ArmResource(path="", properties={}, etag=self.service_etag)
        entry = self.resources.get(path)
        if entry is None:
            return None
        props, etag = entry
        return ArmResource(
            path=path, properties=strip_secrets(rtype, copy.deepcopy(props)), etag=etag
        )

    async def put(self, path: str, properties: Mapping[str, Any], *, if_match: str | None) -> None:
        rtype = check_path(path)
        self._enter("PUT", path, if_match)
        if any(k in properties for k in ("primaryKey", "secondaryKey")) or (
            rtype is ResourceType.NAMED_VALUE and "value" in properties
        ):
            raise InvalidSchemaError("secret material is never written", reason="secret_in_payload")
        entry = self.resources.get(path)
        if entry is None and if_match not in (None, "*"):
            raise map_status(412)
        if entry is not None and if_match != "*" and if_match != entry[1]:
            raise map_status(412)
        stored = copy.deepcopy(dict(properties))
        if (
            self.reformat_policies
            and rtype in _POLICY_TYPES
            and isinstance(stored.get("value"), str)
        ):
            # APIM re-indents policy XML on save; verify must compare normalised XML.
            stored["value"] = stored["value"].replace("><", ">\n    <")
        if rtype is ResourceType.SUBSCRIPTION:
            # APIM generates keys; the double stores them so tests can prove they never leak.
            stored.setdefault("primaryKey", "pk-generated-secret")
            stored.setdefault("secondaryKey", "sk-generated-secret")
        self.resources[path] = (stored, self._mint())

    async def delete(self, path: str, *, if_match: str) -> bool:
        check_path(path)
        self._enter("DELETE", path, if_match)
        entry = self.resources.get(path)
        if entry is None:
            return False
        if if_match != "*" and if_match != entry[1]:
            raise map_status(412)
        del self.resources[path]
        return True

    def kind_of(self, path: str) -> ResourceType | None:
        return classify_path(path)
