"""Versioned detector set (PRP-101 item 5).

A ``DetectorSet`` is the unit the engine runs and the unit a stored redaction names: a slug
``version`` (PRP-99 ``detector_set_version`` grammar) and a ``digest`` over its configuration.
The digest covers each detector's id, version, kinds and ``always_redact`` flag plus the
customer configuration (dictionary ids with a sha256 of their terms, pattern ids with their
patterns): configuration, never content. Changing any detector version or any customer term
or pattern changes the digest.

Customer detectors are built here from their validated configuration (``dictionaries`` and
``patterns``) rather than passed in as objects, so the digest always covers them and the
engine knows which detectors need chunking. ``detectors`` holds every other detector; the
engine runs ``all_detectors`` (``detectors`` then the customer detectors).

Pure: no I/O, no logging. Errors name fields, never terms, patterns or text.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from neurosphere_core.classification.detectors.customer import (
    CustomerDictionary,
    CustomerDictionaryDetector,
    CustomerPattern,
    CustomerPatternDetector,
    build_customer_detectors,
)
from neurosphere_core.classification.detectors.identifiers import identifier_detectors
from neurosphere_core.classification.detectors.secret_detectors import secret_detectors
from neurosphere_core.classification.protocol import Detector

#: Version of the default detector set; bump whenever a built-in detector changes.
DEFAULT_SET_ID: Final = "ns-default"
DEFAULT_SET_VERSION: Final = "ns-detectors-1.0.0"

_SLUG: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SEMVER: Final = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _dictionary_width(dictionary: CustomerDictionary) -> int:
    """Longest possible match in original characters.

    The dictionary detector matches case-folded text; every original character folds to at
    least one character, so a match never spans more original characters than the longest
    folded term.
    """
    return max(len(term.casefold()) for term in dictionary.terms)


def _pattern_width(pattern: CustomerPattern) -> int:
    """Upper bound on a match width from the stdlib parse tree (bounded for accepted patterns)."""
    parser = importlib.import_module("re._parser")
    _, high = parser.parse(pattern.pattern).getwidth()
    return int(high)


@dataclass(frozen=True, slots=True)
class DetectorSet:
    """An immutable, versioned set of detectors with a configuration digest."""

    set_id: str
    version: str
    detectors: tuple[Detector, ...]
    dictionaries: tuple[CustomerDictionary, ...] = ()
    patterns: tuple[CustomerPattern, ...] = ()
    customer_detectors: tuple[Detector, ...] = field(init=False)
    #: Largest possible match width of any customer detector (0 without customer config).
    customer_max_width: int = field(init=False)
    digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.set_id, str) or not _SLUG.fullmatch(self.set_id):
            raise ValueError("set_id must be a lowercase slug")
        if not isinstance(self.version, str) or not _SLUG.fullmatch(self.version):
            raise ValueError("version must match ^[a-z0-9][a-z0-9._-]{0,63}$")
        detectors = tuple(self.detectors)
        dictionaries = tuple(self.dictionaries)
        patterns = tuple(self.patterns)
        if not all(isinstance(d, CustomerDictionary) for d in dictionaries):
            raise TypeError("dictionaries must be CustomerDictionary instances")
        if not all(isinstance(p, CustomerPattern) for p in patterns):
            raise TypeError("patterns must be CustomerPattern instances")
        for detector in detectors:
            if not isinstance(detector, Detector):
                raise TypeError("every detector must implement the Detector protocol")
            if isinstance(detector, CustomerDictionaryDetector | CustomerPatternDetector):
                raise TypeError("customer detectors are configured via dictionaries/patterns")
        customer = build_customer_detectors(dictionaries, patterns)
        everything = detectors + customer
        seen: set[str] = set()
        for detector in everything:
            if not isinstance(detector.detector_id, str) or not _SLUG.fullmatch(
                detector.detector_id
            ):
                raise ValueError("detector_id must be a lowercase slug")
            if not isinstance(detector.version, str) or not _SEMVER.fullmatch(detector.version):
                raise ValueError("detector version must be x.y.z")
            if detector.detector_id in seen:
                raise ValueError("duplicate detector_id in detector set")
            seen.add(detector.detector_id)
        widths = [_dictionary_width(d) for d in dictionaries]
        widths += [_pattern_width(p) for p in patterns]
        object.__setattr__(self, "detectors", detectors)
        object.__setattr__(self, "dictionaries", dictionaries)
        object.__setattr__(self, "patterns", patterns)
        object.__setattr__(self, "customer_detectors", customer)
        object.__setattr__(self, "customer_max_width", max(widths, default=0))
        object.__setattr__(self, "digest", self._compute_digest())

    @property
    def all_detectors(self) -> tuple[Detector, ...]:
        """Built-in and other detectors first, then customer detectors."""
        return self.detectors + self.customer_detectors

    def _compute_digest(self) -> str:
        canonical = {
            "detectors": [
                {
                    "detector_id": d.detector_id,
                    "version": d.version,
                    "kinds": sorted(d.kinds),
                    "always_redact": bool(d.always_redact),
                }
                for d in self.all_detectors
            ],
            "dictionaries": [
                {
                    "dictionary_id": d.dictionary_id,
                    "terms_sha256": _sha256("\n".join(sorted(t.casefold() for t in d.terms))),
                    "sensitivity_category": d.sensitivity_category,
                    "confidence": d.confidence,
                }
                for d in self.dictionaries
            ],
            "patterns": [
                {
                    "pattern_id": p.pattern_id,
                    "pattern": p.pattern,
                    "sensitivity_category": p.sensitivity_category,
                    "confidence": p.confidence,
                }
                for p in self.patterns
            ],
        }
        return _sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")))

    def __repr__(self) -> str:
        return (
            f"DetectorSet(set_id={self.set_id!r}, version={self.version!r}, "
            f"detectors={len(self.all_detectors)}, digest={self.digest[:12]!r})"
        )


def default_detector_set(
    *,
    dictionaries: Iterable[CustomerDictionary] = (),
    patterns: Iterable[CustomerPattern] = (),
) -> DetectorSet:
    """Secret and identifier detectors plus the given customer dictionaries and patterns."""
    return DetectorSet(
        set_id=DEFAULT_SET_ID,
        version=DEFAULT_SET_VERSION,
        detectors=secret_detectors() + identifier_detectors(),
        dictionaries=tuple(dictionaries),
        patterns=tuple(patterns),
    )
