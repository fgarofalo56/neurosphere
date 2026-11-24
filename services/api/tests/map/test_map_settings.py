"""``NS_MAP_*`` settings: defaults and range validation (PRP-74 item 1)."""

import pytest
from neurosphere_api.map.settings import MapSettings
from pydantic import ValidationError


def test_defaults() -> None:
    s = MapSettings()
    assert s.topology_enabled is True
    assert s.topology_poll_seconds == 3
    assert s.topology_scan_pages == 20
    assert s.search_scan_pages == 100
    assert s.search_timeout_ms == 8000
    assert s.derived_failing_ratio == 0.5
    assert s.derived_degraded_ratio == 0.34


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_MAP_TOPOLOGY_ENABLED", "false")
    monkeypatch.setenv("NS_MAP_TOPOLOGY_POLL_SECONDS", "10")
    monkeypatch.setenv("NS_MAP_DERIVED_FAILING_RATIO", "0.75")
    s = MapSettings()
    assert s.topology_enabled is False
    assert s.topology_poll_seconds == 10
    assert s.derived_failing_ratio == 0.75


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("NS_MAP_TOPOLOGY_POLL_SECONDS", "0"),
        ("NS_MAP_TOPOLOGY_POLL_SECONDS", "61"),
        ("NS_MAP_SEARCH_SCAN_PAGES", "201"),
        ("NS_MAP_SEARCH_SCAN_PAGES", "0"),
        ("NS_MAP_DERIVED_FAILING_RATIO", "1.5"),
        ("NS_MAP_DERIVED_DEGRADED_RATIO", "0"),
    ],
)
def test_out_of_range_values_fail_at_startup(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        MapSettings()
