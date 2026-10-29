"""Compare a desired payload with what the gateway returned.

The comparison is a subset match: every property the payload sets must be present with the
same value; properties ARM adds (read-only fields, defaults) are ignored. Policy XML is compared
after C14N canonicalisation with whitespace stripped, because APIM re-indents policy documents on
save and may change attribute quoting. The XML is our own policy text read back from the
customer's gateway; expat does not resolve external entities.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from xml.etree.ElementTree import ParseError, canonicalize

from neurosphere_connector_apim_gateway.models import ResourceType

__all__ = ["normalize_xml", "payload_matches"]

_POLICY_TYPES = frozenset(
    {ResourceType.POLICY_FRAGMENT, ResourceType.API_POLICY, ResourceType.PRODUCT_POLICY}
)


def normalize_xml(text: str) -> str:
    try:
        return canonicalize(xml_data=text, strip_text=True)
    except ParseError:
        return text.strip()


def _subset(desired: Any, observed: Any) -> bool:
    if isinstance(desired, Mapping):
        if not isinstance(observed, Mapping):
            return False
        return all(
            k in observed and _subset(v, observed[k])  # pyright: ignore[reportUnknownArgumentType]
            for k, v in desired.items()  # pyright: ignore[reportUnknownVariableType]
        )
    if isinstance(desired, list):
        if not isinstance(observed, list) or len(desired) != len(observed):  # pyright: ignore[reportUnknownArgumentType]
            return False
        return all(_subset(d, o) for d, o in zip(desired, observed, strict=True))  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
    return bool(desired == observed)


def payload_matches(
    rtype: ResourceType, desired: Mapping[str, Any], observed: Mapping[str, Any]
) -> bool:
    """True when every desired property is visible in the observed ``properties``."""
    if rtype in _POLICY_TYPES and isinstance(desired.get("value"), str):
        value = observed.get("value")
        if not isinstance(value, str) or normalize_xml(value) != normalize_xml(desired["value"]):
            return False
        rest = {k: v for k, v in desired.items() if k not in ("value", "format")}
        return _subset(rest, observed)
    return _subset(desired, observed)
