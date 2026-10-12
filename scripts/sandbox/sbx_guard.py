"""Safety guards for the sandbox seed/replay CLI (PRP-03 item 4).

Pure functions, no network. Every database/container name must start with ``sandbox-`` and
every endpoint must be a loopback emulator address. There is deliberately no override.
"""

from __future__ import annotations

import base64
import ipaddress
import os
from urllib.parse import urlparse

PREFIX = "sandbox-"
DEFAULT_COSMOS_ENDPOINT = "http://localhost:8081"
ENV_COSMOS_ENDPOINT = "NS_SANDBOX_COSMOS_ENDPOINT"
ENV_COSMOS_KEY = "NS_SANDBOX_COSMOS_KEY"
ENV_EVENTHUBS_CONN = "NS_SANDBOX_EVENTHUBS_CONNECTION_STRING"
_LOCAL_NAMES = frozenset({"localhost"})


class GuardError(RuntimeError):
    """Raised when a request would leave the sandbox. Messages never contain secrets."""


def require_sandbox_name(name: str, kind: str = "resource") -> str:
    if not isinstance(name, str) or not name.startswith(PREFIX) or len(name) <= len(PREFIX):
        raise GuardError(f"refusing {kind} {name!r}: sandbox names must start with {PREFIX!r}")
    return name


def is_local_host(host: str | None) -> bool:
    if not host:
        return False
    host = host.strip("[]").lower()
    if host in _LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def require_local_endpoint(url: str) -> str:
    """Accept only loopback hosts. Raises without echoing userinfo or query strings."""
    parsed = urlparse(url if "://" in url else f"//{url}")
    if not is_local_host(parsed.hostname):
        raise GuardError(
            f"refusing endpoint host {parsed.hostname!r}: only local emulator addresses "
            "(localhost, loopback) are allowed; there is no override"
        )
    return url


def eventhubs_endpoint_host(conn: str) -> str | None:
    for part in conn.split(";"):
        key, _, value = part.partition("=")
        if key.strip().lower() == "endpoint":
            return urlparse(value.strip()).hostname
    return None


def require_local_connection_string(conn: str) -> str:
    host = eventhubs_endpoint_host(conn)
    if not is_local_host(host):
        raise GuardError(
            f"refusing Event Hubs endpoint host {host!r}: only local emulator addresses are "
            "allowed; there is no override"
        )
    return conn


def cosmos_settings(env: dict[str, str] | None = None) -> tuple[str, str]:
    """Return (endpoint, key). The key is a runtime-built dummy: the vNext emulator ignores it."""
    env = dict(os.environ) if env is None else env
    endpoint = require_local_endpoint(env.get(ENV_COSMOS_ENDPOINT, DEFAULT_COSMOS_ENDPOINT))
    key = env.get(ENV_COSMOS_KEY) or base64.b64encode(b"sandbox-local-emulator").decode("ascii")
    return endpoint, key


def eventhubs_connection_string(env: dict[str, str] | None = None) -> str:
    """Return the connection string from the environment, else build the emulator's at runtime."""
    env = dict(os.environ) if env is None else env
    conn = env.get(ENV_EVENTHUBS_CONN)
    if not conn:
        # Assembled from parts at runtime so no connection string is committed as a literal.
        parts = [
            "Endpoint=sb://localhost",
            "SharedAccessKeyName=RootManageSharedAccessKey",
            "SharedAccessKey=" + "SAS_KEY" + "_VALUE",
            "UseDevelopmentEmulator=true",
        ]
        conn = ";".join(parts) + ";"
    return require_local_connection_string(conn)
