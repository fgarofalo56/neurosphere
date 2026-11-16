"""``NS_SEARCH_ENSURE_INDEX``: opt-in index creation through an injected index client."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from neurosphere_core.search.azure.schema import catalog_index_definition
from runtime_data.test_search_builder import (  # pyright: ignore[reportMissingImports]
    FakeAzure,
    _compose,  # pyright: ignore[reportPrivateUsage]
)


class FakeIndexAdmin:
    def __init__(self) -> None:
        self.created: list[Any] = []

    async def create_or_update_index(self, index: Any, **_: Any) -> None:
        self.created.append(index)


def _with_admin(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> FakeIndexAdmin:
    admin = FakeIndexAdmin()
    import runtime_data.test_search_builder as helpers  # pyright: ignore[reportMissingImports]

    original = helpers.data_overrides

    def patched(clock: Any) -> Any:
        base = original(clock)
        return replace(base, backends={**base.backends, "search_index_client": admin})

    monkeypatch.setattr(helpers, "data_overrides", patched)
    _compose_and_start(monkeypatch, env)
    return admin


def _compose_and_start(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    composed, _ = _compose(monkeypatch, env, FakeAzure())
    with composed.client():  # runs the lifespan: startup hooks fire here
        pass


def test_default_creates_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    admin = _with_admin(monkeypatch, {"NS_SEARCH_PROVIDER": "azure", "NS_SEARCH_REGION": "eastus"})
    assert admin.created == []


def test_opt_in_creates_the_catalog_index_once(monkeypatch: pytest.MonkeyPatch) -> None:
    admin = _with_admin(
        monkeypatch,
        {
            "NS_SEARCH_PROVIDER": "azure",
            "NS_SEARCH_REGION": "eastus",
            "NS_SEARCH_ENSURE_INDEX": "true",
            "NS_SEARCH_INDEX": "idx-test",
        },
    )
    assert len(admin.created) == 1
    expected = catalog_index_definition("idx-test")
    assert admin.created[0].name == expected.name
    assert [f.name for f in admin.created[0].fields] == [f.name for f in expected.fields]


def test_unsupported_region_makes_no_request_even_when_opted_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = _with_admin(
        monkeypatch,
        {
            "NS_SEARCH_PROVIDER": "azure",
            "NS_SEARCH_REGION": "marscentral",
            "NS_SEARCH_ENSURE_INDEX": "true",
        },
    )
    assert admin.created == []


def test_fixture_provider_never_ensures(monkeypatch: pytest.MonkeyPatch) -> None:
    admin = _with_admin(
        monkeypatch, {"NS_SEARCH_PROVIDER": "fixture", "NS_SEARCH_ENSURE_INDEX": "true"}
    )
    assert admin.created == []
