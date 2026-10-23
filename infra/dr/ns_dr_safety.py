"""Target safety for the DR scripts (PRP-21 item 5).

Default is the local compose emulators only. A non-local endpoint is refused unless BOTH the
environment variable ``NS_LIVE_APPROVED=1`` and an explicit ``--target`` name are given. A
restore against a non-local target additionally needs ``--confirm-target`` equal to ``--target``.
Hosts are compared by parsed hostname, never by substring.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
LIVE_APPROVED_ENV = "NS_LIVE_APPROVED"
DRILL_PREFIX = "drill-"


class TargetRefusedError(Exception):
    """Raised when a target is not allowed. The message never contains a credential."""


@dataclass(frozen=True)
class TargetPolicy:
    target: str | None = None
    confirm_target: str | None = None
    env: Mapping[str, str] | None = None


def is_local_endpoint(url: str) -> bool:
    """True only when the URL's parsed hostname is a loopback name."""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return False
    return host is not None and host in LOCAL_HOSTS


def blob_endpoint_from_connection_string(connection_string: str) -> str:
    """The blob endpoint a connection string would talk to.

    ``UseDevelopmentStorage=true`` is Azurite (loopback). An explicit ``BlobEndpoint`` is used as
    given. Anything else resolves to a public storage endpoint, reported as a non-local URL.
    """
    parts: dict[str, str] = {}
    for item in connection_string.split(";"):
        if "=" in item:
            key, _, value = item.partition("=")
            parts[key.strip().lower()] = value.strip()
    if parts.get("blobendpoint"):
        return parts["blobendpoint"]
    if parts.get("usedevelopmentstorage", "").lower() == "true":
        return "http://127.0.0.1:10000/"
    account = parts.get("accountname", "unknown")
    suffix = parts.get("endpointsuffix", "core.windows.net")
    return f"https://{account}.blob.{suffix}/"


def authorize(endpoints: Iterable[str], policy: TargetPolicy, *, restore: bool) -> bool:
    """Return True when every endpoint is local, False when a live target was authorized.

    Raises ``TargetRefusedError`` otherwise. ``restore`` selects the stricter confirmation rule.
    """
    env = policy.env if policy.env is not None else {}
    remote = [e for e in endpoints if not is_local_endpoint(e)]
    if not remote:
        return True
    if env.get(LIVE_APPROVED_ENV) != "1":
        raise TargetRefusedError(f"non-local endpoint refused: {LIVE_APPROVED_ENV}=1 is required")
    if not policy.target:
        raise TargetRefusedError(
            "non-local endpoint refused: an explicit --target name is required"
        )
    if restore and policy.confirm_target != policy.target:
        raise TargetRefusedError(
            "non-local restore refused: --confirm-target must equal --target exactly"
        )
    return False


def require_drill_name(name: str) -> str:
    """Drill code may only create, overwrite or delete drill-namespaced databases/containers."""
    if not name.startswith(DRILL_PREFIX) or len(name) <= len(DRILL_PREFIX):
        raise TargetRefusedError(f"refusing to touch {name!r}: not a drill- namespaced resource")
    return name
