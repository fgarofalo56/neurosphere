from __future__ import annotations

import pytest
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ServiceRequestError,
)
from azure.cosmos.exceptions import CosmosHttpResponseError
from azure.eventhub import exceptions as eh
from neurosphere_core.clients import translate_sdk_error, translating
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    RateLimitedError,
    StaleVersionError,
)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, ForbiddenError),
        (403, ForbiddenError),
        (412, StaleVersionError),
        (408, DependencyTransientError),
        (500, DependencyTransientError),
        (503, DependencyTransientError),
        (429, RateLimitedError),
    ],
)
def test_cosmos_status_mapping(status: int, expected: type[Exception]) -> None:
    exc = CosmosHttpResponseError(status_code=status, message="secret-bearing text")
    mapped = translate_sdk_error(exc)
    assert isinstance(mapped, expected)
    assert "secret-bearing" not in str(mapped)


def test_unmapped_status_is_left_alone() -> None:
    assert translate_sdk_error(CosmosHttpResponseError(status_code=404, message="nf")) is None
    assert translate_sdk_error(HttpResponseError(message="x")) is None
    assert translate_sdk_error(ValueError("x")) is None


@pytest.mark.parametrize(
    "exc",
    [
        ServiceRequestError("down"),
        TimeoutError(),
        ConnectionResetError(),
        eh.ConnectError("c"),
        eh.ConnectionLostError("l"),
        eh.OperationTimeoutError("t"),
    ],
)
def test_transient_mapping(exc: Exception) -> None:
    assert isinstance(translate_sdk_error(exc), DependencyTransientError)


def test_auth_mapping() -> None:
    assert isinstance(translate_sdk_error(ClientAuthenticationError("x")), ForbiddenError)
    assert isinstance(translate_sdk_error(eh.AuthenticationError("x")), ForbiddenError)


def test_translating_chains_original() -> None:
    original = CosmosHttpResponseError(status_code=412, message="etag")

    def _fail() -> None:
        raise original

    with pytest.raises(StaleVersionError) as ei, translating():
        _fail()
    assert ei.value.__cause__ is original


def test_translating_passes_through_unmapped() -> None:
    with pytest.raises(KeyError), translating():
        raise KeyError("k")
