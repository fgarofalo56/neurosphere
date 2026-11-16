"""Per-key validation of a stored runtime setting and its mapping to the runtime settings classes.

:func:`validate_setting` is the ONE check every write path runs before anything is stored:

1. the key is one of :data:`~neurosphere_core.admin.runtime.keys.SETTING_KEYS`;
2. no field NAME looks like a credential (the copilot ``KEY|SECRET|PASSWORD`` markers): only
   ``setting_key`` and a ``credential.secret_uri`` reference are allowed, so a value that is a
   key can never be stored (references only, A7);
3. ``setting_key`` names the member the key carries;
4. the body validates as ``system_setting`` (``validate_admin_body``: schema, exactly-one member,
   credential-reference shape, customer ids, a Key Vault on the deployment cloud's suffix);
5. cloud rules: a model endpoint (copilot, judge) passes ``endpoint_problem`` for the deployment
   cloud (a Commercial endpoint in a Government deployment is refused, never bridged) and needs a
   managed-identity credential (the runtime never reads a key); a search endpoint is on the
   deployment cloud's search suffix.

Failures are ``invalid_schema`` (422) with a value-free pointer and a reason code.

The ``*_init_args`` helpers turn a validated setting into the init arguments of the settings
class the runtime already uses (pydantic-settings init arguments beat the environment, so env
stays the bootstrap default and that class's own validation still runs, A2). The API and worker
builders own the class; core only names the fields.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import Any, Final

from neurosphere_contracts.admin.v1.system_setting import SystemSetting
from pydantic import BaseModel

from neurosphere_core.admin.models import CloudName, validate_admin_body
from neurosphere_core.admin.runtime.keys import (
    SETTING_KEYS,
    SYSTEM_SETTING_KIND,
    member_of,
)
from neurosphere_core.cloud.profile import CloudName as ProfileCloud
from neurosphere_core.cloud.profile import profile_for
from neurosphere_core.copilot.models.endpoints import endpoint_problem
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue

__all__ = [
    "CREDENTIAL_MARKERS",
    "copilot_init_args",
    "judge_init_args",
    "mcp_server_init_args",
    "refuse_credential_names",
    "scan_init_args",
    "search_init_args",
    "search_service_name",
    "validate_setting",
]

#: Same markers as the copilot builder's credential-shaped env refusal.
CREDENTIAL_MARKERS: Final = ("KEY", "SECRET", "PASSWORD")
_SERVICE: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,48}[a-z0-9]$")
_MODEL_KEYS: Final = frozenset({"copilot", "judge"})


def _refuse(pointer: str, detail: str, reason: str) -> InvalidSchemaError:
    return InvalidSchemaError(
        "runtime setting is invalid", errors=[ValidationIssue(pointer, detail)], reason=reason
    )


def _names(node: Any, pointer: str, parent: str | None) -> Iterator[tuple[str, str, str | None]]:
    if isinstance(node, Mapping):
        for name, value in node.items():
            text = str(name)
            yield f"{pointer}/{text}", text, parent
            yield from _names(value, f"{pointer}/{text}", text)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _names(value, f"{pointer}/{index}", parent)


def _allowed_name(name: str, parent: str | None, pointer: str) -> bool:
    if name == "setting_key" and pointer == "/body/setting_key":
        return True
    return name == "secret_uri" and parent == "credential"


def refuse_credential_names(body: Mapping[str, Any]) -> None:
    """Refuse a body with a credential-shaped field name (names only; values are never read)."""
    for pointer, name, parent in _names(body, "/body", None):
        upper = name.upper()
        if any(m in upper for m in CREDENTIAL_MARKERS) and not _allowed_name(name, parent, pointer):
            raise _refuse(pointer, "a credential is never a setting", "credential_in_setting")


def search_service_name(endpoint: str, cloud: CloudName) -> str:
    """The Azure AI Search service name of ``endpoint`` on ``cloud``'s suffix, else 422."""
    host = endpoint.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
    suffix = profile_for(ProfileCloud(cloud)).search_suffix
    other = profile_for(
        ProfileCloud.GOVERNMENT if cloud == "commercial" else ProfileCloud.COMMERCIAL
    ).search_suffix
    pointer = "/body/search/endpoint"
    if host.endswith(other):
        raise _refuse(pointer, "endpoint belongs to another cloud", "cross_cloud")
    if not host.endswith(suffix) or not _SERVICE.fullmatch(host[: -len(suffix)]):
        raise _refuse(pointer, "not a search service of this cloud", "search_endpoint_invalid")
    return host[: -len(suffix)]


def _check_cloud(setting: SystemSetting, cloud: CloudName | None) -> None:
    key = setting.setting_key
    if key in _MODEL_KEYS:
        member = getattr(setting, key)
        if member.credential.kind != "managed_identity":
            raise _refuse(
                f"/body/{key}/credential",
                "the model endpoint is called with a managed identity",
                "managed_identity_required",
            )
        if cloud is not None:
            problem = endpoint_problem(cloud, member.endpoint.root)
            if problem is not None:
                reason = "cross_cloud" if problem[0] == "endpoint_cloud_mismatch" else problem[0]
                raise _refuse(f"/body/{key}/endpoint", "endpoint refused for this cloud", reason)
    elif key == "search" and cloud is not None and setting.search is not None:
        search_service_name(setting.search.endpoint.root, cloud)


def validate_setting(
    key: str,
    body: Mapping[str, Any] | BaseModel,
    *,
    customer_id: str,
    cloud: CloudName | None,
) -> SystemSetting:
    """Validate ``body`` as the stored value of ``key`` (see module doc); returns the model."""
    if key not in SETTING_KEYS:
        raise _refuse("/key", "unknown setting key", "unknown_setting_key")
    raw = body.model_dump(mode="json", exclude_none=True) if isinstance(body, BaseModel) else body
    if not isinstance(raw, Mapping):
        raise _refuse("/body", "a setting is an object", "admin_body_invalid")
    refuse_credential_names(raw)
    if raw.get("setting_key") != member_of(key):  # type: ignore[arg-type]
        raise _refuse("/body/setting_key", "does not match the key", "setting_key_mismatch")
    model = validate_admin_body(SYSTEM_SETTING_KIND, raw, customer_id=customer_id, cloud=cloud)
    assert isinstance(model, SystemSetting)
    _check_cloud(model, cloud)
    return model


# -- init arguments of the runtime settings classes ----------------------------------------------


def copilot_init_args(setting: SystemSetting, *, env_mode: str) -> dict[str, Any]:
    """``CopilotRuntimeSettings`` fields. Disabled wins; enabled keeps an env adapter mode."""
    if not setting.enabled or setting.copilot is None:
        return {"mode": "disabled"}
    member = setting.copilot
    return {
        "mode": env_mode if env_mode != "disabled" else "approved_endpoint",
        "endpoint": member.endpoint.root,
        "deployment": member.deployment,
        "api_version": member.api_version,
    }


def judge_init_args(setting: SystemSetting) -> dict[str, Any]:
    """Worker ``EvalSettings`` judge fields; disabled keeps the recorded-fixture judge."""
    if not setting.enabled or setting.judge is None:
        return {"judge": "fixture"}
    member = setting.judge
    return {
        "judge": "endpoint",
        "judge_endpoint": member.endpoint.root,
        "judge_deployment": member.deployment,
        "judge_api_version": member.api_version,
    }


def search_init_args(setting: SystemSetting, *, cloud: CloudName) -> dict[str, Any]:
    """``SearchSettings`` fields: Azure AI Search on the stored service, or no search."""
    if not setting.enabled or setting.search is None:
        return {"provider": None}
    return {
        "provider": "azure",
        "service": search_service_name(setting.search.endpoint.root, cloud),
        "index": setting.search.index_name,
    }


def mcp_server_init_args(setting: SystemSetting) -> dict[str, Any] | None:
    """``McpServerSettings`` fields, or ``None`` when the stored setting disables the server."""
    if not setting.enabled or setting.mcp_server is None:
        return None
    return {"resource_server_url": setting.mcp_server.endpoint.root}


def scan_init_args(setting: SystemSetting) -> dict[str, Any]:
    """``ScanSettings`` fields (the interval and scopes are stored for the scheduler only)."""
    return {"enabled": bool(setting.enabled)}
