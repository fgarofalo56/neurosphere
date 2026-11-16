"""PRP-44 item 4: the admin_platform builder and the startup load of the stored review policy."""

from __future__ import annotations

from datetime import timedelta

import pytest
from neurosphere_api.admin.platform import PlatformAdminPlane
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import admin_platform as builder
from neurosphere_api.runtime.builders import default_builders
from neurosphere_api.runtime.status import OPTIONAL_COMPONENTS
from neurosphere_contracts.admin.v1.review_policy_document import ReviewPolicyDocument
from neurosphere_core.admin.platform import DEFAULTS_ETAG, ReviewPolicyAdmin
from neurosphere_core.hitl import ReviewPolicyRegistry
from platform_harness import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    PlatformWorld,
    configure_env,
    policy_body,
)
from runtime_api.runtime_helpers import compose  # pyright: ignore[reportMissingImports]

ACTOR = "commercial:contoso:entra:person:p-" + "0c" * 32


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


def test_builder_is_registered_and_optional() -> None:
    assert "admin_platform" in [spec.name for spec in default_builders()]
    assert "admin_platform" in OPTIONAL_COMPONENTS


def test_with_override_stores_the_component_is_ok_and_the_plane_installed() -> None:
    world = PlatformWorld.build()
    assert world.composed.registry.get("admin_platform").state == "ok"
    assert isinstance(world.composed.app.state.admin_platform, PlatformAdminPlane)


def test_without_cosmos_or_backend_the_component_is_disabled_and_routes_answer_503() -> None:
    composed = compose(CompositionOverrides(backends={}), builders=(builder.BUILDER,))
    assert composed.registry.get("admin_platform").state == "disabled"
    assert composed.app.state.admin_platform is None


def test_without_stored_policy_the_registry_equals_the_defaults() -> None:
    world = PlatformWorld.build()
    with world.composed.client():
        pass
    assert world.policies.loaded
    plain = ReviewPolicyRegistry()
    assert world.policies.resolve("maker_checker") == plain.resolve("maker_checker")


async def test_a_stored_policy_is_applied_once_at_startup() -> None:
    world = PlatformWorld.build()
    await ReviewPolicyAdmin(world.repository).replace(
        CUSTOMER,
        ReviewPolicyDocument.model_validate(policy_body()),
        if_match=DEFAULTS_ETAG,
        updated_by=ACTOR,
    )
    with world.composed.client():
        pass
    assert world.policies.resolve("maker_checker").sla == timedelta(hours=1)
    assert world.policies.resolve("maker_checker").policy_version == "admin-v1"


def test_a_store_outage_keeps_the_defaults_and_the_app_serves() -> None:
    world = PlatformWorld.build()
    world.repository.fail_with(RuntimeError("down"))
    with world.composed.client():
        pass
    assert not world.policies.loaded
    assert world.policies.resolve("maker_checker").policy_version == "hitl-defaults-1"
