"""Static checks: no literal Azure cloud hostnames in Bicep, Government params stay Government."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BICEP_ROOT = ROOT / "infra" / "bicep"
MODULES = BICEP_ROOT / "modules"
PARAMS = BICEP_ROOT / "params"
MAIN = MODULES / "main.bicep"

# A hostname whose registrable tail is a Commercial Azure/Microsoft cloud domain. The leading
# lookbehind and the trailing word boundary keep this to hostnames, not ordinary words.
_COMMERCIAL_TAILS = (
    r"core\.windows\.net|windows\.net|azure\.com|microsoftonline\.com|azure\.net|"
    r"azure-api\.net|azurewebsites\.net|cloudapp\.net|microsoft\.com|azure-automation\.net"
)
COMMERCIAL_HOST = re.compile(
    rf"(?<![A-Za-z0-9-])(?:[A-Za-z0-9-]+\.)*(?:{_COMMERCIAL_TAILS})(?![A-Za-z0-9-])",
    re.IGNORECASE,
)

# Hosts that only appear as documentation or schema pointers, never as runtime endpoints.
ALLOWED_HOSTS = frozenset(
    {
        "aka.ms",
        "json-schema.org",
        "schema.management.azure.com",  # ARM $schema URL
        "learn.microsoft.com",  # documentation links in comments
    }
)

GOVERNMENT_REGIONS = frozenset(
    {
        "usgovvirginia",
        "usgovtexas",
        "usgovarizona",
        "usgoviowa",
        "usdodeast",
        "usdodcentral",
    }
)

SCANNED_SUFFIXES = {".bicep", ".bicepparam"}


def find_commercial_hosts(text: str) -> list[str]:
    """Return Commercial Azure hostnames in ``text`` that are not allowlisted."""
    return [
        m.group(0)
        for m in COMMERCIAL_HOST.finditer(text)
        if m.group(0).lower() not in ALLOWED_HOSTS
    ]


def _scanned_files() -> list[Path]:
    files = [
        p
        for base in (MODULES, PARAMS)
        for p in base.rglob("*")
        if p.is_file() and (p.suffix in SCANNED_SUFFIXES or p.name == "bicepconfig.json")
    ]
    return sorted(files)


def _param_files(cloud: str) -> list[Path]:
    return sorted((PARAMS / cloud).glob("*.bicepparam"))


@pytest.mark.parametrize(
    "text",
    [
        "https://login.microsoftonline.com/tenant",
        "acct.documents.azure.com",
        "ns.servicebus.windows.net",
        "x.search.windows.net",
        "kv.vault.azure.net",
        "mystore.blob.core.windows.net",
    ],
)
def test_matcher_flags_commercial_hosts(text: str) -> None:
    assert find_commercial_hosts(text), text


@pytest.mark.parametrize(
    "text",
    [
        "param location = 'usgovvirginia'",
        "login.microsoftonline.us",
        "management.usgovcloudapi.net",
        "https://aka.ms/bicep/core-diagnostics",
        "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls10",
        "the azure platform is a cloud",
    ],
)
def test_matcher_ignores_non_commercial_text(text: str) -> None:
    assert find_commercial_hosts(text) == [], text


def test_there_are_files_to_scan() -> None:
    names = {p.name for p in _scanned_files()}
    assert "main.bicep" in names
    assert "main.bicepparam" in names


def test_no_literal_commercial_endpoint_in_bicep_or_params() -> None:
    offenders = {
        str(p.relative_to(ROOT)): hosts
        for p in _scanned_files()
        if (hosts := find_commercial_hosts(p.read_text(encoding="utf-8")))
    }
    assert not offenders, f"literal Commercial Azure hosts found: {offenders}"


def test_commercial_and_government_params_exist_for_same_main() -> None:
    commercial = {p.name for p in _param_files("commercial")}
    government = {p.name for p in _param_files("government")}
    assert commercial, "no commercial params"
    assert commercial == government, "per-cloud param file sets differ"
    for cloud in ("commercial", "government"):
        for p in _param_files(cloud):
            m = re.search(r"^using\s+'([^']+)'", p.read_text(encoding="utf-8"), re.MULTILINE)
            assert m, f"{p} has no using statement"
            assert (p.parent / m.group(1)).resolve() == MAIN.resolve(), p


def _locations(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return re.findall(r"^param\s+location\s*=\s*'([^']+)'", text, re.MULTILINE)


def test_government_params_use_only_government_regions() -> None:
    for p in _param_files("government"):
        locations = _locations(p)
        assert locations, f"{p} sets no location"
        assert set(locations) <= GOVERNMENT_REGIONS, (p, locations)
        assert not find_commercial_hosts(p.read_text(encoding="utf-8")), p


def test_commercial_params_do_not_use_government_regions() -> None:
    for p in _param_files("commercial"):
        locations = _locations(p)
        assert locations, f"{p} sets no location"
        assert not set(locations) & GOVERNMENT_REGIONS, (p, locations)
