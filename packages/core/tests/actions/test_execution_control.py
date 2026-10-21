"""Emergency disable stops execution, fails closed, and never touches intents."""

from __future__ import annotations

from typing import Any, cast

import pytest
from azure.core.exceptions import ServiceRequestError
from azure.cosmos.aio import ContainerProxy
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from neurosphere_core.actions import (
    ExecutionControlState,
    InMemoryExecutionControl,
    require_execution_enabled,
)
from neurosphere_core.actions.cosmos_store import CosmosExecutionControl, CosmosIntentStore
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    RateLimitedError,
)
from pydantic import ValidationError

from .action_helpers import CUSTOMER, DOMAIN, START, Harness


async def test_default_is_enabled() -> None:
    control = InMemoryExecutionControl()
    state = await require_execution_enabled(control, CUSTOMER)
    assert state == ExecutionControlState(customer_id=CUSTOMER)


async def test_disable_blocks_and_enable_restores() -> None:
    control = InMemoryExecutionControl()
    await control.set(CUSTOMER, disabled=True, reason="incident", changed_by="p-admin01", now=START)
    with pytest.raises(CapabilityUnavailableError) as caught:
        await require_execution_enabled(control, CUSTOMER)
    assert caught.value.reason == "emergency_disabled"
    assert caught.value.code == "capability_unavailable"
    # Per customer: another customer is unaffected.
    await require_execution_enabled(control, "fabrikam")
    await control.set(CUSTOMER, disabled=False, reason=None, changed_by="p-admin01", now=START)
    await require_execution_enabled(control, CUSTOMER)


def test_disabled_requires_a_reason() -> None:
    with pytest.raises(ValidationError):
        ExecutionControlState(customer_id=CUSTOMER, disabled=True)


@pytest.mark.parametrize(
    "error",
    [
        DependencyTransientError("down", reason="execution_control_unavailable"),
        RuntimeError("unexpected"),
    ],
    ids=["taxonomy", "unexpected"],
)
async def test_unreachable_control_store_fails_closed(error: Exception) -> None:
    control = InMemoryExecutionControl()
    control.fail_with(error)
    with pytest.raises(DependencyTransientError) as caught:
        await require_execution_enabled(control, CUSTOMER)
    assert caught.value.status == 503


async def test_kill_switch_stops_the_executor_without_touching_the_intent() -> None:
    h = Harness()
    executing = await h.executing()
    await h.control.set(
        CUSTOMER, disabled=True, reason="incident", changed_by="p-admin01", now=h.clock.now
    )
    writes = h.store.replace_calls
    with pytest.raises(CapabilityUnavailableError):
        await h.service.begin_execution(executing.key, worker_id="worker-a")
    with pytest.raises(CapabilityUnavailableError):
        await h.service.recheck_execution(executing, current_target_version="etag-x")
    assert h.store.replace_calls == writes
    assert await h.current(executing.key) == executing
    assert ("action.execute", "emergency_disabled") in h.denials()
    await h.control.set(
        CUSTOMER, disabled=False, reason=None, changed_by="p-admin01", now=h.clock.now
    )
    claimed = await h.service.begin_execution(executing.key, worker_id="worker-a")
    assert claimed.execution is not None
    assert claimed.execution.attempts == 1


async def test_control_outage_blocks_execution() -> None:
    h = Harness()
    executing = await h.executing()
    h.control.fail_with(RuntimeError("control store down"))
    with pytest.raises(DependencyTransientError) as caught:
        await h.service.begin_execution(executing.key, worker_id="worker-a")
    assert caught.value.reason == "execution_control_unavailable"
    assert (await h.current(executing.key)).state == "executing"


# -- Cosmos implementations fail closed (no emulator needed) ----------------------------------


class _BrokenContainer:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def read_item(self, **_: Any) -> dict[str, Any]:
        raise self.error

    async def upsert_item(self, **_: Any) -> dict[str, Any]:
        raise self.error

    async def create_item(self, **_: Any) -> dict[str, Any]:
        raise self.error

    async def replace_item(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise self.error


def _container(error: Exception) -> ContainerProxy:
    return cast(ContainerProxy, _BrokenContainer(error))


async def test_cosmos_control_outage_fails_closed() -> None:
    control = CosmosExecutionControl(_container(ServiceRequestError("unreachable")))
    with pytest.raises(DependencyTransientError) as caught:
        await require_execution_enabled(control, CUSTOMER)
    assert caught.value.reason == "execution_control_unavailable"
    with pytest.raises(DependencyTransientError):
        await control.set(CUSTOMER, disabled=True, reason="x", changed_by="p-a", now=START)


async def test_cosmos_control_absent_document_is_enabled() -> None:
    control = CosmosExecutionControl(_container(CosmosResourceNotFoundError(message="absent")))
    assert (await control.get(CUSTOMER)).disabled is False


async def test_cosmos_control_forbidden_read_fails_closed() -> None:
    control = CosmosExecutionControl(
        _container(CosmosHttpResponseError(status_code=403, message="denied"))
    )
    with pytest.raises(DependencyTransientError):
        await control.get(CUSTOMER)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ServiceRequestError("unreachable"), DependencyTransientError),
        (CosmosHttpResponseError(status_code=503, message="busy"), DependencyTransientError),
        (CosmosHttpResponseError(status_code=429, message="throttled"), RateLimitedError),
    ],
    ids=["unreachable", "503", "429"],
)
async def test_cosmos_intent_store_outage_is_mapped(
    error: Exception, expected: type[Exception]
) -> None:
    store = CosmosIntentStore(_container(error))
    with pytest.raises(expected):
        await store.get(CUSTOMER, DOMAIN, "00000000-0000-4000-8000-000000000001")
    h = Harness()
    drafted = await h.drafted()
    with pytest.raises(expected):
        await store.create(drafted.model_copy(update={"etag": None}))
    with pytest.raises(expected):
        await store.replace(drafted, if_match=drafted.etag or "")
