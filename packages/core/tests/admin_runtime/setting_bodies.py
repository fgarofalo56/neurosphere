"""Stored runtime setting bodies shared by the PRP-45 core tests (no real endpoint is called)."""

from __future__ import annotations

from typing import Any

CUSTOMER = "contoso"
ACTOR = "commercial:contoso:entra:person:p-" + "0c" * 32
MI = {
    "kind": "managed_identity",
    "managed_identity_client_id": "0b5d0c6e-1f2a-4b3c-8d4e-5f6a7b8c9d0e",
}
RESOURCE = (
    "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-ns"
    "/providers/Microsoft.CognitiveServices/accounts/acct"
)
COMM_MODEL = "https://acct.openai.azure.com"
GOV_MODEL = "https://acct.openai.azure.us"


def model_body(key: str = "copilot", endpoint: str = COMM_MODEL, **over: Any) -> dict[str, Any]:
    member: dict[str, Any] = {
        "endpoint": endpoint,
        "deployment": "gpt-4o",
        "api_version": "2024-10-21",
        "resource_id": RESOURCE,
        "credential": MI,
    }
    member.update(over)
    return {"schema_version": "1.0.0", "setting_key": key, "enabled": True, key: member}


def search_body(endpoint: str = "https://ns-search.search.windows.net") -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "setting_key": "search",
        "enabled": True,
        "search": {
            "endpoint": endpoint,
            "index_name": "neurosphere-catalog",
            "resource_id": None,
            "credential": MI,
        },
    }


def scan_body(enabled: bool = True) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "setting_key": "scan",
        "enabled": enabled,
        "scan": {
            "interval_seconds": 3600,
            "scopes": ["/subscriptions/00000000-0000-0000-0000-000000000001"],
            "credential": MI,
        },
    }


def mcp_body(endpoint: str = "https://ns.example.com/mcp") -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "setting_key": "mcp_server",
        "enabled": True,
        "mcp_server": {"endpoint": endpoint, "resource_id": None, "credential": None},
    }


def write_target_body(kind: str = "foundry") -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "setting_key": "write_target",
        "enabled": True,
        "write_target": {"target_kind": kind, "resource_id": RESOURCE, "credential": MI},
    }


BODIES: dict[str, dict[str, Any]] = {
    "copilot": model_body("copilot"),
    "judge": model_body("judge"),
    "search": search_body(),
    "scan": scan_body(),
    "mcp_server": mcp_body(),
    "write_targets": write_target_body(),
}
