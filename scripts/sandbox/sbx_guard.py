"""Safety guards for the sandbox seed/replay CLI (PRP-03 item 4).

Pure functions, no network. Every database/container name must start with ``sandbox-`` and
every endpoint must be a loopback emulator address. There is deliberately no override for the
local path (``require_local_endpoint`` and friends).

The single exception is :func:`require_hosted_endpoint` (PRP-32): it admits exactly the hosts a
registered NeuroSphere demo deployment recorded in ``temp/hosted-demo/registration.json``, and
only with operator approval (``NS_LIVE_APPROVED=1``), a matching deployment id
(``NS_SANDBOX_HOSTED_DEPLOYMENT_ID``), the Commercial cloud, the Commercial endpoint suffix for the
resource kind and no key or connection string anywhere in the environment (Entra only). It never
returns a credential. It is not an override of the local path: it widens nothing else.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import os
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse, urlsplit

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


# -- registered hosted environment (PRP-32) --------------------------------------------------

ENV_LIVE_APPROVED: Final = "NS_LIVE_APPROVED"
ENV_HOSTED_DEPLOYMENT_ID: Final = "NS_SANDBOX_HOSTED_DEPLOYMENT_ID"
DEFAULT_REGISTRATION: Final = Path("temp") / "hosted-demo" / "registration.json"
#: Environment variables that carry a key or connection string. Any of them set refuses the
#: hosted path: hosted access is Entra only.
CREDENTIAL_ENV_NAMES: Final = (
    ENV_COSMOS_KEY,
    "NS_COSMOS_KEY",
    ENV_EVENTHUBS_CONN,
    "NS_EVENTHUBS_CONNECTION_STRING",
    "NS_BLOB_CONNECTION_STRING",
    "NS_AUTH_PSEUDONYM_KEY",
)
#: kind -> registration field holding the bare host.
_REGISTRATION_HOST_FIELD: Final = {
    "cosmos": "cosmos_host",
    "eventhubs": "eventhubs_host",
    "blob": "blob_host",
    "keyvault": "key_vault_host",
}
#: Commercial suffixes the CloudProfile does not carry (it has Cosmos and Event Hubs only).
_EXTRA_COMMERCIAL_SUFFIX: Final = {
    "blob": ".blob.core.windows.net",
    "keyvault": ".vault.azure.net",
}
_HTTPS_DEFAULT_PORT: Final = 443


def _commercial_suffix(kind: str) -> str:
    from neurosphere_core.cloud import CloudName, profile_for

    profile = profile_for(CloudName.COMMERCIAL)
    if kind == "cosmos":
        return profile.cosmos_suffix
    if kind == "eventhubs":
        return profile.eventhubs_suffix
    return _EXTRA_COMMERCIAL_SUFFIX[kind]


def load_registration(registration_path: str | Path) -> dict[str, Any]:
    """Read the hosted registration (D9 schema 1). Never echoes file content."""
    try:
        raw = Path(registration_path).read_text(encoding="utf-8")
    except OSError:
        raise GuardError("refusing hosted endpoint: the registration file is missing") from None
    try:
        doc = json.loads(raw)
    except ValueError:
        raise GuardError(
            "refusing hosted endpoint: the registration file is not valid JSON"
        ) from None
    if not isinstance(doc, dict) or doc.get("schema") != 1:
        raise GuardError("refusing hosted endpoint: the registration has an unsupported schema")
    return doc


def _host_in_suffix(host: str, suffix: str) -> bool:
    """``host`` is a strict subdomain of ``suffix`` (which starts with a dot)."""
    return len(host) > len(suffix) and host[-len(suffix) :] == suffix


def require_hosted_endpoint(
    url: str,
    *,
    kind: str,
    env: dict[str, str] | Any,
    registration_path: str | Path,
) -> str:
    """Return the normalized ``https://<host>/`` endpoint for the registered ``kind`` host.

    ``kind`` is ``cosmos``, ``eventhubs``, ``blob`` or ``keyvault``. Anything outside the
    registered environment raises :class:`GuardError`; messages never echo userinfo or secrets.
    """
    field_name = _REGISTRATION_HOST_FIELD.get(kind)
    if field_name is None:
        raise GuardError("refusing hosted endpoint: unknown resource kind")
    if env.get(ENV_LIVE_APPROVED) != "1":
        raise GuardError(
            f"refusing hosted {kind} endpoint: operator approval ({ENV_LIVE_APPROVED}=1) is not set"
        )
    for name in CREDENTIAL_ENV_NAMES:
        if env.get(name):
            raise GuardError(
                f"refusing hosted {kind} endpoint: {name} is set; hosted access is Entra only"
            )
    doc = load_registration(registration_path)
    deployment_id = doc.get("deployment_id")
    if (
        not isinstance(deployment_id, str)
        or not deployment_id
        or env.get(ENV_HOSTED_DEPLOYMENT_ID) != deployment_id
    ):
        raise GuardError(
            f"refusing hosted {kind} endpoint: {ENV_HOSTED_DEPLOYMENT_ID} does not match the "
            "registered deployment"
        )
    if doc.get("cloud") != "AzureCloud":
        raise GuardError(
            f"refusing hosted {kind} endpoint: only the AzureCloud (Commercial) is allowed"
        )
    registered = doc.get(field_name)
    if not isinstance(registered, str) or not registered:
        raise GuardError(
            f"refusing hosted {kind} endpoint: the registration records no {kind} host"
        )
    registered = registered.lower()
    suffix = _commercial_suffix(kind)
    if not _host_in_suffix(registered, suffix):
        raise GuardError(
            f"refusing hosted {kind} endpoint: the registered host is not a Commercial {kind} host"
        )

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise GuardError(f"refusing hosted {kind} endpoint: the URL cannot be parsed") from None
    if parts.scheme != "https":
        raise GuardError(f"refusing hosted {kind} endpoint: https is required")
    if "@" in parts.netloc:
        raise GuardError(f"refusing hosted {kind} endpoint: credentials in the URL are not allowed")
    if parts.query or parts.fragment:
        raise GuardError(f"refusing hosted {kind} endpoint: a query or fragment is not allowed")
    if port not in (None, _HTTPS_DEFAULT_PORT):
        raise GuardError(f"refusing hosted {kind} endpoint: only the default port is allowed")
    if parts.path not in ("", "/"):
        raise GuardError(f"refusing hosted {kind} endpoint: a path is not allowed")
    host = (parts.hostname or "").lower()
    if host != registered or not _host_in_suffix(host, suffix):
        raise GuardError(
            f"refusing hosted {kind} endpoint host {host!r}: it is not the registered "
            "deployment's host"
        )
    return f"https://{host}/"
