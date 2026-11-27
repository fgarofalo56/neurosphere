"""Per-kind body models and the core rules the generated models cannot express (clarification 10).

``AdminConfigDocument.body`` is a union in the generated Pydantic model, so on its own it cannot
say WHICH kind's model applies. :data:`ADMIN_KIND_MODELS` pins it, and :func:`validate_admin_body`
validates a body against its kind's model and then the rules JSON Schema carries in ``if/then`` or
``not`` (which Pydantic ignores, PRP-01 deviation):

* every ``CredentialReference`` names exactly the member its ``kind`` requires (A7);
* a ``SystemSetting`` carries exactly the member its ``setting_key`` names;
* ``ConnectorConfig.settings`` keys are never secret-like (a credential is never a setting);
* ``SpendBudget.thresholds_percent`` is strictly ascending; ``tags_filter`` has at most 16
  entries and a ``cost_center`` value matches the Grant pattern;
* an ``azure_retail_prices`` sheet is Commercial-only and comes from ``prices.azure.com``; a sheet
  must list the deployment cloud (Commercial prices are never a Government fallback);
* a ``ReviewPolicyDocument`` has a ``maker_checker`` default and unique review kinds;
* every canonical id in the body belongs to the document's customer and, when the store knows
  its deployment cloud, to that cloud; a Key Vault secret URI is on that cloud's vault suffix.

Failures are ``invalid_schema`` (422) with RFC 6901 pointers under ``/body`` and value-free
messages: no body content, secret URI or tag value is ever echoed (#190 item 3).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from itertools import pairwise
from types import MappingProxyType
from typing import Any, Final, Literal, get_args
from urllib.parse import urlsplit

from neurosphere_contracts.admin.v1.budget import SpendBudget
from neurosphere_contracts.admin.v1.connector_config import ConnectorConfig
from neurosphere_contracts.admin.v1.domain_definition import DomainDefinition
from neurosphere_contracts.admin.v1.price_sheet_upload import PriceSheetUpload
from neurosphere_contracts.admin.v1.producer_record import ProducerRecord
from neurosphere_contracts.admin.v1.review_policy_document import ReviewPolicyDocument
from neurosphere_contracts.admin.v1.system_setting import SystemSetting
from neurosphere_contracts.notifications.v1.notification_channel import NotificationChannel
from neurosphere_contracts.notifications.v1.notification_subscription import (
    NotificationSubscription,
)
from neurosphere_contracts.policy.v1.enforcement_binding import EnforcementBinding
from pydantic import BaseModel, ValidationError

from neurosphere_core.errors import InvalidSchemaError, ValidationIssue

__all__ = [
    "ADMIN_CONFIG_CONTAINER",
    "ADMIN_CONFIG_PARTITION_KEY_PATH",
    "ADMIN_CONFIG_SCHEMA_VERSION",
    "ADMIN_KINDS",
    "ADMIN_KIND_MODELS",
    "AdminBody",
    "AdminKindName",
    "CloudName",
    "validate_admin_body",
    "validate_kind",
]

ADMIN_CONFIG_CONTAINER: Final = "admin_config"
ADMIN_CONFIG_PARTITION_KEY_PATH: Final = "/customer_id"
#: ``schema_version`` stamped on envelopes this store writes (admin/v1).
ADMIN_CONFIG_SCHEMA_VERSION: Final = "1.0.0"

AdminKindName = Literal[
    "producer",
    "connector_config",
    "domain",
    "budget",
    "price_sheet",
    "review_policy",
    "system_setting",
    "enforcement_binding",
    "notification_channel",
    "notification_subscription",
]
CloudName = Literal["commercial", "government"]
AdminBody = (
    ProducerRecord
    | ConnectorConfig
    | DomainDefinition
    | SpendBudget
    | PriceSheetUpload
    | ReviewPolicyDocument
    | SystemSetting
    | EnforcementBinding
    | NotificationChannel
    | NotificationSubscription
)

#: kind -> the generated model its body must validate against (mirrors the schema's allOf).
ADMIN_KIND_MODELS: Final[Mapping[str, type[BaseModel]]] = MappingProxyType(
    {
        "producer": ProducerRecord,
        "connector_config": ConnectorConfig,
        "domain": DomainDefinition,
        "budget": SpendBudget,
        "price_sheet": PriceSheetUpload,
        "review_policy": ReviewPolicyDocument,
        "system_setting": SystemSetting,
        "enforcement_binding": EnforcementBinding,
        "notification_channel": NotificationChannel,
        "notification_subscription": NotificationSubscription,
    }
)
ADMIN_KINDS: Final[frozenset[str]] = frozenset(get_args(AdminKindName))

_SETTING_MEMBERS: Final = (
    "copilot",
    "judge",
    "search",
    "scan",
    "mcp_server",
    "write_target",
    "notifications",
)
_SECRET_LIKE: Final = re.compile(
    r"(secret|passw|pwd|token|key|sas|signature|credential|connection)"
)
_CANONICAL: Final = re.compile(
    r"^(commercial|government):([a-z0-9._-]+):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$"
)
_VAULT_SUFFIX: Final[Mapping[str, str]] = MappingProxyType(
    {"commercial": ".vault.azure.net", "government": ".vault.usgovcloudapi.net"}
)
_CREDENTIAL_KEYS: Final = frozenset({"kind", "secret_uri", "managed_identity_client_id"})
_MAX_TAGS: Final = 16
_COST_CENTER: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_RETAIL_PRICES_URL: Final = re.compile(r"^https://prices\.azure\.com(/|$)")


def _refuse(pointer: str, detail: str, *, reason: str = "admin_body_invalid") -> InvalidSchemaError:
    return InvalidSchemaError(
        "admin configuration body is invalid",
        errors=[ValidationIssue(pointer, detail)],
        reason=reason,
    )


def validate_kind(kind: str) -> AdminKindName:
    """``kind`` when it is a declared admin kind, else ``invalid_schema`` (unknown_admin_kind)."""
    if kind not in ADMIN_KINDS:
        raise _refuse("/kind", "unknown admin kind", reason="unknown_admin_kind")
    return kind  # type: ignore[return-value]


def _walk(node: Any, pointer: str = "/body") -> Iterator[tuple[str, Any]]:
    yield pointer, node
    if isinstance(node, Mapping):
        for key, value in node.items():
            yield from _walk(value, f"{pointer}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{pointer}/{index}")


def _is_credential(node: Any) -> bool:
    return (
        isinstance(node, Mapping)
        and node.get("kind") in ("key_vault_secret", "managed_identity")
        and set(node) <= _CREDENTIAL_KEYS
    )


def _check_credential(pointer: str, node: Mapping[str, Any], cloud: str | None) -> None:
    has_uri = node.get("secret_uri") is not None
    has_mi = node.get("managed_identity_client_id") is not None
    if node["kind"] == "key_vault_secret":
        if not has_uri or has_mi:
            raise _refuse(pointer, "key_vault_secret needs secret_uri and nothing else")
        host = urlsplit(str(node["secret_uri"])).hostname or ""
        if cloud is not None and not host.endswith(_VAULT_SUFFIX[cloud]):
            raise _refuse(f"{pointer}/secret_uri", "vault is not on the deployment cloud")
    elif not has_mi or has_uri:
        raise _refuse(pointer, "managed_identity needs managed_identity_client_id only")


def _check_tree(body: Mapping[str, Any], customer_id: str, cloud: str | None) -> None:
    for pointer, node in _walk(body):
        if _is_credential(node):
            _check_credential(pointer, node, cloud)
        elif isinstance(node, str):
            match = _CANONICAL.fullmatch(node)
            if match is None:
                continue
            if match.group(2) != customer_id:
                raise _refuse(pointer, "id belongs to another customer", reason="cross_customer")
            if cloud is not None and match.group(1) != cloud:
                raise _refuse(pointer, "id belongs to another cloud", reason="cross_cloud")


def _check_kind_rules(model: BaseModel, customer: str, cloud: str | None) -> None:
    if isinstance(model, SystemSetting):
        present = {m for m in _SETTING_MEMBERS if getattr(model, m) is not None}
        if present != {model.setting_key}:
            raise _refuse("/body", "exactly the member named by setting_key must be set")
    elif isinstance(model, ConnectorConfig):
        for key in model.settings:
            if _SECRET_LIKE.search(key):
                raise _refuse("/body/settings", "a secret-like key is never a setting")
    elif isinstance(model, SpendBudget):
        values = [t.root for t in model.thresholds_percent]
        if any(b <= a for a, b in pairwise(values)):
            raise _refuse("/body/thresholds_percent", "thresholds must be strictly ascending")
        tags = model.tags_filter.root if model.tags_filter is not None else {}
        if len(tags) > _MAX_TAGS:
            raise _refuse("/body/tags_filter", f"at most {_MAX_TAGS} tags")
        if "cost_center" in tags and not _COST_CENTER.fullmatch(tags["cost_center"].root):
            raise _refuse("/body/tags_filter/cost_center", "not a cost center")
    elif isinstance(model, PriceSheetUpload):
        if model.source == "azure_retail_prices":
            if [c.root for c in model.clouds] != ["commercial"]:
                raise _refuse("/body/clouds", "retail prices cover commercial only")
            if not _RETAIL_PRICES_URL.match(model.source_url.root):
                raise _refuse("/body/source_url", "retail prices come from prices.azure.com")
        if cloud is not None and cloud not in {c.root for c in model.clouds}:
            raise _refuse(
                "/body/clouds", "sheet does not apply to this cloud", reason="cross_cloud"
            )
    elif isinstance(model, ReviewPolicyDocument):
        kinds = [d.review_kind.root for d in model.kind_defaults]
        if "maker_checker" not in kinds:
            raise _refuse("/body/kind_defaults", "maker_checker needs a policy (fail closed)")
        if len(kinds) != len(set(kinds)):
            raise _refuse("/body/kind_defaults", "review kinds must be unique")
    elif isinstance(model, ProducerRecord):
        if model.customer_id.root != customer:
            raise _refuse("/body/customer_id", "another customer", reason="cross_customer")
        if cloud is not None and model.cloud.root != cloud:
            raise _refuse("/body/cloud", "another cloud", reason="cross_cloud")


def validate_admin_body(
    kind: str,
    body: Mapping[str, Any] | BaseModel,
    *,
    customer_id: str,
    cloud: CloudName | None = None,
) -> AdminBody:
    """Validate ``body`` as ``kind``'s model plus the core rules above; returns the model.

    ``cloud`` is the deployment's cloud when the caller knows it (a store bound to one
    deployment always does); ``None`` skips only the cloud checks, never the customer checks.
    """
    model_cls = ADMIN_KIND_MODELS[validate_kind(kind)]
    raw = body.model_dump(mode="json", exclude_none=True) if isinstance(body, BaseModel) else body
    try:
        model = model_cls.model_validate(raw)
    except ValidationError as exc:
        raise InvalidSchemaError(
            "admin configuration body is invalid",
            errors=[
                ValidationIssue("/body" + "".join(f"/{p}" for p in err["loc"]), str(err["type"]))
                for err in exc.errors(include_input=False, include_url=False)
            ],
            reason="admin_body_invalid",
        ) from exc
    _check_kind_rules(model, customer_id, cloud)
    _check_tree(model.model_dump(mode="json", exclude_none=True), customer_id, cloud)
    return model  # type: ignore[return-value]
