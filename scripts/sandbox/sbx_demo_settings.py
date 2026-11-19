"""Store the demo profile's feature settings (PRP-71 item 5), local only.

    python scripts/sandbox/sbx_demo_settings.py

Writes the stored runtime settings (PRP-45) the local demo profile shows as ``source: stored``:
``scan``, ``mcp_server``, ``search``, a ``copilot`` placeholder and the ``write_targets`` entries.
Every one goes through the SAME audited write the ``PUT /api/v1/admin/system/settings/{key}`` route
runs (``settings_router._write``: ``validate_setting`` incl. the credential-shaped-name refusal,
``check_runtime_settings``, the ``If-Match``-guarded ``AdminConfigRepository`` create and the
before/after audit records on ``<customer>.admin-config``). Nothing here writes a raw document.

Local emulator only: ``NS_ENV`` must be ``local`` and the Cosmos endpoint loopback (``sbx_guard``;
no override); ``--hosted`` is refused. Idempotent: a key that is already stored is left alone and
counted under ``skipped_existing``. Exit 0 and, on stdout and nothing else,
``{"seeded": {"settings": n}, "skipped_existing": n}``; exit 2 = refused, 3 = failed.

Values are non-secret and consistent with ``infra/dev/demo-profile.env``: scan on, the MCP
resource URL on ``127.0.0.1``, the copilot DISABLED (the placeholder keeps a model endpoint for
the console but ``enabled`` is false; PRP-78 owns turning it on), search disabled (no Azure AI
Search is reachable locally), write targets disabled (listed, never registered: the ARM host is a
frozen cloud-profile fact and cannot be pointed at a loopback fake, so apply stays advisory).
Cloud resource ids are SYNTHETIC fixtures (all-zero subscription) that nothing resolves.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
from collections.abc import Mapping, Sequence
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Final

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _path in (HERE, REPO):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from neurosphere_api.admin.system.service import SystemAdminPlane  # noqa: E402
from neurosphere_api.admin.system.settings_router import (  # noqa: E402
    ABSENT_ETAG,
    _write,  # pyright: ignore[reportPrivateUsage]
)
from neurosphere_core.admin import AdminConfigRepository  # noqa: E402
from neurosphere_core.admin.runtime import (  # noqa: E402
    STORED_SETTINGS_UNCONFIGURED,
    SYSTEM_SETTING_KIND,
    WRITE_TARGETS,
    SettingKey,
    StoredSettingsSnapshot,
    document_id,
)
from neurosphere_core.audit import AuditRepository  # noqa: E402
from neurosphere_core.errors import NeuroSphereError  # noqa: E402
from neurosphere_core.scope import IdentityScope  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sbx_guard import GuardError, require_local_endpoint  # noqa: E402

Doc = dict[str, Any]

EXIT_REFUSED: Final = 2
EXIT_FAILED: Final = 3
DEFAULT_COSMOS_ENDPOINT: Final = "http://127.0.0.1:8081"
CATEGORY: Final = "settings"
SCHEMA_VERSION: Final = "1.0.0"
#: SYNTHETIC identifiers: an all-zero subscription and a fixed managed-identity client id.
SUBSCRIPTION: Final = "00000000-0000-4000-8000-000000000001"
IDENTITY_CLIENT_ID: Final = "00000000-0000-4000-8000-000000000002"
RESOURCE_GROUP: Final = "rg-synthetic-sandbox"
#: Same id the seed registers as its synthetic gateway (``sbx_seed_stack.SEED_GATEWAY_ARM_ID``).
APIM_RESOURCE_ID: Final = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RESOURCE_GROUP}"
    "/providers/Microsoft.ApiManagement/service/apim-synthetic-sandbox"
)
FOUNDRY_RESOURCE_ID: Final = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RESOURCE_GROUP}"
    "/providers/Microsoft.CognitiveServices/accounts/ai-synthetic-sandbox"
)
#: Same value as ``NS_MCP_RESOURCE_SERVER_URL`` in the demo profile.
MCP_ENDPOINT: Final = "https://127.0.0.1:8000/mcp"


class ConfigError(RuntimeError):
    """The environment is unusable or unsafe (exit 2)."""


def _identity() -> Doc:
    return {"kind": "managed_identity", "managed_identity_client_id": IDENTITY_CLIENT_ID}


def demo_settings() -> tuple[tuple[SettingKey, Doc], ...]:
    """``(key, body)`` of every stored setting, bodies in the ``SystemSetting`` shape."""

    def body(member: str, enabled: bool, value: Doc) -> Doc:
        return {
            "schema_version": SCHEMA_VERSION,
            "setting_key": member,
            "enabled": enabled,
            member: value,
        }

    return (
        (
            "scan",
            body(
                "scan",
                True,
                {
                    "interval_seconds": 3600,
                    "scopes": [f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RESOURCE_GROUP}"],
                    "credential": _identity(),
                },
            ),
        ),
        (
            "mcp_server",
            body(
                "mcp_server",
                True,
                {"endpoint": MCP_ENDPOINT, "resource_id": None, "credential": None},
            ),
        ),
        (
            "search",
            body(
                "search",
                False,
                {
                    "endpoint": "https://ns-demo-search.search.windows.net",
                    "index_name": "ns-demo-catalog",
                    "resource_id": None,
                    "credential": _identity(),
                },
            ),
        ),
        (
            "copilot",
            body(
                "copilot",
                False,
                {
                    "endpoint": "https://ns-demo-placeholder.openai.azure.com",
                    "deployment": "demo-placeholder",
                    "api_version": "2024-10-21",
                    "resource_id": None,
                    "credential": _identity(),
                },
            ),
        ),
        (
            "write_targets",
            body(
                "write_target",
                False,
                {
                    "target_kind": "apim",
                    "resource_id": APIM_RESOURCE_ID,
                    "credential": _identity(),
                },
            ),
        ),
        (
            "write_targets",
            body(
                "write_target",
                False,
                {
                    "target_kind": "foundry",
                    "resource_id": FOUNDRY_RESOURCE_ID,
                    "credential": _identity(),
                },
            ),
        ),
    )


def require_local(environ: Mapping[str, str]) -> str:
    """The loopback guard, as the seed applies it. Returns the Cosmos endpoint.

    Raises ``ConfigError`` unless ``NS_ENV`` is ``local`` and ``GuardError`` unless the Cosmos
    endpoint is a loopback address (there is no override)."""
    if environ.get("NS_ENV", "local") != "local":
        raise ConfigError("the demo settings only run with NS_ENV=local")
    return require_local_endpoint(environ.get("NS_COSMOS_ENDPOINT") or DEFAULT_COSMOS_ENDPOINT)


async def apply_demo_settings(
    repository: AdminConfigRepository,
    audit: AuditRepository,
    scope: IdentityScope,
    *,
    environ: Mapping[str, str],
    cloud: str = "commercial",
    correlation: str = "seed-demo-settings",
) -> tuple[int, int]:
    """Store every missing demo setting through the PUT route's write. Returns
    ``(created, skipped_existing)``. The caller has applied :func:`require_local`."""
    plane = SystemAdminPlane(
        repository=repository,
        audit=lambda: audit,
        applied=StoredSettingsSnapshot.empty("unconfigured", STORED_SETTINGS_UNCONFIGURED),
        cloud=cloud,
        environ=environ,
        customer_binding="local_default",
    )
    created = skipped = 0
    for key, body in demo_settings():
        target = body["write_target"]["target_kind"] if key == WRITE_TARGETS else None
        doc_id = document_id(key, target)
        if await repository.get(scope.customer_id, SYSTEM_SETTING_KIND, doc_id) is not None:
            skipped += 1
            continue
        await _write(plane, scope, key, body, ABSENT_ETAG, correlation)
        created += 1
    return created, skipped


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Store the demo profile's feature settings through the audited settings write."
    )
    parser.add_argument(
        "--hosted", type=Path, metavar="REGISTRATION", help="refused: the demo is local only"
    )
    return parser


async def _run(environ: Mapping[str, str]) -> Doc:
    import sbx_seed_stack as seed  # lazy: the seed imports this module

    config = seed.resolve_config(seed.DEMO_WORLD, None, environ)
    async with AsyncExitStack() as stack:
        backends = await seed.open_backends(config, stack)
        if backends.admin_config is None or backends.audit is None:
            raise seed.SeedError("the settings store is not available")
        scope = await seed.worker_scope(backends, config)
        created, skipped = await apply_demo_settings(
            backends.admin_config, backends.audit, scope, environ=environ, cloud=config.cloud
        )
    return {"seeded": {CATEGORY: created}, "skipped_existing": skipped}


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    import json

    args = _parser().parse_args(argv)
    environ = dict(os.environ) if env is None else dict(env)
    if args.hosted is not None:
        print("REFUSED: the demo settings are local only (--hosted)", file=sys.stderr)
        return EXIT_REFUSED
    try:
        require_local(environ)
        summary = asyncio.run(_run(environ))
    except (GuardError, ConfigError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except (RuntimeError, NeuroSphereError, ValidationError, OSError) as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_FAILED
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
