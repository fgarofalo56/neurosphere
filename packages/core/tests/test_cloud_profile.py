from __future__ import annotations

import pytest
from neurosphere_core.cloud import CloudName, CloudProfile, Settings, load_settings, profile_for
from pydantic import ValidationError

_EXPECTED = {
    CloudName.GOVERNMENT: {
        "login_host": "login.microsoftonline.us",
        "management_host": "management.usgovcloudapi.net",
        "cosmos_suffix": ".documents.azure.us",
        "eventhubs_suffix": ".servicebus.usgovcloudapi.net",
        "search_suffix": ".search.azure.us",
    },
    CloudName.COMMERCIAL: {
        "login_host": "login.microsoftonline.com",
        "management_host": "management.azure.com",
        "cosmos_suffix": ".documents.azure.com",
        "eventhubs_suffix": ".servicebus.windows.net",
        "search_suffix": ".search.windows.net",
    },
}


@pytest.mark.parametrize("cloud", list(CloudName))
def test_suffix_table(cloud: CloudName) -> None:
    profile = profile_for(cloud)
    for field, value in _EXPECTED[cloud].items():
        assert getattr(profile, field) == value


@pytest.mark.parametrize("cloud", list(CloudName))
def test_endpoint_builders(cloud: CloudName) -> None:
    p = profile_for(cloud)
    t = _EXPECTED[cloud]
    assert p.cosmos_endpoint("acct1") == f"https://acct1{t['cosmos_suffix']}/"
    assert p.eventhubs_fqdn("ns-one") == f"ns-one{t['eventhubs_suffix']}"
    assert p.search_endpoint("srch") == f"https://srch{t['search_suffix']}/"
    assert p.authority_url == f"https://{t['login_host']}/"
    assert p.management_url == f"https://{t['management_host']}/"


@pytest.mark.parametrize(
    "name",
    ["", "a", "Acct", "a.evil.com", "a/b", "a@b", "-ab", "ab-", "a" * 51, "a b", "a:443", "a#"],
)
def test_account_names_validated(name: str) -> None:
    p = profile_for(CloudName.GOVERNMENT)
    for build in (p.cosmos_endpoint, p.eventhubs_fqdn, p.search_endpoint):
        with pytest.raises(ValueError, match="invalid account name"):
            build(name)


@pytest.mark.parametrize("field", list(_EXPECTED[CloudName.GOVERNMENT]))
def test_government_rejects_commercial_hosts(field: str) -> None:
    data = {"cloud": CloudName.GOVERNMENT, **_EXPECTED[CloudName.GOVERNMENT]}
    data[field] = _EXPECTED[CloudName.COMMERCIAL][field]
    with pytest.raises(ValidationError, match="suffix set"):
        CloudProfile(**data)


def test_government_rejects_arbitrary_host() -> None:
    data = {"cloud": CloudName.GOVERNMENT, **_EXPECTED[CloudName.GOVERNMENT]}
    data["login_host"] = "login.evil.example"
    with pytest.raises(ValidationError):
        CloudProfile(**data)


def test_profile_frozen() -> None:
    with pytest.raises(ValidationError):
        profile_for(CloudName.COMMERCIAL).login_host = "x"


def _env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for key in ("NS_ENV", "NS_CLOUD"):
        monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_settings_local_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    s = load_settings()
    assert s.env == "local"
    assert s.cloud_profile.cloud is CloudName.COMMERCIAL


@pytest.mark.parametrize("cloud", ["commercial", "government"])
def test_settings_explicit_cloud(monkeypatch: pytest.MonkeyPatch, cloud: str) -> None:
    _env(monkeypatch, NS_ENV="prod", NS_CLOUD=cloud)
    assert load_settings().cloud_profile.cloud.value == cloud


def test_non_local_without_cloud_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, NS_ENV="prod")
    with pytest.raises(ValidationError, match="NS_CLOUD"):
        load_settings()


@pytest.mark.parametrize(
    "values",
    [
        {"NS_CLOUD": "azure"},
        {"NS_CLOUD": "Gov"},
        {"NS_ENV": "production", "NS_CLOUD": "government"},
    ],
)
def test_unknown_values_fail(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    _env(monkeypatch, **values)
    with pytest.raises(ValidationError):
        load_settings()


def test_settings_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, NS_ENV="dev", NS_CLOUD="government")
    s = Settings()
    with pytest.raises(ValidationError):
        s.cloud = CloudName.COMMERCIAL
