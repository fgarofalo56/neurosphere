"""Region groups for the data access questions (PRP-73 item 1).

The groups are data (``data/region_groups.yaml``, shipped as package data) with a source URL and
retrieval date. The Government cloud has both groups present and empty: nothing is inferred
for it. An unknown group raises ``AccessQueryError`` (reason ``unknown_region_group``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from neurosphere_core.errors.taxonomy import InvalidSchemaError

__all__ = [
    "REGION_GROUPS_FILE",
    "AccessQueryError",
    "RegionGroups",
    "load_region_groups",
    "normalise_regions",
]

REGION_GROUPS_FILE = Path(__file__).parent / "data" / "region_groups.yaml"
_REGION_TOKEN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class AccessQueryError(InvalidSchemaError):
    """A bounded access query was malformed; ``reason`` is a stable code (API maps it to 422).

    Reason codes: ``unknown_region_group``, ``unknown_region``, ``max_depth_exceeded``,
    ``invalid_depth``, ``too_many_assets``.
    """

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail, reason=reason)


@dataclass(frozen=True)
class RegionGroups:
    """Loaded groups: ``clouds[cloud][group]`` is a frozen set of region names."""

    source_url: str
    source_retrieved: str
    clouds: dict[str, dict[str, frozenset[str]]]
    known_regions: dict[str, frozenset[str]]
    known_regions_source_urls: dict[str, str]
    known_regions_retrieved: str

    def is_known_region(self, cloud: str, region: str) -> bool:
        """The one decision point: is ``region`` a known Azure region of ``cloud``."""
        return region.strip().lower() in self.known_regions.get(cloud, frozenset())

    def group_names(self, cloud: str) -> tuple[str, ...]:
        return tuple(sorted(self.clouds.get(cloud, {})))

    def regions_in(self, cloud: str, group: str) -> frozenset[str]:
        """Member regions of ``group`` for ``cloud`` (empty for Government).

        Raises ``AccessQueryError`` (``unknown_region_group``) for an unknown group or cloud.
        """
        members = self.clouds.get(cloud, {}).get(group.strip().lower())
        if members is None:
            raise AccessQueryError("unknown_region_group", "unknown region group")
        return members


def normalise_regions(
    regions: list[str], cloud: str, groups: RegionGroups | None = None
) -> frozenset[str]:
    """Lower-cased request regions; one that is not a known region of ``cloud`` is rejected.

    Raises ``AccessQueryError`` (``unknown_region``) for a malformed token or a region missing
    from the cloud's ``known_regions`` list. Applies to the request filter only; stored assets
    may carry any region token and simply never match.
    """
    known = groups or load_region_groups()
    out: set[str] = set()
    for region in regions:
        token = region.strip().lower()
        if not _REGION_TOKEN.fullmatch(token) or not known.is_known_region(cloud, token):
            raise AccessQueryError("unknown_region", f"unknown region: {region[:64]!r}")
        out.add(token)
    return frozenset(out)


@lru_cache(maxsize=1)
def load_region_groups() -> RegionGroups:
    """Read and validate the packaged YAML (cached)."""
    raw: Any = yaml.safe_load(REGION_GROUPS_FILE.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw.get("source_url") or not raw.get("source_retrieved"):
        raise ValueError("region_groups.yaml needs source_url and source_retrieved")
    clouds: dict[str, dict[str, frozenset[str]]] = {}
    for cloud, groups in dict(raw.get("clouds") or {}).items():
        clouds[str(cloud)] = {
            str(name): frozenset(str(r) for r in (members or []))
            for name, members in dict(groups).items()
        }
    known: dict[str, frozenset[str]] = {}
    urls: dict[str, str] = {}
    for cloud, entry in dict(raw.get("known_regions") or {}).items():
        entry = dict(entry)
        if not entry.get("source_url") or not entry.get("regions"):
            raise ValueError("region_groups.yaml known_regions needs source_url and regions")
        known[str(cloud)] = frozenset(str(r) for r in entry["regions"])
        urls[str(cloud)] = str(entry["source_url"])
    if not raw.get("known_regions_retrieved"):
        raise ValueError("region_groups.yaml needs known_regions_retrieved")
    return RegionGroups(
        source_url=str(raw["source_url"]),
        source_retrieved=str(raw["source_retrieved"]),
        clouds=clouds,
        known_regions=known,
        known_regions_source_urls=urls,
        known_regions_retrieved=str(raw["known_regions_retrieved"]),
    )
