"""Detector protocol (PRP-101).

A detector is pure and deterministic: ``find`` returns offsets into the text it was given and
a category, never the matched text. It must never log, print or raise with text in the message;
the engine turns any exception into a ``RedactionFailed("detector_error")``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from neurosphere_core.classification.models import Match


@runtime_checkable
class Detector(Protocol):
    #: Lowercase slug, ``^[a-z0-9][a-z0-9._-]{0,63}$``.
    detector_id: str
    #: Semantic version without prefix, ``x.y.z``.
    version: str
    #: Categories this detector can emit.
    kinds: frozenset[str]
    #: True for every credential detector and for ``opaque_secret`` (Clarification 9): the
    #: engine forces ``replaced`` for its matches whatever the configuration.
    always_redact: bool

    def find(self, text: str) -> tuple[Match, ...]:
        """Matches in ``text`` as offsets only; never logs or raises with text."""
        ...
